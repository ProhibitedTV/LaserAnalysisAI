"""Full public-catalog probe checks remain offline and omit record content."""
from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest.mock import patch

from laserlab.veilbreak_bridge import VeilbreakError, check_public_compatibility
from scripts.check_veilbreak import main


class ProbeClient:
    def __init__(self, overrides=None, *, empty=False):
        self.overrides = overrides or {}
        self.empty = empty
        self.calls = []

    def _initialize(self):
        return "PRIVATE SESSION"

    def _rpc(self, method, params, request_id, session):
        self.calls.append((method, params, request_id))
        if method == "tools/list":
            tools = []
            for name in ("get_protocols", "get_protocol_by_id", "get_experiments", "get_experiment_by_id", "get_schema"):
                schema = {"type": "object", "properties": {}, "required": []}
                if name.endswith("_by_id"):
                    schema.update(properties={"id": {"type": "integer"}}, required=["id"])
                tools.append({"name": name, "inputSchema": schema})
            return {"tools": tools}, session
        name, arguments = params["name"], params["arguments"]
        missing = arguments.get("id") == 9007199254740991
        key = "missing_" + name if missing else name
        if key in self.overrides:
            return self.overrides[key], session
        if name == "get_schema":
            return {"structuredContent": {"fields": {"protocol": {field: {"description": unit} for field, unit in
                    (("laser_wavelength", "nanometers"), ("laser_power", "milliwatts"), ("projection_distance", "feet"))}}}}, session
        if missing:
            return {"isError": True, "content": [{"type": "text", "text": "PRIVATE missing-record response"}]}, session
        identifier = 21 if "protocol" in name else 32
        row = {"id": identifier, "title": "PRIVATE TITLE", "author": "PRIVATE AUTHOR",
               "meta": {"laser_wavelength": 650, "projection_distance": 5},
               "questionnaire": {"participant": "PRIVATE PARTICIPANT"}}
        value = row if name.endswith("_by_id") else ([] if self.empty else [row])
        return {"structuredContent": value}, session


class FullCatalogProbeTests(unittest.TestCase):
    def test_both_catalogs_and_lookups_are_checked_with_unique_request_ids_without_content(self):
        client = ProbeClient()
        summary = check_public_compatibility(client=client)
        self.assertEqual(summary["catalogs_checked"], ["protocols", "experiments"])
        for kind in ("protocol", "experiment"):
            self.assertEqual(summary[f"{kind}_records"], 1)
            self.assertTrue(summary[f"{kind}_by_id_checked"])
            self.assertTrue(summary[f"missing_{kind}_reported_as_error"])
        self.assertEqual(summary["experiment_optical_field_counts"]["projection_distance_meters"], 1)
        self.assertNotIn("PRIVATE", json.dumps(summary))
        ids = [call[2] for call in client.calls]
        self.assertEqual(len(ids), len(set(ids)))
        calls = [call[1] for call in client.calls if call[0] == "tools/call"]
        self.assertEqual([call["name"] for call in calls], ["get_schema", "get_protocols", "get_protocol_by_id",
                         "get_protocol_by_id", "get_experiments", "get_experiment_by_id", "get_experiment_by_id"])
        self.assertEqual(calls[5]["arguments"], {"id": 32})

    def test_experiment_errors_partial_catalogs_and_bad_shapes_cannot_pass_protocol_only(self):
        for response in ({"isError": True, "content": [{"type": "text", "text": "PRIVATE ERROR"}]},
                         {"structuredContent": {"data": [{"id": 32}], "pagination": {"has_more": True}}},
                         {"structuredContent": {"unexpected": "PRIVATE CONTENT"}}):
            with self.subTest(response=response):
                client = ProbeClient({"get_experiments": response})
                with self.assertRaises(VeilbreakError) as error:
                    check_public_compatibility(client=client)
                self.assertNotIn("PRIVATE", str(error.exception))
                self.assertTrue(any(call[1].get("name") == "get_protocol_by_id" for call in client.calls))

    def test_experiment_lookup_rejects_mismatched_missing_and_multiple_records(self):
        for value in ({"id": 999}, [], [{"id": 32}, {"id": 33}]):
            with self.subTest(value=value), self.assertRaisesRegex(VeilbreakError, "experiment-ID lookup"):
                check_public_compatibility(client=ProbeClient({"get_experiment_by_id": {"structuredContent": value}}))

    def test_missing_experiment_behavior_is_required_and_cli_failure_stays_sanitized(self):
        client = ProbeClient({"missing_get_experiment_by_id": {"structuredContent": {"id": 32, "title": "PRIVATE TITLE"}}})
        output = io.StringIO()
        with patch("scripts.check_veilbreak.check_public_compatibility", side_effect=lambda: check_public_compatibility(client=client)), \
             contextlib.redirect_stdout(output):
            status = main(["--live"])
        self.assertEqual(status, 1)
        result = json.loads(output.getvalue())
        self.assertFalse(result["compatible"])
        self.assertIn("missing-experiment", result["error"])
        self.assertNotIn("PRIVATE", output.getvalue())

    def test_empty_catalogs_do_not_invent_exact_id_checks(self):
        client = ProbeClient(empty=True)
        summary = check_public_compatibility(client=client)
        for kind in ("protocol", "experiment"):
            self.assertEqual(summary[f"{kind}_records"], 0)
            self.assertFalse(summary[f"{kind}_by_id_checked"])
            self.assertTrue(summary[f"missing_{kind}_reported_as_error"])
        id_calls = [call[1]["arguments"] for call in client.calls if call[1].get("name", "").endswith("_by_id")]
        self.assertEqual(id_calls, [{"id": 9007199254740991}, {"id": 9007199254740991}])


if __name__ == "__main__":
    unittest.main()
