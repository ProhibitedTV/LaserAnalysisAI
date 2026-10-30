"""Dependency-free local interchange for community reference data.

The loaders in this module never access the network and intentionally return
only normalized, allow-listed fields. Subjective symbol observations remain
context-only data and are never promoted to detector evidence or operational
guidance.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "1.0"
CONFIDENCE_SCORES = {
    "exact": 1.0,
    "inferred": 0.6,
    "missing": 0.0,
    "user_entered": 1.0,
}
PRIVACY_STATUSES = {"not_reviewed", "reviewed", "pseudonymized", "public", "restricted"}
REDACTION_STATUSES = {"not_reviewed", "not_required", "redacted", "required"}
PATTERN_TYPES = {"cross", "dot", "line", "grid", "fan", "unknown"}

EXTERNAL_FIELDS = (
    "wavelength_nm",
    "rated_power_mw",
    "laser_class_label",
    "projection_distance_meters",
    "laser_pattern_type",
    "equipment",
    "tags",
)

SYMBOL_CSV_FIELDS = (
    "record_id",
    "pseudonymous_id",
    "coordinate_x",
    "coordinate_y",
    "coordinate_space",
    "timestamp_seconds",
    "wavelength_nm",
    "laser_pattern_type",
    "transcription",
    "crop_sha256",
    "evidence_role",
    "privacy_status",
    "redaction_status",
    "attribution_json",
    "license_json",
)

_SENSITIVE_KEY_PARTS = {
    "administration",
    "dose",
    "dosage",
    "drug",
    "intake",
    "route",
    "substance",
}
_OPERATIONAL_CONTENT = re.compile(
    r"\b(?:administer|consume|dose|dosage|ingest|inject|microdose|smoke|take)\b"
    r"|\b\d+(?:\.\d+)?\s*(?:mg|mcg|micrograms?|milligrams?)\b",
    re.IGNORECASE,
)
_PSEUDONYM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of a local file's exact bytes."""

    local_path = _local_file(path)
    digest = hashlib.sha256()
    with local_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_local_data(
    path: str | Path,
    *,
    data_kind: str = "external_references",
    privacy_status: str | None = None,
    redaction_status: str | None = None,
    attribution: str | Mapping[str, Any] | None = None,
    license_info: str | Mapping[str, Any] | None = None,
    user_overrides: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Load normalized community data from a local JSON or CSV file.

    ``data_kind`` is either ``external_references`` or
    ``symbol_transcriptions``. URL-like paths are rejected so callers cannot
    accidentally turn this local interoperability core into a network client.
    """

    if data_kind == "external_references":
        return load_external_references(
            path,
            privacy_status=privacy_status,
            redaction_status=redaction_status,
            attribution=attribution,
            license_info=license_info,
            user_overrides=user_overrides,
        )
    if data_kind == "symbol_transcriptions":
        return load_symbol_transcriptions(
            path,
            privacy_status=privacy_status,
            redaction_status=redaction_status,
            attribution=attribution,
            license_info=license_info,
        )
    raise ValueError(f"Unsupported community data kind: {data_kind}")


def load_external_references(
    path: str | Path,
    *,
    privacy_status: str | None = None,
    redaction_status: str | None = None,
    attribution: str | Mapping[str, Any] | None = None,
    license_info: str | Mapping[str, Any] | None = None,
    user_overrides: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Load and normalize allow-listed external-reference records."""

    local_path, source_hash, records, metadata = _read_local_records(path)
    metadata_privacy = metadata.get("privacy") if isinstance(metadata.get("privacy"), Mapping) else {}
    privacy = _privacy_record(
        privacy_status or metadata.get("privacy_status") or metadata_privacy.get("status"),
        redaction_status or metadata.get("redaction_status") or metadata_privacy.get("redaction_status"),
    )
    normalized_attribution = _normalize_attribution(attribution or metadata.get("attribution"))
    normalized_license = _normalize_license(license_info or metadata.get("license"))
    normalized_records = []
    for index, record in enumerate(records):
        normalized_records.append(
            normalize_external_reference(
                record,
                source_sha256=source_hash,
                record_index=index,
                privacy=privacy,
                attribution=normalized_attribution,
                license_info=normalized_license,
                user_overrides=_overrides_for_index(user_overrides, index),
            )
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "external_references",
        "source": _source_record(local_path, source_hash, len(records)),
        "source_sha256": source_hash,
        "privacy": privacy,
        "attribution": normalized_attribution,
        "license": normalized_license,
        "records": normalized_records,
    }


def normalize_external_reference(
    record: Mapping[str, Any],
    *,
    source_sha256: str | None = None,
    record_index: int = 0,
    privacy: Mapping[str, Any] | None = None,
    attribution: str | Mapping[str, Any] | None = None,
    license_info: str | Mapping[str, Any] | None = None,
    user_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize a Veilbreak-like record without retaining unknown fields."""

    if not isinstance(record, Mapping):
        raise TypeError("External reference records must be mappings.")
    source = {_key(key): value for key, value in record.items()}
    overrides = {_key(key): value for key, value in (user_overrides or {}).items()}
    embedded_overrides = record.get("user_entered_fields")
    if isinstance(embedded_overrides, Mapping):
        overrides.update({_key(key): value for key, value in embedded_overrides.items()})

    values: dict[str, Any] = {}
    confidence: dict[str, dict[str, Any]] = {}
    values["wavelength_nm"], confidence["wavelength_nm"] = _resolve_wavelength(source, overrides)
    values["rated_power_mw"], confidence["rated_power_mw"] = _resolve_power(source, overrides)
    values["laser_class_label"], confidence["laser_class_label"] = _resolve_laser_class(source, overrides)
    values["projection_distance_meters"], confidence["projection_distance_meters"] = _resolve_distance(
        source, overrides
    )
    values["laser_pattern_type"], confidence["laser_pattern_type"] = _resolve_pattern(source, overrides)
    values["equipment"], confidence["equipment"] = _resolve_equipment(source, overrides)
    values["tags"], confidence["tags"] = _resolve_tags(source, overrides)

    observed_value, observed_field = _first_present(
        source,
        ("observed_code", "observed_symbols", "perceived_code", "symbol_transcription", "transcription"),
    )
    context = {
        "observed_code": _text(observed_value) if observed_field else None,
        "source_field": observed_field,
        "evidence_role": "context_only",
        "excluded_from_detector_scoring": True,
        "operational_guidance": False,
    }
    sensitive_fields = sorted(
        original_key
        for original_key in record
        if _is_sensitive_key(_key(original_key))
    )
    privacy_record = _privacy_record(
        (privacy or {}).get("status"),
        (privacy or {}).get("redaction_status"),
    )
    reference_id = _reference_id(record, source_sha256, record_index)
    return {
        "schema_version": SCHEMA_VERSION,
        "reference_id": reference_id,
        **values,
        "field_confidence": confidence,
        "context": context,
        "privacy": privacy_record,
        "attribution": _normalize_attribution(attribution or record.get("attribution")),
        "license": _normalize_license(license_info or record.get("license")),
        "provenance": {
            "source_sha256": _optional_sha256(source_sha256),
            "source_record_index": int(record_index),
            "local_only_import": True,
        },
        "safety_filter": {
            "substance_or_dose_fields_removed": sensitive_fields,
            "operational_guidance_created": False,
        },
    }


def load_symbol_transcriptions(
    path: str | Path,
    *,
    privacy_status: str | None = None,
    redaction_status: str | None = None,
    attribution: str | Mapping[str, Any] | None = None,
    license_info: str | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load normalized symbol-transcription records from local CSV or JSON."""

    local_path, source_hash, records, metadata = _read_local_records(path)
    if records:
        metadata = {**_metadata_from_symbol_row(records[0]), **metadata}
    metadata_privacy = metadata.get("privacy") if isinstance(metadata.get("privacy"), Mapping) else {}
    privacy = _privacy_record(
        privacy_status or metadata.get("privacy_status") or metadata_privacy.get("status"),
        redaction_status or metadata.get("redaction_status") or metadata_privacy.get("redaction_status"),
    )
    normalized_attribution = _normalize_attribution(attribution or metadata.get("attribution"))
    normalized_license = _normalize_license(license_info or metadata.get("license"))
    normalized_records = [
        normalize_symbol_transcription(record, source_sha256=source_hash, record_index=index)
        for index, record in enumerate(records)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "symbol_transcriptions",
        "source": _source_record(local_path, source_hash, len(records)),
        "source_sha256": source_hash,
        "privacy": privacy,
        "attribution": normalized_attribution,
        "license": normalized_license,
        "records": normalized_records,
        "evidence_role": "context_only",
        "excluded_from_detector_scoring": True,
    }


def import_symbol_transcriptions_csv(
    path: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    """Import a local symbol-transcription CSV file."""

    local_path = _local_file(path)
    if local_path.suffix.lower() != ".csv":
        raise ValueError("Symbol transcription CSV import requires a .csv file.")
    return load_symbol_transcriptions(local_path, **kwargs)


def normalize_symbol_transcription(
    record: Mapping[str, Any],
    *,
    source_sha256: str | None = None,
    record_index: int = 0,
) -> dict[str, Any]:
    """Normalize one pseudonymous, context-only transcription record."""

    source = {_key(key): value for key, value in record.items()}
    pseudonymous_id = _required_text(
        _first_value(source, ("pseudonymous_id", "pseudonym", "session_id", "participant_id")),
        "pseudonymous_id",
    )
    if not _PSEUDONYM.fullmatch(pseudonymous_id) or "@" in pseudonymous_id:
        raise ValueError("pseudonymous_id must be a non-identifying token using letters, digits, '.', '_' or '-'.")

    x_value, y_value, coordinate_space = _coordinate_values(source)
    timestamp = _timestamp_seconds(
        _first_value(source, ("timestamp_seconds", "timestamp", "time_seconds", "time"))
    )
    wavelength = _bounded_float(
        _first_value(source, ("wavelength_nm", "laser_wavelength_nm", "wavelength")),
        "wavelength_nm",
        minimum=200.0,
        maximum=2000.0,
    )
    pattern = _pattern_value(
        _first_value(source, ("laser_pattern_type", "pattern_type", "pattern")),
        allow_missing=False,
    )
    transcription = _required_text(
        _first_value(source, ("transcription", "observed_code", "observed_symbols")),
        "transcription",
    )
    crop_hash = _optional_sha256(_first_value(source, ("crop_sha256", "crop_hash")))
    explicit_id = _text(_first_value(source, ("record_id", "id")))
    record_id = explicit_id or _symbol_record_id(source_sha256, record_index)
    return {
        "schema_version": SCHEMA_VERSION,
        "record_id": record_id,
        "pseudonymous_id": pseudonymous_id,
        "coordinate": {"x": x_value, "y": y_value, "space": coordinate_space},
        "timestamp_seconds": timestamp,
        "wavelength_nm": wavelength,
        "laser_pattern_type": pattern,
        "transcription": transcription,
        "crop_sha256": crop_hash,
        "evidence_role": "context_only",
        "excluded_from_detector_scoring": True,
        "operational_guidance": False,
        "provenance": {
            "source_sha256": _optional_sha256(source_sha256),
            "source_record_index": int(record_index),
            "local_only_import": True,
        },
    }


def export_symbol_transcriptions_csv(
    records_or_payload: Iterable[Mapping[str, Any]] | Mapping[str, Any],
    output_path: str | Path,
) -> Path:
    """Export normalized transcription records to a deterministic CSV."""

    if isinstance(records_or_payload, Mapping):
        records = records_or_payload.get("records", [])
        privacy = _privacy_record(
            (records_or_payload.get("privacy") or {}).get("status"),
            (records_or_payload.get("privacy") or {}).get("redaction_status"),
        )
        attribution = _normalize_attribution(records_or_payload.get("attribution"))
        license_info = _normalize_license(records_or_payload.get("license"))
    else:
        records = records_or_payload
        privacy = _privacy_record(None, None)
        attribution = _normalize_attribution(None)
        license_info = _normalize_license(None)

    normalized = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise TypeError("Symbol transcription records must be mappings.")
        if "coordinate" in record and record.get("evidence_role") == "context_only":
            normalized.append(dict(record))
        else:
            normalized.append(normalize_symbol_transcription(record, record_index=index))

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SYMBOL_CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for record in normalized:
            coordinate = record.get("coordinate") or {}
            writer.writerow(
                {
                    "record_id": record.get("record_id", ""),
                    "pseudonymous_id": record.get("pseudonymous_id", ""),
                    "coordinate_x": coordinate.get("x", ""),
                    "coordinate_y": coordinate.get("y", ""),
                    "coordinate_space": coordinate.get("space", "pixels"),
                    "timestamp_seconds": record.get("timestamp_seconds", ""),
                    "wavelength_nm": record.get("wavelength_nm", ""),
                    "laser_pattern_type": record.get("laser_pattern_type", "unknown"),
                    "transcription": record.get("transcription", ""),
                    "crop_sha256": record.get("crop_sha256") or "",
                    "evidence_role": "context_only",
                    "privacy_status": privacy["status"],
                    "redaction_status": privacy["redaction_status"],
                    "attribution_json": _compact_json(attribution),
                    "license_json": _compact_json(license_info),
                }
            )
    return output


def _read_local_records(path: str | Path) -> tuple[Path, str, list[dict[str, Any]], dict[str, Any]]:
    local_path = _local_file(path)
    source_hash = sha256_file(local_path)
    suffix = local_path.suffix.lower()
    metadata: dict[str, Any] = {}
    if suffix == ".json":
        with local_path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            container_key = next(
                (key for key in ("records", "data", "references") if isinstance(payload.get(key), list)),
                None,
            )
            if container_key:
                records = payload[container_key]
                metadata = {key: value for key, value in payload.items() if key != container_key}
            else:
                records = [payload]
        else:
            raise ValueError("JSON community data must be an object or a list of objects.")
    elif suffix == ".csv":
        with local_path.open("r", encoding="utf-8-sig", newline="") as handle:
            records = list(csv.DictReader(handle))
    else:
        raise ValueError("Community data must be a local .json or .csv file.")
    if not all(isinstance(record, dict) for record in records):
        raise ValueError("Every community data record must be a JSON object or CSV row.")
    return local_path, source_hash, records, metadata


def _local_file(path: str | Path) -> Path:
    raw = str(path)
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", raw):
        raise ValueError("Network URLs are not supported; provide a local JSON or CSV file.")
    local_path = Path(path)
    if not local_path.is_file():
        raise FileNotFoundError(local_path)
    return local_path


def _source_record(path: Path, source_hash: str, record_count: int) -> dict[str, Any]:
    return {
        "filename": path.name,
        "format": path.suffix.lower().lstrip("."),
        "sha256": source_hash,
        "record_count": record_count,
        "local_path_included": False,
        "network_accessed": False,
    }


def _privacy_record(status: Any, redaction_status: Any) -> dict[str, str]:
    normalized_status = _key(status or "not_reviewed")
    normalized_redaction = _key(redaction_status or "not_reviewed")
    if normalized_status not in PRIVACY_STATUSES:
        raise ValueError(f"Unknown privacy status: {status}")
    if normalized_redaction not in REDACTION_STATUSES:
        raise ValueError(f"Unknown redaction status: {redaction_status}")
    return {"status": normalized_status, "redaction_status": normalized_redaction}


def _normalize_attribution(value: str | Mapping[str, Any] | None) -> dict[str, str | None]:
    if isinstance(value, str):
        value = {"citation": value}
    source = value if isinstance(value, Mapping) else {}
    return {
        "title": _optional_text(source.get("title")),
        "creator": _optional_text(source.get("creator") or source.get("author")),
        "source_url": _optional_text(source.get("source_url") or source.get("url")),
        "citation": _optional_text(source.get("citation")),
    }


def _normalize_license(value: str | Mapping[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, str):
        value = {"name": value}
    source = value if isinstance(value, Mapping) else {}
    return {
        "name": _optional_text(source.get("name") or source.get("license")) or "unspecified",
        "url": _optional_text(source.get("url")),
        "verified": bool(source.get("verified", False)),
    }


def _resolve_wavelength(source: Mapping[str, Any], overrides: Mapping[str, Any]) -> tuple[float | None, dict[str, Any]]:
    override, key = _first_present(overrides, ("wavelength_nm", "laser_wavelength_nm", "wavelength"))
    if key:
        return _wavelength_value(override), _confidence("user_entered", key)
    value, key = _first_present(source, ("wavelength_nm", "laser_wavelength_nm", "wavelength"))
    if key:
        return _wavelength_value(value), _confidence("exact", key)
    color, color_key = _first_present(source, ("color_label", "laser_color", "color"))
    color_map = {"red": 650.0, "green": 532.0, "cyan": 488.0, "blue": 450.0, "violet": 405.0, "purple": 405.0}
    if color_key and _key(color) in color_map:
        return color_map[_key(color)], _confidence("inferred", color_key, "nominal wavelength inferred from color label")
    match = _search_unstructured(source, r"\b(\d{3}(?:\.\d+)?)\s*nm\b")
    if match:
        return _wavelength_value(match[0]), _confidence("inferred", match[1], "parsed from unstructured equipment text")
    return None, _confidence("missing")


def _resolve_power(source: Mapping[str, Any], overrides: Mapping[str, Any]) -> tuple[float | None, dict[str, Any]]:
    keys = (
        "rated_power_mw",
        "laser_power_mw",
        "power_mw",
        "rated_power_w",
        "laser_power_w",
        "power_w",
        "rated_power",
        "laser_power",
        "power",
    )
    override, key = _first_present(overrides, keys)
    if key:
        return _power_mw(override, key), _confidence("user_entered", key)
    value, key = _first_present(source, keys)
    if key:
        return _power_mw(value, key), _confidence("exact", key)
    match = _search_unstructured(
        source,
        r"\b(\d+(?:\.\d+)?)\s*(mw|milliwatts?|w|watts?)\b",
        flags=re.IGNORECASE,
    )
    if match:
        return _power_mw(f"{match[0]} {match[2]}"), _confidence("inferred", match[1], "parsed from unstructured equipment text")
    return None, _confidence("missing")


def _resolve_laser_class(source: Mapping[str, Any], overrides: Mapping[str, Any]) -> tuple[str | None, dict[str, Any]]:
    keys = ("laser_class_label", "laser_class", "class_label", "safety_class", "class")
    override, key = _first_present(overrides, keys)
    if key:
        return _optional_text(override), _confidence("user_entered", key)
    value, key = _first_present(source, keys)
    if key:
        return _optional_text(value), _confidence("exact", key)
    match = _search_unstructured(source, r"\bclass\s*(1m?|2m?|3r|3a|3b|4)\b", flags=re.IGNORECASE)
    if match:
        return f"Class {match[0].upper()}", _confidence("inferred", match[1], "parsed from unstructured equipment text")
    return None, _confidence("missing")


def _resolve_distance(source: Mapping[str, Any], overrides: Mapping[str, Any]) -> tuple[float | None, dict[str, Any]]:
    keys = (
        "projection_distance_meters",
        "projection_distance_m",
        "projection_distance_cm",
        "projection_distance_mm",
        "projection_distance_ft",
        "projection_distance",
        "distance_to_surface",
    )
    override, key = _first_present(overrides, keys)
    if key:
        return _distance_meters(override, key), _confidence("user_entered", key)
    value, key = _first_present(source, keys)
    if key:
        return _distance_meters(value, key), _confidence("exact", key)
    return None, _confidence("missing")


def _resolve_pattern(source: Mapping[str, Any], overrides: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    keys = ("laser_pattern_type", "pattern_type", "laser_pattern", "pattern")
    override, key = _first_present(overrides, keys)
    if key:
        return _pattern_value(override), _confidence("user_entered", key)
    value, key = _first_present(source, keys)
    if key:
        return _pattern_value(value), _confidence("exact", key)
    unstructured = _unstructured_text(source)
    for pattern in sorted(PATTERN_TYPES - {"unknown"}):
        if re.search(rf"\b{re.escape(pattern)}\b", unstructured, re.IGNORECASE):
            return pattern, _confidence("inferred", "unstructured_text", "pattern name found in equipment text")
    return "unknown", _confidence("missing")


def _resolve_equipment(source: Mapping[str, Any], overrides: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    equipment_keys = (
        "equipment",
        "hardware",
        "device",
        "manufacturer_model",
        "laser_model",
        "camera",
        "camera_model",
        "diffraction_optic_type",
        "mount_type",
    )
    override, key = _first_present(overrides, equipment_keys)
    if key:
        return _equipment_record(overrides), _confidence("user_entered", key)
    present = [key for key in equipment_keys if source.get(key) not in (None, "")]
    if present:
        return _equipment_record(source), _confidence("exact", ",".join(present))
    return {}, _confidence("missing")


def _resolve_tags(source: Mapping[str, Any], overrides: Mapping[str, Any]) -> tuple[list[str], dict[str, Any]]:
    override, key = _first_present(overrides, ("tags", "keywords"))
    if key:
        return _tags(override), _confidence("user_entered", key)
    value, key = _first_present(source, ("tags", "keywords"))
    if key:
        return _tags(value), _confidence("exact", key)
    return [], _confidence("missing")


def _equipment_record(source: Mapping[str, Any]) -> dict[str, Any]:
    equipment = source.get("equipment")
    result: dict[str, Any] = {}
    if isinstance(equipment, Mapping):
        for key in ("laser", "camera", "diffraction_optic", "mount"):
            value = equipment.get(key)
            if value not in (None, "") and not _contains_operational_content(value):
                result[key] = _json_safe(value)
    elif equipment not in (None, "") and not _contains_operational_content(equipment):
        result["notes"] = _text(equipment)
    for generic_key in ("hardware", "device"):
        generic_value = source.get(generic_key)
        if generic_value not in (None, "") and not _contains_operational_content(generic_value):
            result.setdefault("notes", _json_safe(generic_value))
    aliases = {
        "laser": ("manufacturer_model", "laser_model"),
        "camera": ("camera", "camera_model"),
        "diffraction_optic": ("diffraction_optic_type",),
        "mount": ("mount_type",),
    }
    for target, keys in aliases.items():
        value = _first_value(source, keys)
        if value not in (None, "") and not _contains_operational_content(value):
            result[target] = _json_safe(value)
    return result


def _coordinate_values(source: Mapping[str, Any]) -> tuple[float, float, str]:
    coordinate = source.get("coordinate")
    if isinstance(coordinate, Mapping):
        x_value = coordinate.get("x")
        y_value = coordinate.get("y")
        space = coordinate.get("space", "pixels")
    else:
        x_value = _first_value(source, ("coordinate_x", "x"))
        y_value = _first_value(source, ("coordinate_y", "y"))
        space = _first_value(source, ("coordinate_space", "space")) or "pixels"
        if (x_value in (None, "") or y_value in (None, "")) and coordinate not in (None, ""):
            parts = re.split(r"\s*[,;]\s*", _text(coordinate), maxsplit=1)
            if len(parts) == 2:
                x_value, y_value = parts
    x = _bounded_float(x_value, "coordinate_x", minimum=0.0)
    y = _bounded_float(y_value, "coordinate_y", minimum=0.0)
    normalized_space = _key(space)
    if normalized_space not in {"pixels", "normalized"}:
        raise ValueError("coordinate_space must be 'pixels' or 'normalized'.")
    if normalized_space == "normalized" and (x > 1.0 or y > 1.0):
        raise ValueError("Normalized coordinates must be between 0 and 1.")
    return x, y, normalized_space


def _timestamp_seconds(value: Any) -> float:
    if value in (None, ""):
        raise ValueError("timestamp_seconds is required.")
    if isinstance(value, str) and ":" in value:
        parts = value.strip().split(":")
        if len(parts) not in {2, 3}:
            raise ValueError("timestamp must be seconds or HH:MM:SS / MM:SS.")
        numbers = [float(part) for part in parts]
        if len(numbers) == 2:
            seconds = numbers[0] * 60 + numbers[1]
        else:
            seconds = numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    else:
        seconds = float(value)
    if seconds < 0:
        raise ValueError("timestamp_seconds must be non-negative.")
    return seconds


def _wavelength_value(value: Any) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)", _text(value))
    if not match:
        raise ValueError("wavelength_nm must contain a numeric value.")
    return _bounded_float(match.group(1), "wavelength_nm", minimum=200.0, maximum=2000.0)


def _power_mw(value: Any, source_key: str = "") -> float:
    text = _text(value).strip()
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*([A-Za-z]*)", text)
    if not match:
        raise ValueError("rated_power_mw must contain a numeric value.")
    amount = float(match.group(1))
    unit = match.group(2).lower()
    if unit in {"w", "watt", "watts"} or (not unit and source_key.endswith("_w")):
        amount *= 1000.0
    if amount < 0:
        raise ValueError("rated_power_mw must be non-negative.")
    return amount


def _distance_meters(value: Any, source_key: str) -> float:
    text = _text(value).strip()
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*([A-Za-z]*)", text)
    if not match:
        raise ValueError("projection distance must contain a numeric value.")
    amount = float(match.group(1))
    unit = match.group(2).lower()
    if source_key.endswith("_cm") or unit in {"cm", "centimeter", "centimeters"}:
        amount /= 100.0
    elif source_key.endswith("_mm") or unit in {"mm", "millimeter", "millimeters"}:
        amount /= 1000.0
    elif source_key.endswith("_ft") or unit in {"ft", "foot", "feet"}:
        amount *= 0.3048
    if amount < 0:
        raise ValueError("projection_distance_meters must be non-negative.")
    return amount


def _pattern_value(value: Any, *, allow_missing: bool = True) -> str:
    if value in (None, ""):
        if allow_missing:
            return "unknown"
        raise ValueError("laser_pattern_type is required.")
    normalized = _key(value)
    if normalized not in PATTERN_TYPES:
        raise ValueError(f"Unknown laser pattern type: {value}")
    return normalized


def _tags(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_tags = re.split(r"[,;]", value)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        raw_tags = list(value)
    else:
        raw_tags = [value]
    tags = []
    for raw_tag in raw_tags:
        tag = _text(raw_tag).strip()
        if tag and not _contains_operational_content(tag):
            tags.append(tag)
    return list(dict.fromkeys(tags))


def _metadata_from_symbol_row(record: Mapping[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if record.get("privacy_status"):
        metadata["privacy_status"] = record["privacy_status"]
    if record.get("redaction_status"):
        metadata["redaction_status"] = record["redaction_status"]
    for output_key, source_key in (("attribution", "attribution_json"), ("license", "license_json")):
        raw = record.get(source_key)
        if raw:
            try:
                decoded = json.loads(str(raw))
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid {source_key} metadata.") from error
            if not isinstance(decoded, dict):
                raise ValueError(f"{source_key} metadata must contain a JSON object.")
            metadata[output_key] = decoded
    return metadata


def _reference_id(record: Mapping[str, Any], source_hash: str | None, index: int) -> str:
    explicit = _optional_text(record.get("reference_id") or record.get("id"))
    if explicit:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", explicit).strip("-")
        if safe:
            return safe[:100]
    prefix = source_hash[:12] if source_hash else "local"
    return f"ext-{prefix}-{index + 1:04d}"


def _symbol_record_id(source_hash: str | None, index: int) -> str:
    prefix = source_hash[:12] if source_hash else "local"
    return f"sym-{prefix}-{index + 1:04d}"


def _confidence(status: str, source_field: str | None = None, note: str | None = None) -> dict[str, Any]:
    record = {
        "status": status,
        "score": CONFIDENCE_SCORES[status],
        "source_field": source_field,
    }
    if note:
        record["note"] = note
    return record


def _search_unstructured(
    source: Mapping[str, Any],
    pattern: str,
    *,
    flags: int = 0,
) -> tuple[str, str, str] | None:
    for key in ("equipment", "hardware", "description", "notes"):
        value = source.get(key)
        if value in (None, "") or isinstance(value, Mapping) or _contains_operational_content(value):
            continue
        match = re.search(pattern, _text(value), flags)
        if match:
            second = match.group(2) if match.lastindex and match.lastindex >= 2 else ""
            return match.group(1), key, second
    return None


def _unstructured_text(source: Mapping[str, Any]) -> str:
    values = []
    for key in ("equipment", "hardware", "description", "notes"):
        value = source.get(key)
        if value not in (None, "") and not isinstance(value, Mapping) and not _contains_operational_content(value):
            values.append(_text(value))
    return " ".join(values)


def _contains_operational_content(value: Any) -> bool:
    return bool(_OPERATIONAL_CONTENT.search(_text(value)))


def _is_sensitive_key(key: str) -> bool:
    return any(part in key.split("_") for part in _SENSITIVE_KEY_PARTS)


def _overrides_for_index(
    overrides: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    index: int,
) -> Mapping[str, Any] | None:
    if overrides is None or isinstance(overrides, Mapping):
        return overrides
    return overrides[index] if index < len(overrides) else None


def _first_present(source: Mapping[str, Any], keys: Sequence[str]) -> tuple[Any, str | None]:
    for key in keys:
        if key in source and source[key] not in (None, ""):
            value = source[key]
            if isinstance(value, Mapping) and "value" in value:
                value = value["value"]
            return value, key
    return None, None


def _first_value(source: Mapping[str, Any], keys: Sequence[str]) -> Any:
    return _first_present(source, keys)[0]


def _key(value: Any) -> str:
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(value).strip())
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _text(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return _compact_json(value)
    return str(value)


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return _text(value).strip() or None


def _required_text(value: Any, field: str) -> str:
    text = _optional_text(value)
    if not text:
        raise ValueError(f"{field} is required.")
    return text


def _bounded_float(
    value: Any,
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if value in (None, ""):
        raise ValueError(f"{field} is required.")
    number = float(value)
    if minimum is not None and number < minimum:
        raise ValueError(f"{field} must be at least {minimum}.")
    if maximum is not None and number > maximum:
        raise ValueError(f"{field} must be at most {maximum}.")
    return number


def _optional_sha256(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = _text(value).lower()
    if not _SHA256.fullmatch(normalized):
        raise ValueError("SHA-256 values must be 64 hexadecimal characters.")
    return normalized


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_safe(value: Any) -> Any:
    try:
        return json.loads(_compact_json(value))
    except (TypeError, ValueError):
        return _text(value)


# Explicit aliases keep the public surface readable for callers with different
# local integration vocabulary.
load_community_data = load_local_data
load_user_supplied_data = load_local_data
normalize_reference = normalize_external_reference
import_symbol_transcriptions = import_symbol_transcriptions_csv
export_symbol_transcriptions = export_symbol_transcriptions_csv


__all__ = [
    "CONFIDENCE_SCORES",
    "EXTERNAL_FIELDS",
    "SCHEMA_VERSION",
    "SYMBOL_CSV_FIELDS",
    "export_symbol_transcriptions",
    "export_symbol_transcriptions_csv",
    "import_symbol_transcriptions",
    "import_symbol_transcriptions_csv",
    "load_community_data",
    "load_external_references",
    "load_local_data",
    "load_symbol_transcriptions",
    "load_user_supplied_data",
    "normalize_external_reference",
    "normalize_reference",
    "normalize_symbol_transcription",
    "sha256_file",
]
