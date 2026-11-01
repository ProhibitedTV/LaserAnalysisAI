"""Veilbreak public-catalog bridge tests. Never contact an external server."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from laserlab import app_api
from laserlab.manifest import load_manifest
from laserlab.veilbreak_bridge import (
    MCP_ENDPOINT,
    VeilbreakClient,
    VeilbreakError,
    _parse_rpc_response,
    browse_public,
    linked_record,
    read_public_record,
    safe_public_record,
    check_public_compatibility,
)


class MockCatalog:
    def __init__(self):
        self.calls = []

    def call(self, tool, arguments=None):
        self.calls.append((tool, arguments))
        if tool == "get_protocols":
            return {"data": [
                {"id": 19, "title": "Cross Beam", "laser_wavelength": 650,
                 "laser_power": 1, "laser_class": "Class 2",
                 "equipment": ["laser", "grating"], "tags": ["optics"],
                 "substance": "PRIVATE", "substance_dose": 123,
                 "author_email": "never-store@example.org",
                 "questionnaire": {"participant": "private"}},
                {"id": 20, "title": "Control test", "wavelength_nm": 532},
            ]}
        if tool == "get_experiment_by_id":
            return {"id": 42, "title": "Exp", "laser_wavelength": 532,
                    "observed_code": "DO NOT TREAT AS DETECTOR EVIDENCE"}
        raise AssertionError("Unexpected tool " + tool)


class BridgeTests(unittest.TestCase):
    def test_live_nested_schema_units_and_sensitive_fields(self):
        record = safe_public_record({
            "id": 1, "title": "Public protocol", "laser_class": "Class 2",
            "meta": {"laser_wavelength": 650, "laser_power": 0, "projection_distance": 5,
                     "substance_dose": "PRIVATE DOSE", "participant": "PRIVATE PERSON"},
            "author": {"email": "PRIVATE EMAIL"}, "equipment_details": "PRIVATE NOTES",
            "content": "PRIVATE CONTENT", "_links": {"private": "PRIVATE LINK"},
        }, "protocols")
        optical = record["optical_metadata"]
        self.assertEqual(optical["wavelength_nm"], 650)
        self.assertEqual(optical["rated_power_mw"], 0)
        self.assertAlmostEqual(optical["projection_distance_meters"], 1.524)
        self.assertEqual(record["field_confidence"]["projection_distance_meters"]["source_field"], "meta.projection_distance")
        self.assertNotIn("PRIVATE", json.dumps(record))
        with self.assertRaises(VeilbreakError) as error:
            safe_public_record({"id": 1, "meta": {"laser_wavelength": "PRIVATE MALFORMED VALUE"}}, "protocols")
        self.assertNotIn("PRIVATE", str(error.exception))

    def test_explicit_units_and_top_level_values_take_precedence(self):
        record = safe_public_record({"id": 1, "laser_wavelength": 532,
                                     "projection_distance_meters": 2,
                                     "meta": {"laser_wavelength": 650, "projection_distance": 10}}, "protocols")
        self.assertEqual(record["optical_metadata"]["wavelength_nm"], 532)
        self.assertEqual(record["optical_metadata"]["projection_distance_meters"], 2)
        flat = safe_public_record({"id": 2, "projection_distance": 1.5}, "protocols")
        self.assertAlmostEqual(flat["optical_metadata"]["projection_distance_meters"], 0.4572)

    def test_catalog_does_not_silently_drop_records_after_200(self):
        from unittest.mock import Mock
        fake = Mock()
        fake.call.return_value = [{"id": n, "title": "Repeated title"} for n in range(1, 254)]
        records = browse_public("protocols", client=fake)
        self.assertEqual(len(records), 253)
        self.assertEqual(records[-1]["record_id"], 253)
        fake.call.return_value = {"data": [{"id": 1}], "pagination": {"has_more": True, "total_pages": 3}}
        with self.assertRaisesRegex(VeilbreakError, "partial catalog"):
            browse_public("protocols", client=fake)
        fake.call.return_value = {"data": [{"id": 1}], "pagination": {"total": 4}}
        with self.assertRaisesRegex(VeilbreakError, "partial catalog"):
            browse_public("protocols", client=fake)
        fake.call.return_value = {"items": [{"id": 1}], "nextCursor": "more-records"}
        with self.assertRaisesRegex(VeilbreakError, "partial catalog"):
            browse_public("protocols", client=fake)

    def test_sse_crlf_comments_notifications_and_multiple_data_lines(self):
        raw = (b': keepalive\r\n\r\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\r\n\r\n'
               b'event: message\r\ndata: {"jsonrpc":"2.0","id":2,\r\ndata: "result":{"content":[]}}\r\n\r\n')
        self.assertEqual(_parse_rpc_response(raw, "text/event-stream", 2), {"content": []})
        with self.assertRaisesRegex(VeilbreakError, "UTF-8"):
            _parse_rpc_response(b'\xff', "application/json", 2)

    def test_unsupported_negotiated_version_stops_before_tool_calls(self):
        with patch.object(VeilbreakClient, "_rpc", return_value=({"protocolVersion": "2099-01-01"}, None)) as rpc:
            with self.assertRaisesRegex(VeilbreakError, "unsupported MCP"):
                VeilbreakClient().call("get_protocols")
        rpc.assert_called_once()

    def test_http_errors_are_actionable_and_do_not_echo_response_content(self):
        for status, expected in ((429, "rate limiting"), (403, "keyless"), (503, "HTTP error")):
            with self.subTest(status=status), patch("laserlab.veilbreak_bridge.build_opener") as opener:
                opener.return_value.open.side_effect = HTTPError(MCP_ENDPOINT, status, "PRIVATE SERVER CONTENT", {}, None)
                with self.assertRaises(VeilbreakError) as error:
                    VeilbreakClient().call("get_protocols")
                self.assertIn(expected, str(error.exception))
                self.assertNotIn("PRIVATE", str(error.exception))

    def test_compatibility_probe_reports_facts_without_persisting_record_contents(self):
        from unittest.mock import Mock
        fake = Mock()
        tools = [{"name": name, "inputSchema": {"type": "object", "required": ["id"],
                  "properties": {"id": {"type": "integer"}}}} for name in
                 ("get_protocols", "get_protocol_by_id", "get_experiments", "get_experiment_by_id", "get_schema")]
        def rpc(method, params, request_id, session):
            if method == "tools/list":
                return {"tools": tools}, None
            name = params["name"]
            if name == "get_schema":
                data = {"fields": {"protocol": {key: {"description": unit} for key, unit in
                        (("laser_wavelength", "nanometers"), ("laser_power", "milliwatts"), ("projection_distance", "feet"))}}}
            elif name == "get_protocols":
                data = [{"id": 1, "title": "PRIVATE PUBLIC TITLE", "meta": {"laser_wavelength": 650}}]
            elif params["arguments"]["id"] == 1:
                data = {"id": 1, "title": "PRIVATE PUBLIC TITLE"}
            else:
                return {"isError": True, "content": [{"type": "text", "text": "PRIVATE ERROR"}]}, None
            return {"structuredContent": data}, None
        fake._rpc.side_effect = rpc
        result = check_public_compatibility(client=fake)
        self.assertEqual(result["protocol_records"], 1)
        self.assertTrue(result["protocol_by_id_checked"])
        self.assertTrue(result["missing_protocol_reported_as_error"])
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertEqual([call.args[1].get("name") for call in fake._rpc.call_args_list],
                         [None, "get_schema", "get_protocols", "get_protocol_by_id", "get_protocol_by_id"])

    def test_compatibility_probe_rejects_missing_tools_or_changed_units(self):
        from unittest.mock import Mock
        fake = Mock()
        fake._rpc.return_value = ({"tools": []}, None)
        with self.assertRaisesRegex(VeilbreakError, "missing an expected"):
            check_public_compatibility(client=fake)
        tools = [{"name": name, "inputSchema": {"required": ["id"], "properties": {"id": {"type": "integer"}}}}
                 for name in ("get_protocols", "get_protocol_by_id", "get_experiments", "get_experiment_by_id", "get_schema")]
        fake._rpc.side_effect = [({"tools": tools}, None), ({"structuredContent": {"fields": {"protocol": {
            "laser_wavelength": {"description": "nanometers"}, "laser_power": {"description": "milliwatts"},
            "projection_distance": {"description": "meters"}}}}}, None)]
        with self.assertRaisesRegex(VeilbreakError, "optical units changed"):
            check_public_compatibility(client=fake)
        fake._rpc.side_effect = [({"tools": tools}, None), ({"structuredContent": {"fields": None}}, None)]
        with self.assertRaisesRegex(VeilbreakError, "optical units changed"):
            check_public_compatibility(client=fake)

    def test_maintainer_probe_requires_explicit_live_flag(self):
        import contextlib
        import io
        from scripts.check_veilbreak import main
        with patch("scripts.check_veilbreak.check_public_compatibility") as probe, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exit_status:
                main([])
        self.assertEqual(exit_status.exception.code, 2)
        probe.assert_not_called()

    def test_public_catalog_exposes_only_optical_metadata(self):
        fake = MockCatalog()
        records = browse_public("protocols", client=fake)
        self.assertEqual(fake.calls, [("get_protocols", None)])
        self.assertEqual([r["record_id"] for r in records], [19, 20])
        self.assertEqual(records[0]["optical_metadata"]["wavelength_nm"], 650)
        self.assertTrue(records[0]["excluded_from_detector_scoring"])
        encoded = json.dumps(records)
        for disallowed in ("PRIVATE", "substance_dose", "author_email",
                           "never-store@example.org", "questionnaire", "observed_code"):
            self.assertNotIn(disallowed, encoded)

    def test_exact_record_uses_read_only_tool(self):
        fake = MockCatalog()
        result = read_public_record("experiments", 42, client=fake)
        self.assertEqual(result["record_id"], 42)
        self.assertEqual(result["record_type"], "experiment")
        self.assertEqual(fake.calls, [("get_experiment_by_id", {"id": 42})])

    def test_invalid_kind_or_id_rejected_without_network(self):
        fake = MockCatalog()
        with self.assertRaises(ValueError):
            browse_public("private", client=fake)
        with self.assertRaises(ValueError):
            read_public_record("protocols", -1, client=fake)
        with self.assertRaises(VeilbreakError):
            safe_public_record({"id": "bad"}, "protocols")
        self.assertFalse(fake.calls)

    def test_mcp_json_and_sse_responses(self):
        result = {"jsonrpc": "2.0", "id": 2, "result": {"content": []}}
        raw = json.dumps(result).encode()
        self.assertEqual(_parse_rpc_response(raw, "application/json", 2), {"content": []})
        self.assertEqual(
            _parse_rpc_response(b"event: message\n" + b"data: " + raw + b"\n\n",
                                "text/event-stream", 2),
            {"content": []},
        )

    def test_client_never_sends_user_content_and_uses_fixed_endpoint(self):
        requests = []
        class FakeResponse:
            def __init__(self, payload, session="session-test"):
                self.payload = json.dumps(payload).encode()
                self.headers = {"Content-Type": "application/json",
                                "Mcp-Session-Id": session}
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False
            def geturl(self):
                return MCP_ENDPOINT
            def read(self, _count):
                return self.payload
        class FakeOpener:
            def open(self, request, timeout):
                self_assert = json.loads(request.data)
                requests.append((request.full_url, self_assert))
                if self_assert["method"] == "initialize":
                    return FakeResponse({"jsonrpc": "2.0", "id": 1,
                                         "result": {"protocolVersion": "2025-03-26"}})
                if self_assert["method"] == "notifications/initialized":
                    return FakeResponse({})
                return FakeResponse({
                    "jsonrpc": "2.0", "id": 2,
                    "result": {"content": [{"type": "text", "text":
                                           json.dumps([{"id": 1, "title": "Visible"}])}]}
                })
        with patch("laserlab.veilbreak_bridge.build_opener", return_value=FakeOpener()):
            payload = VeilbreakClient().call("get_protocols")
        self.assertEqual(payload[0]["id"], 1)
        self.assertEqual([req[1]["method"] for req in requests],
                         ["initialize", "notifications/initialized", "tools/call"])
        self.assertTrue(all(url == MCP_ENDPOINT for url, _ in requests))
        self.assertNotIn("experiment", json.dumps(requests).lower())

    def test_link_is_local_idempotent_and_not_part_of_detector_scores(self):
        sample = browse_public("protocols", client=MockCatalog())[0]
        with tempfile.TemporaryDirectory() as temp:
            experiment = Path(temp) / "lab"
            app_api.create_experiment(experiment)
            with patch("laserlab.veilbreak_bridge.build_opener",
                       side_effect=AssertionError("network must not be used")):
                app_api.link_veilbreak_reference(experiment, sample)
                app_api.link_veilbreak_reference(experiment, sample)
            manifest = load_manifest(experiment)
            references = manifest["external_dataset_references"]
            self.assertEqual(len(references), 1)
            self.assertEqual(references[0]["record_id"], 19)
            self.assertEqual(references[0]["source"], "veilbreak")
            self.assertTrue(references[0]["excluded_from_detector_scoring"])
            self.assertEqual(manifest["protocol"], "anomaly")
            self.assertEqual(manifest["captures"], [])

    def test_link_refuses_ongoing_blinded_review(self):
        sample = browse_public("protocols", client=MockCatalog())[0]
        with tempfile.TemporaryDirectory() as temp:
            experiment = Path(temp) / "lab"
            manifest = app_api.create_experiment(experiment)
            manifest["outputs"]["review_state"] = "blinded"
            from laserlab.manifest import write_manifest
            write_manifest(experiment, manifest)
            with self.assertRaisesRegex(ValueError, "unblind"):
                app_api.link_veilbreak_reference(experiment, sample)


if __name__ == "__main__":
    unittest.main()
