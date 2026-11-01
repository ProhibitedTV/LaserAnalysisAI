"""Offline privacy, scientific-boundary and reviewed-snapshot export tests."""
from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from laserlab import __version__, app_api
from laserlab.artifacts import write_json, directory_fingerprint
from laserlab.cli import main
from laserlab.manifest import new_manifest, write_manifest
from laserlab.research_exchange import prepare_exchange, export_exchange, EXCHANGE_VERSION
from laserlab.stats import evidence_ladder, summarize_results

try:
    from test_replication import synthetic_run
    from test_capture_inference import pairs
except ModuleNotFoundError:
    from tests.test_replication import synthetic_run
    from tests.test_capture_inference import pairs


class ExchangeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.experiment = self.root / "PRIVATE-experiment"
        self.output = self.root / "exchange.json"
        self.run = synthetic_run(1)
        self.run.update(subjective_reports=[{"story": "PRIVATE story"}], review_annotations={"name": "PRIVATE reviewer"},
                        review_session={"complete": True}, laserlab_version="0.8.2")
        self.run["analysis_configuration"]["ocr_engines"] = [["PRIVATE engine path", "PRIVATE key", True]]
        for result in self.run["results"]:
            result.update(ocr={"text": "PRIVATE OCR"}, source_path="PRIVATE source path", timestamp_ms=12345,
                          extraction_settings={"mode": "interval", "frame_interval": 5, "max_frames": 10,
                                               "deduplicate": True, "PRIVATE_extra": "PRIVATE sampling"})
        self.manifest = new_manifest()
        self.manifest["outputs"] = {"latest_run": "runs/selected", "review_state": "unblinded"}
        self.manifest["external_dataset_references"] = [{"source": "veilbreak", "record_type": "protocol", "record_id": 7,
                                                         "title": "PRIVATE title", "author": "PRIVATE author",
                                                         "optical_metadata": {"wavelength_nm": 999}}]
        self.save()

    def save(self):
        write_manifest(self.experiment, self.manifest)
        write_json(self.experiment / "runs/selected/results.json", self.run)

    def export(self, preview=None, **options):
        preview = preview or prepare_exchange(self.experiment, **options)
        return export_exchange(self.experiment, self.output, expected_snapshot=preview["_snapshot_sha256"],
                               privacy_acknowledged=True, **options)

    def test_default_document_is_allow_listed_and_source_artifacts_are_preserved(self):
        files = list(self.experiment.rglob("*.json"))
        before = directory_fingerprint(files)
        with patch("laserlab.veilbreak_bridge.build_opener", side_effect=AssertionError("no network")):
            preview = prepare_exchange(self.experiment)
            self.export(preview)
        document = json.loads(self.output.read_text())
        self.assertEqual(document, preview["document"])
        self.assertEqual(document["schema_version"], EXCHANGE_VERSION)
        self.assertEqual(document["exporter"]["version"], __version__)
        self.assertEqual(document["community_references"], [])
        encoded = self.output.read_text()
        for value in ("PRIVATE", "timestamp_ms", "review_token", "_snapshot", "_reference_choices", "ocr_engines"):
            self.assertNotIn(value, encoded)
        for record in self.run["results"]:
            self.assertNotIn(record["capture_source_sha256"], encoded)
        self.assertEqual(document["captures"][0]["reported_setup"]["camera_details"], "recorded_but_omitted")
        self.assertEqual(document["captures"][0]["sampling"]["frame_interval"], 5)
        self.assertIsNone(document["findings"]["candidate_fdr"])
        self.assertEqual(before, directory_fingerprint(files))

    def test_hashes_and_one_linked_reference_require_explicit_selection(self):
        reference = {"source": "veilbreak", "record_type": "protocol", "record_id": 7}
        preview = prepare_exchange(self.experiment, include_source_hashes=True, reference=reference)
        self.export(preview, include_source_hashes=True, reference=reference)
        document = json.loads(self.output.read_text())
        self.assertEqual(document["community_references"], [reference])
        self.assertEqual(document["captures"][0]["recorded_source_hashes"]["capture_sha256"], self.run["results"][0]["capture_source_sha256"])
        self.assertIn("can link recordings", " ".join(document["limitations"]))
        self.assertNotIn("PRIVATE", self.output.read_text())
        self.assertNotIn("999", json.dumps(document["community_references"]))
        for bad in ({**reference, "record_id": 99}, {**reference, "record_id": True}, {**reference, "title": "extra"}):
            with self.assertRaisesRegex(ValueError, "already linked"):
                prepare_exchange(self.experiment, reference=bad)

    def test_acknowledgement_and_exact_review_token_are_required_before_any_write(self):
        preview = prepare_exchange(self.experiment)
        with self.assertRaisesRegex(ValueError, "acknowledge"):
            export_exchange(self.experiment, self.output, expected_snapshot=preview["_snapshot_sha256"])
        with self.assertRaisesRegex(ValueError, "preview before saving"):
            export_exchange(self.experiment, self.output, expected_snapshot="", privacy_acknowledged=True)
        with self.assertRaisesRegex(ValueError, "options changed"):
            self.export(preview, include_source_hashes=True)
        self.assertFalse(self.output.exists())

    def test_source_or_manifest_change_invalidates_the_review(self):
        for source in ("manifest", "run"):
            with self.subTest(source=source):
                preview = prepare_exchange(self.experiment)
                target = self.manifest if source == "manifest" else self.run
                target["PRIVATE_new_note"] = "changed after review"
                self.save()
                with self.assertRaisesRegex(ValueError, "fresh preview"):
                    self.export(preview)
                self.assertFalse(self.output.exists())

    def test_existing_destination_is_preserved(self):
        self.output.write_text("unrelated existing work")
        with self.assertRaises(FileExistsError):
            self.export()
        self.assertEqual(self.output.read_text(), "unrelated existing work")

    def test_sealed_manifest_is_rejected_before_results_are_read(self):
        self.manifest["outputs"]["review_state"] = "blinded"
        write_manifest(self.experiment, self.manifest)
        (self.experiment / "runs/selected/results.json").unlink()
        with self.assertRaisesRegex(ValueError, "Explicitly unblind"):
            prepare_exchange(self.experiment)

    def test_missing_or_false_run_unblind_state_is_rejected(self):
        for state in ({}, {"unblinded": False}):
            self.run["review_state"] = state
            self.save()
            with self.assertRaisesRegex(ValueError, "explicit unblinded"):
                prepare_exchange(self.experiment)

    def test_outside_run_path_is_rejected_and_no_raw_media_or_map_is_opened(self):
        original_read = Path.read_bytes
        def read_only_artifacts(path):
            self.assertIn(path.name, {"manifest.json", "results.json"})
            return original_read(path)
        with patch.object(Path, "read_bytes", read_only_artifacts):
            prepare_exchange(self.experiment)
        self.manifest["outputs"]["latest_run"] = "../outside"
        write_manifest(self.experiment, self.manifest)
        with self.assertRaisesRegex(ValueError, "within the selected"):
            prepare_exchange(self.experiment)

    def test_tested_insufficient_and_untested_results_keep_distinct_meanings(self):
        scenarios = [(pairs(), "above-control candidate"), (pairs(null=True), "no signal"),
                     (pairs(1), "insufficient independent samples"), ([], "not tested")]
        for records, expected in scenarios:
            self.run["results"] = records
            self.run["aggregate_statistics"] = summarize_results(records, 31)
            self.save()
            findings = prepare_exchange(self.experiment)["document"]["findings"]
            self.assertEqual(findings["evidence_level"], expected)
            if expected in {"not tested", "insufficient independent samples"}:
                self.assertIsNone(findings["permutation_p_value"])
            self.assertIsNone(findings["candidate_fdr"])
        self.run = synthetic_run(1)
        self.run["pre_run_quality"] = {"status": "mismatch", "requires_exploratory": True}
        self.save()
        document = prepare_exchange(self.experiment)["document"]
        self.assertEqual(document["findings"]["evidence_level"], "not tested")
        self.assertIsNone(document["findings"]["permutation_p_value"])
        self.assertTrue(document["quality"]["exploratory"])

    def test_legacy_views_and_unknown_analysis_version_do_not_rewrite_originals(self):
        self.run.pop("laserlab_version")
        self.run["aggregate_statistics"].pop("statistics_version")
        self.save()
        path = self.experiment / "runs/selected/results.json"
        before = path.read_bytes()
        document = prepare_exchange(self.experiment)["document"]
        self.assertIsNone(document["analysis_software_version"])
        self.assertEqual(document["experiment_purpose"], "unspecified")
        self.assertEqual(document["method"]["statistics_version"], "paired-capture-v2")
        self.assertEqual(before, path.read_bytes())
        self.run["results"][0]["capture_metadata"]["camera"] = "unknown"
        self.save()
        self.assertEqual(prepare_exchange(self.experiment)["document"]["captures"][0]["reported_setup"]["camera_details"], "unknown")

    def test_nonfinite_numbers_and_free_text_configuration_do_not_enter_json(self):
        self.run["results"][0]["capture_metadata"].update(wavelength_nm=float("nan"), focus_mode="PRIVATE focus")
        self.run["analysis_configuration"].update(detectors=["ocr", "PRIVATE detector"], roi={"x": float("inf"), "y": 0})
        self.save()
        document = prepare_exchange(self.experiment)["document"]
        encoded = json.dumps(document, allow_nan=False)
        self.assertNotIn("PRIVATE", encoded)
        self.assertIsNone(document["captures"][0]["reported_setup"]["wavelength_nm"])
        self.assertIsNone(document["method"]["roi"]["x"])
        self.assertEqual(document["method"]["detectors"], ["ocr"])

    def test_all_supported_control_generation_modes_are_retained(self):
        for mode in ("none", "standard", "strict"):
            self.run["analysis_configuration"]["control_generation"] = mode
            self.save()
            document = prepare_exchange(self.experiment)["document"]
            self.assertEqual(document["method"]["control_generation"], mode)

    def test_cli_preview_token_and_save_use_the_same_explicit_options(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["exchange", "preview", "--experiment", str(self.experiment)]), 0)
        preview = json.loads(output.getvalue())
        with redirect_stdout(io.StringIO()):
            status = main(["exchange", "export", "--experiment", str(self.experiment), "--output", str(self.output),
                           "--review-token", preview["review_token"], "--acknowledge-privacy"])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(self.output.read_text()), preview["document"])
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(["exchange", "preview", "--experiment", str(self.experiment), "--reference-id", "7"]), 2)

    def test_shared_threshold_constants_preserve_existing_boundary_behavior(self):
        for difference, p_value, expected in ((.02, .01, "no signal"), (.020001, .05, "above-control candidate"),
                                               (.05, .050001, "artifact"), (.050001, .050001, "anomaly")):
            self.assertEqual(evidence_ladder({"inference": {"status": "tested"}, "mean_difference": difference,
                                              "permutation_p_value": p_value}), expected)

    def test_real_bundled_demo_keeps_practice_marker_and_records_analysis_version(self):
        payload = app_api.run_bundled_demo(self.root / "practice", max_frames=1)
        experiment = Path(payload["experiment_dir"])
        app_api.complete_review(experiment)
        app_api.unblind_latest_run(experiment)
        document = app_api.prepare_research_exchange(experiment)["document"]
        self.assertEqual(document["analysis_software_version"], __version__)
        self.assertEqual(document["experiment_purpose"], "practice_demo")
        self.assertEqual(document["findings"]["evidence_level"], "not tested")
        self.assertIn("Practice demo", " ".join(document["limitations"]))


if __name__ == "__main__":
    unittest.main()
