"""Optional, read-only access to Veilbreak's published community research catalog.

The public MCP endpoint is fixed and never receives experiment paths, footage,
personal notes, session IDs, credentials, or detector results. Imported records
are reduced to allow-listed optical metadata; they remain context-only.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import __version__
from .community_data import normalize_external_reference

MCP_ENDPOINT = "https://veilbreak.ai/api/mcp"
MCP_VERSION = "2025-03-26"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
TIMEOUT_SECONDS = 12
CATALOG_TTL = timedelta(hours=24)
LICENSE_POLICY_URL = "https://veilbreak.ai/data-usage"

_TOOLS = {
    "protocols": ("get_protocols", "get_protocol_by_id"),
    "experiments": ("get_experiments", "get_experiment_by_id"),
}


class VeilbreakError(RuntimeError):
    """A public catalog request could not be completed safely."""


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise VeilbreakError("Veilbreak redirected the request; refusing to contact a different endpoint.")


def _parse_rpc_response(raw: bytes, content_type: str, expected_id: int) -> dict[str, Any]:
    """Accept a JSON-RPC response or MCP's SSE-delivered JSON-RPC message."""
    try:
        text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError as exc:
        raise VeilbreakError("Veilbreak returned invalid UTF-8 data.") from exc
    candidates: list[Any] = []
    if "text/event-stream" in content_type.lower():
        for event in text.split("\n\n"):
            data = "\n".join(
                line[5:].strip() for line in event.splitlines() if line.startswith("data:")
            )
            if data:
                try:
                    candidates.append(json.loads(data))
                except json.JSONDecodeError:
                    continue
    else:
        try:
            candidates.append(json.loads(text))
        except json.JSONDecodeError as exc:
            raise VeilbreakError("Veilbreak returned non-JSON data.") from exc
    for item in candidates:
        if isinstance(item, dict) and item.get("id") == expected_id:
            if item.get("error"):
                raise VeilbreakError("Veilbreak rejected the request; review the server compatibility.")
            if not isinstance(item.get("result"), dict):
                raise VeilbreakError("Veilbreak returned an unexpected MCP response.")
            return item["result"]
    raise VeilbreakError("Veilbreak did not return the requested MCP response.")


class VeilbreakClient:
    """Small dependency-free MCP client; public read-only tool calls only."""

    def __init__(self, *, timeout: int = TIMEOUT_SECONDS):
        self.timeout = timeout

    def _rpc(
        self,
        method: str,
        params: Mapping[str, Any],
        request_id: int,
        session: str | None = None,
        *,
        notification: bool = False,
    ) -> tuple[dict[str, Any], str | None]:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": dict(params)}
        if not notification:
            payload["id"] = request_id
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": MCP_VERSION,
            "User-Agent": "LaserLab/VeilbreakReadOnlyBridge",
        }
        if session:
            headers["Mcp-Session-Id"] = session
        request = Request(
            MCP_ENDPOINT,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with build_opener(_NoRedirects()).open(request, timeout=self.timeout) as response:
                if response.geturl() != MCP_ENDPOINT:
                    raise VeilbreakError("Unexpected Veilbreak destination.")
                new_session = response.headers.get("Mcp-Session-Id") or session
                data = response.read(MAX_RESPONSE_BYTES + 1)
                mime = response.headers.get("Content-Type", "")
                if len(data) > MAX_RESPONSE_BYTES:
                    raise VeilbreakError("Veilbreak response exceeds the safe size limit.")
        except HTTPError as exc:
            if exc.code == 429:
                raise VeilbreakError("Veilbreak is rate limiting requests. Wait before browsing again.") from exc
            if exc.code in (401, 403):
                raise VeilbreakError("Veilbreak refused public catalog access. The MCP catalog is documented as keyless; do not enter a key in LaserLab.") from exc
            raise VeilbreakError("Veilbreak's public MCP endpoint returned an HTTP error. Try again later or import a local JSON/CSV export.") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise VeilbreakError(
                "Could not reach Veilbreak's public MCP endpoint. "
                "Try again later or import a local JSON/CSV export."
            ) from exc
        if notification:
            return {}, new_session
        return _parse_rpc_response(data, mime, request_id), new_session

    def call(self, tool: str, arguments: Mapping[str, Any] | None = None) -> Any:
        if tool not in {"get_protocols", "get_protocol_by_id", "get_experiments",
                        "get_experiment_by_id", "get_schema"}:
            raise ValueError("Only Veilbreak's published read-only tools are permitted.")
        args = dict(arguments or {})
        if tool.endswith("_by_id"):
            if not isinstance(args.get("id"), int) or isinstance(args["id"], bool) or args["id"] < 1:
                raise ValueError("Veilbreak record ID must be a positive integer.")
            args = {"id": args["id"]}
        else:
            args = {}
        session = self._initialize()
        result, _ = self._rpc("tools/call", {"name": tool, "arguments": args}, 2, session)
        return _tool_payload(result)

    def _initialize(self) -> str | None:
        init, session = self._rpc(
            "initialize",
            {"protocolVersion": MCP_VERSION, "capabilities": {},
             "clientInfo": {"name": "LaserLab", "version": __version__}},
            1,
        )
        if init.get("protocolVersion") != MCP_VERSION:
            raise VeilbreakError("Veilbreak negotiated an unsupported MCP version. Check compatibility before retrying.")
        self._rpc("notifications/initialized", {}, 0, session, notification=True)
        return session


def _tool_payload(result: Mapping[str, Any]) -> Any:
    if result.get("isError"):
        raise VeilbreakError("Veilbreak reported an error reading the public catalog.")
    if isinstance(result.get("structuredContent"), (dict, list)):
        return result["structuredContent"]
    blocks = result.get("content", [])
    if isinstance(blocks, list):
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                try:
                    return json.loads(block["text"])
                except (KeyError, TypeError, json.JSONDecodeError):
                    continue
    raise VeilbreakError("Veilbreak returned a catalog format LaserLab could not parse.")


def _records(payload: Any, kind: str) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        pagination = payload.get("pagination")
        if (isinstance(pagination, Mapping) and (
            pagination.get("has_more") or pagination.get("total_pages") not in (None, 0, 1)
        )) or any(payload.get(key) for key in ("nextCursor", "next_cursor", "next")):
            raise VeilbreakError("Veilbreak returned a partial catalog. Its MCP tools do not advertise pagination; LaserLab will not silently omit remaining records.")
        for key in ("data", kind, "records", "items", "results"):
            if key in payload:
                records = _records(payload[key], kind)
                total = pagination.get("total") if isinstance(pagination, Mapping) else None
                if isinstance(total, int) and total > len(records):
                    raise VeilbreakError("Veilbreak returned a partial catalog. Remaining records are unavailable through the advertised MCP tools.")
                return records
        if "id" in payload:
            return [payload]
    raise VeilbreakError("Veilbreak returned an unsupported catalog shape.")


def safe_public_record(record: Mapping[str, Any], kind: str) -> dict[str, Any]:
    """Allow-list only optical fields. Never retain substance, dose or participant data."""
    if kind not in _TOOLS:
        raise ValueError("Record type must be protocols or experiments.")
    identifier = record.get("id")
    if isinstance(identifier, bool) or not str(identifier).isdigit() or int(identifier) <= 0:
        raise VeilbreakError("Veilbreak record has no valid numeric ID.")
    identifier = int(identifier)
    title = str(record.get("title") or f"Veilbreak {kind[:-1]} #{identifier}")[:160]
    optical_keys = (
        "laser_wavelength_nm", "wavelength_nm", "laser_power", "rated_power_mw",
        "laser_class", "laser_class_label", "projection_distance", "projection_distance_ft",
        "projection_distance_meters", "equipment", "laser_pattern_type", "tags",
        "laser_wavelength",
    )
    meta = record.get("meta")
    meta = meta if isinstance(meta, Mapping) else {}
    source = {}
    origins = {}
    for key in optical_keys:
        for candidate, prefix in ((record, ""), (meta, "meta.")):
            if key in candidate and candidate[key] not in (None, ""):
                source[key] = candidate[key]
                origins[key] = prefix + key
                break
    # Veilbreak's published schema calls this field laser_wavelength, while
    # LaserLab's normalizer expects wavelength_nm or laser_wavelength_nm.
    if "laser_wavelength" in source and not any(
        key in source for key in ("wavelength_nm", "laser_wavelength_nm")
    ):
        source["wavelength_nm"] = source["laser_wavelength"]
        origins["wavelength_nm"] = origins["laser_wavelength"]
    # The live get_schema response defines projection_distance in FEET, unlike
    # the generic community-import default of meters. Explicit unit keys win.
    if "projection_distance" in source:
        source.setdefault("projection_distance_ft", source["projection_distance"])
        origins.setdefault("projection_distance_ft", origins["projection_distance"])
        del source["projection_distance"]
    # Never save free-form descriptions, questionnaire answers, or perceived symbols.
    try:
        normalized = normalize_external_reference(source, record_index=identifier)
    except (TypeError, ValueError) as exc:
        raise VeilbreakError("Veilbreak returned invalid optical metadata. No reference was linked.") from exc
    confidence = normalized.get("field_confidence", {})
    for detail in confidence.values():
        field = detail.get("source_field")
        if field in origins:
            detail["source_field"] = origins[field]
        if field == "projection_distance_ft":
            detail["note"] = "Veilbreak reports feet; normalized to meters. Reported context, not a local measurement."
    return {
        "source": "veilbreak",
        "record_type": kind[:-1],
        "record_id": identifier,
        "title": title,
        "optical_metadata": {
            key: normalized.get(key) for key in (
                "wavelength_nm", "rated_power_mw", "laser_class_label",
                "projection_distance_meters", "laser_pattern_type", "equipment", "tags",
            )
        },
        "field_confidence": confidence,
        "evidence_role": "context_only",
        "excluded_from_detector_scoring": True,
    }


def browse_public(kind: str, *, client: VeilbreakClient | None = None) -> list[dict[str, Any]]:
    """Read approved public catalog entries. No background polling or uploads."""
    if kind not in _TOOLS:
        raise ValueError("Record type must be protocols or experiments.")
    payload = (client or VeilbreakClient()).call(_TOOLS[kind][0])
    return [safe_public_record(record, kind) for record in _records(payload, kind)]


def check_public_compatibility(*, client: VeilbreakClient | None = None) -> dict[str, Any]:
    """Explicit live protocol check returning counts/schema facts, never raw records.

    Does not run at startup, during ordinary analysis, or in offline test/CI.
    Maintainer coordination, experiment-record acceptance and contribution
    authorization are separate from this point-in-time public protocol probe.
    """
    client = client or VeilbreakClient()
    session = client._initialize()
    discovery, _ = client._rpc("tools/list", {}, 2, session)
    if discovery.get("nextCursor"):
        raise VeilbreakError("Veilbreak tool discovery is incomplete; check compatibility manually.")
    advertised = discovery.get("tools")
    if not isinstance(advertised, list):
        raise VeilbreakError("Veilbreak returned an unsupported tool-discovery schema.")
    tools = {tool["name"]: tool for tool in advertised
             if isinstance(tool, Mapping) and isinstance(tool.get("name"), str)}
    expected = {name for names in _TOOLS.values() for name in names} | {"get_schema"}
    if not expected.issubset(tools):
        raise VeilbreakError("Veilbreak is missing an expected read-only catalog tool.")

    def obj(value: Any) -> Mapping[str, Any]:
        return value if isinstance(value, Mapping) else {}

    for name in ("get_protocol_by_id", "get_experiment_by_id"):
        schema = obj(tools[name].get("inputSchema"))
        required = schema.get("required")
        if (obj(obj(schema.get("properties")).get("id")).get("type") not in ("integer", "number")
                or not isinstance(required, list) or "id" not in required):
            raise VeilbreakError("Veilbreak's record-ID schema changed; check compatibility manually.")

    def invoke(name: str, args: dict[str, Any], request_id: int) -> Any:
        result, _ = client._rpc("tools/call", {"name": name, "arguments": args}, request_id, session)
        return _tool_payload(result)

    schema = invoke("get_schema", {}, 3)
    fields = obj(obj(obj(schema).get("fields")).get("protocol"))
    units = {"laser_wavelength": "nanometers", "laser_power": "milliwatts", "projection_distance": "feet"}
    if any(unit not in str(obj(fields.get(field)).get("description", "")).lower()
           for field, unit in units.items()):
        raise VeilbreakError("Veilbreak's reported optical units changed or are missing. Do not assume local measurement units.")
    records = [safe_public_record(row, "protocols") for row in _records(invoke("get_protocols", {}, 4), "protocols")]
    by_id_checked = False
    if records:
        identifier = records[0]["record_id"]
        returned = _records(invoke("get_protocol_by_id", {"id": identifier}, 5), "protocols")
        if len(returned) != 1 or safe_public_record(returned[0], "protocols")["record_id"] != identifier:
            raise VeilbreakError("Veilbreak's protocol-ID lookup did not match the catalog.")
        by_id_checked = True
    error_result, _ = client._rpc("tools/call", {"name": "get_protocol_by_id", "arguments": {"id": 9007199254740991}}, 6, session)
    if error_result.get("isError") is not True:
        raise VeilbreakError("Veilbreak did not return the expected missing-protocol error; check compatibility manually.")
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": MCP_ENDPOINT,
        "protocol_version": MCP_VERSION,
        "read_only_tools": sorted(expected),
        "protocol_records": len(records),
        "protocol_by_id_checked": by_id_checked,
        "missing_protocol_reported_as_error": error_result.get("isError") is True,
        "reported_units": units,
        "optical_field_counts": {field: sum(record["optical_metadata"].get(field) is not None for record in records)
                                 for field in ("wavelength_nm", "rated_power_mw", "projection_distance_meters")},
        "scope": "Point-in-time public protocol transport/schema check; not native, volunteer, experiment-record or authorized contribution acceptance.",
    }


def read_public_record(kind: str, record_id: int, *,
                       client: VeilbreakClient | None = None) -> dict[str, Any]:
    """Get one published record by numeric ID, reducing it to safe metadata."""
    if kind not in _TOOLS:
        raise ValueError("Record type must be protocols or experiments.")
    if type(record_id) is not int or record_id < 1:
        raise ValueError("Record ID must be a positive integer.")
    payload = (client or VeilbreakClient()).call(_TOOLS[kind][1], {"id": record_id})
    entries = _records(payload, kind)
    if len(entries) != 1:
        raise VeilbreakError("Veilbreak returned no matching published record.")
    record = safe_public_record(entries[0], kind)
    if record["record_id"] != record_id:
        raise VeilbreakError("Veilbreak returned no matching published record.")
    return record


def validated_catalog_provenance(value: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Validate bounded snapshot age; this is not authentication of provider data."""
    try:
        retrieved = datetime.fromisoformat(value["retrieved_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00"))
        current = now or datetime.now(timezone.utc)
        if (retrieved.tzinfo is None or expires.tzinfo is None or current.tzinfo is None
                or value.get("source_endpoint") != MCP_ENDPOINT or value.get("origin") not in {"live", "saved"}
                or expires - retrieved != CATALOG_TTL or not retrieved <= current < expires):
            raise ValueError
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise VeilbreakError("The public catalog snapshot is expired or invalid. Explicitly refresh it before use.") from exc
    return {"source_endpoint": MCP_ENDPOINT, "origin": value["origin"],
            "retrieved_at": retrieved.astimezone(timezone.utc).isoformat(),
            "expires_at": expires.astimezone(timezone.utc).isoformat(),
            "license_policy_url": LICENSE_POLICY_URL, "license_status": "per_record_unverified"}


def linked_record(public_record: Mapping[str, Any]) -> dict[str, Any]:
    """Small persisted context reference; not a recording or detector input."""
    if public_record.get("source") != "veilbreak":
        raise ValueError("Source must be Veilbreak.")
    record_type = public_record.get("record_type")
    record_id = public_record.get("record_id")
    if record_type not in ("protocol", "experiment") or type(record_id) is not int or record_id < 1:
        raise ValueError("Invalid Veilbreak reference.")
    safe_keys = ("wavelength_nm", "rated_power_mw", "laser_class_label",
                 "projection_distance_meters", "laser_pattern_type", "equipment", "tags")
    allowed = public_record.get("optical_metadata") or {}
    if not isinstance(allowed, Mapping):
        raise ValueError("Invalid optical metadata.")
    optical_metadata = {key: allowed.get(key) for key in safe_keys}
    provenance = {
        "source": "veilbreak",
        "record_type": record_type,
        "record_id": record_id,
        "title": str(public_record.get("title") or "")[:160],
        "optical_metadata": optical_metadata,
    }
    fingerprint = hashlib.sha256(
        json.dumps(provenance, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    catalog = public_record.get("catalog_provenance")
    if catalog is not None and not isinstance(catalog, Mapping):
        raise ValueError("Invalid public catalog provenance. Explicitly refresh the catalog.")
    catalog = validated_catalog_provenance(catalog) if isinstance(catalog, Mapping) else None
    return {
        **provenance,
        "retrieved_at": catalog["retrieved_at"] if catalog else datetime.now(timezone.utc).isoformat(),
        **({"catalog_provenance": catalog, "linked_at": datetime.now(timezone.utc).isoformat()} if catalog else {}),
        "source_sha256": fingerprint,
        "field_confidence": public_record.get("field_confidence", {}),
        "evidence_role": "context_only",
        "excluded_from_detector_scoring": True,
        "source_endpoint": MCP_ENDPOINT,
        "attribution_status": "verify_source_license_before_republishing",
    }
