"""Explicitly opted-in public metadata snapshots, never an experiment database."""
from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifacts import sha256_json
from .diagnostics import get_state_dir
from .veilbreak_bridge import (
    CATALOG_TTL, MCP_ENDPOINT, MAX_RESPONSE_BYTES, VeilbreakError,
    browse_public, validated_catalog_provenance,
)

CACHE_VERSION = "veilbreak-public-catalog-v1"
KINDS = {"protocols", "experiments"}
OPTICAL_FIELDS = ("wavelength_nm", "rated_power_mw", "laser_class_label", "projection_distance_meters",
                  "laser_pattern_type", "equipment", "tags")
OPTICAL_SOURCE_FIELDS = set(OPTICAL_FIELDS) | {"laser_wavelength_nm", "laser_wavelength", "laser_power", "laser_class",
                                              "projection_distance", "projection_distance_ft"}


class CatalogCacheError(VeilbreakError):
    pass


def _canonical_record(record: dict[str, Any], kind: str) -> dict[str, Any]:
    if (not isinstance(record, dict) or record.get("source") != "veilbreak"
            or record.get("record_type") != kind[:-1] or type(record.get("record_id")) is not int
            or record["record_id"] < 1):
        raise CatalogCacheError("The saved catalog has an unsupported record. Explicitly refresh it.")
    optical = record.get("optical_metadata")
    if not isinstance(optical, dict):
        raise CatalogCacheError("The saved catalog has unsupported optical metadata. Explicitly refresh it.")
    metadata = {}
    for field in ("wavelength_nm", "rated_power_mw", "projection_distance_meters"):
        value = optical.get(field)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise CatalogCacheError("The saved catalog has invalid optical values. Explicitly refresh it.")
        metadata[field] = value
    metadata["laser_class_label"] = str(optical.get("laser_class_label"))[:64] if isinstance(optical.get("laser_class_label"), str) else None
    pattern = optical.get("laser_pattern_type")
    metadata["laser_pattern_type"] = pattern if isinstance(pattern, str) and pattern in {"cross", "dot", "line", "grid", "fan", "unknown"} else "unknown"
    equipment = optical.get("equipment") or {}
    metadata["equipment"] = {key: value[:2048] for key, value in equipment.items()
                             if key in {"laser", "camera", "diffraction_optic", "mount", "notes"} and isinstance(value, str)} if isinstance(equipment, dict) else {}
    tags = optical.get("tags") or []
    metadata["tags"] = [value[:80] for value in tags[:100] if isinstance(value, str)] if isinstance(tags, list) else []
    confidence = {}
    details = record.get("field_confidence")
    for field, value in (details if isinstance(details, dict) else {}).items():
        if field in OPTICAL_FIELDS and isinstance(value, dict):
            status = value.get("status")
            if isinstance(status, str) and status in {"exact", "inferred", "missing", "user_entered"}:
                origin = value.get("source_field")
                allowed = OPTICAL_SOURCE_FIELDS | {"meta." + key for key in OPTICAL_SOURCE_FIELDS}
                confidence[field] = {"status": status, "source_field": origin if isinstance(origin, str) and origin in allowed else None}
    return {"source": "veilbreak", "record_type": kind[:-1], "record_id": record["record_id"],
            "title": record.get("title", "")[:160] if isinstance(record.get("title"), str) else f"Veilbreak {kind[:-1]} #{record['record_id']}",
            "optical_metadata": metadata, "field_confidence": confidence,
            "evidence_role": "context_only", "excluded_from_detector_scoring": True}


class CatalogCache:
    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory is not None else get_state_dir() / "public-catalog-cache"

    def _path(self, kind: str) -> Path:
        if kind not in KINDS:
            raise ValueError("Catalog must be protocols or experiments.")
        path = self.directory / f"veilbreak-{kind}-v1.json"
        if path.is_symlink() or path.resolve().parent != self.directory.resolve():
            raise CatalogCacheError("The catalog cache path is not a managed local file.")
        return path

    def save(self, kind: str, records: list[dict[str, Any]], provenance: dict[str, Any]) -> None:
        path = self._path(kind)
        provenance = validated_catalog_provenance(provenance)
        rows = [_canonical_record(record, kind) for record in records]
        payload = {"schema_version": CACHE_VERSION, "kind": kind, "provenance": provenance,
                   "records": rows, "records_sha256": sha256_json(rows)}
        encoded = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_RESPONSE_BYTES:
            raise CatalogCacheError("The sanitized catalog exceeds the local snapshot size limit.")
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(dir=self.directory, prefix=".veilbreak-", suffix=".tmp")
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def load(self, kind: str, *, now: datetime | None = None) -> dict[str, Any]:
        path = self._path(kind)
        try:
            with path.open("rb") as handle:
                raw = handle.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError
            payload = json.loads(raw)
            if payload.get("schema_version") != CACHE_VERSION or payload.get("kind") != kind:
                raise ValueError
            rows = payload["records"]
            if not isinstance(rows, list) or payload["records_sha256"] != sha256_json(rows):
                raise ValueError
            provenance = validated_catalog_provenance(payload["provenance"], now=now)
            rows = [_canonical_record(record, kind) for record in rows]
        except FileNotFoundError as exc:
            raise CatalogCacheError("No saved catalog is available. Opt in and explicitly refresh the public catalog first.") from exc
        except (KeyError, TypeError, AttributeError, ValueError, UnicodeError) as exc:
            raise CatalogCacheError("The saved catalog is invalid or damaged. Explicitly refresh it.") from exc
        provenance["origin"] = "saved"
        return _view(rows, provenance, "saved")

    def clear(self) -> int:
        # Fixed managed files only; no recursive deletion, globbing or media access.
        paths = [self._path(kind) for kind in sorted(KINDS)]
        count = sum(path.exists() for path in paths)
        for path in paths:
            path.unlink(missing_ok=True)
        return count


def _view(records: list[dict[str, Any]], provenance: dict[str, Any], status: str) -> dict[str, Any]:
    return {"records": [{**record, "catalog_provenance": dict(provenance)} for record in records],
            "provenance": dict(provenance), "cache_status": status}


def refresh_catalog(kind: str, *, cache_enabled: bool = False, cache: CatalogCache | None = None,
                    client=None) -> dict[str, Any]:
    if type(cache_enabled) is not bool:
        raise ValueError("Catalog saving requires an explicit boolean choice.")
    records = browse_public(kind, client=client)
    now = datetime.now(timezone.utc)
    provenance = validated_catalog_provenance({"origin": "live", "source_endpoint": MCP_ENDPOINT,
                                              "retrieved_at": now.isoformat(), "expires_at": (now + CATALOG_TTL).isoformat()})
    status = "disabled"
    if cache_enabled:
        try:
            (cache or CatalogCache()).save(kind, records, provenance)
            status = "saved"
        except (OSError, ValueError, VeilbreakError):
            status = "save_failed"
    return _view(records, provenance, status)


def open_saved_catalog(kind: str, *, cache_enabled: bool = False, cache: CatalogCache | None = None) -> dict[str, Any]:
    if cache_enabled is not True:
        raise CatalogCacheError("Enable the optional public catalog cache before opening a saved snapshot.")
    return (cache or CatalogCache()).load(kind)
