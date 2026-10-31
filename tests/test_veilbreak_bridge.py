"""Veilbreak public-catalog bridge tests. Never contact an external server."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
