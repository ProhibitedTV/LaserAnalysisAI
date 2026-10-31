"""Optional, read-only access to Veilbreak's published community research catalog.

The public MCP endpoint is fixed and never receives experiment paths, footage,
personal notes, session IDs, credentials, or detector results. Imported records
are reduced to allow-listed optical metadata; they remain context-only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .community_data import normalize_external_reference

MCP_ENDPOINT = "https://veilbreak.ai/api/mcp"
MCP_VERSION = "2025-03-26"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
TIMEOUT_SECONDS = 12
RECORD_LIMIT = 200

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
    text = raw.decode("utf-8-sig")
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
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
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
        init, session = self._rpc(
            "initialize",
            {"protocolVersion": MCP_VERSION, "capabilities": {},
             "clientInfo": {"name": "LaserLab", "version": "0.8"}},
            1,
        )
        if not init.get("protocolVersion"):
            raise VeilbreakError("Veilbreak did not complete the MCP initialization.")
        self._rpc("notifications/initialized", {}, 0, session, notification=True)
        result, _ = self._rpc("tools/call", {"name": tool, "arguments": args}, 2, session)
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
        return [row for row in payload if isinstance(row, Mapping)][:RECORD_LIMIT]
    if isinstance(payload, Mapping):
        for key in ("data", kind, "records", "items", "results"):
            if key in payload:
                return _records(payload[key], kind)
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
    source = {key: record[key] for key in (
        "laser_wavelength", "wavelength_nm", "laser_power", "rated_power_mw",
        "laser_class", "laser_class_label", "projection_distance",
        "projection_distance_meters", "equipment", "laser_pattern_type", "tags",
    ) if key in record}
    # Never save free-form descriptions, questionnaire answers, or perceived symbols.
    normalized = normalize_external_reference(source, record_index=identifier)
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
        "field_confidence": normalized.get("field_confidence", {}),
        "evidence_role": "context_only",
        "excluded_from_detector_scoring": True,
    }


def browse_public(kind: str, *, client: VeilbreakClient | None = None) -> list[dict[str, Any]]:
    """Read approved public catalog entries. No background polling or uploads."""
    if kind not in _TOOLS:
        raise ValueError("Record type must be protocols or experiments.")
    payload = (client or VeilbreakClient()).call(_TOOLS[kind][0])
    return [safe_public_record(record, kind) for record in _records(payload, kind)]


def read_public_record(kind: str, record_id: int, *,
                       client: VeilbreakClient | None = None) -> dict[str, Any]:
    """Get one published record by numeric ID, reducing it to safe metadata."""
    if kind not in _TOOLS:
        raise ValueError("Record type must be protocols or experiments.")
    if type(record_id) is not int or record_id < 1:
        raise ValueError("Record ID must be a positive integer.")
    payload = (client or VeilbreakClient()).call(_TOOLS[kind][1], {"id": record_id})
    entries = _records(payload, kind)
    if not entries or int(entries[0].get("id", 0)) != record_id:
        raise VeilbreakError("Veilbreak returned no matching published record.")
    return safe_public_record(entries[0], kind)


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
    return {
        "source": "veilbreak",
        "record_type": record_type,
        "record_id": record_id,
        "title": str(public_record.get("title") or "")[:160],
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "optical_metadata": {key: allowed.get(key) for key in safe_keys},
        "evidence_role": "context_only",
        "excluded_from_detector_scoring": True,
        "source_endpoint": MCP_ENDPOINT,
        "attribution_status": "verify_source_license_before_republishing",
    }
