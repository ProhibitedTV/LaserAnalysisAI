"""Known-truth probes, hash replay, optional-engine and evidence boundaries."""
from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from laserlab import app_api
from laserlab.artifacts import load_json, write_json, sha256_file
from laserlab.optical_benchmark import (benchmark_catalog, generate_benchmark_pack, evaluate_benchmark_pack,
                                      confusion_counts, pixel_sha256)

ROOT = Path(__file__).resolve().parents[1]


class OpticalBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.pack = cls.root / "pack"
        cls.manifest = generate_benchmark_pack(cls.pack)
        cls.report = evaluate_benchmark_pack(cls.pack)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_pack_is_small_typed_licensed_and_reproducible(self):
        other = self.root / "again"
        second = generate_benchmark_pack(other)
        self.assertEqual(second, self.manifest)
        self.assertEqual(len(second["cases"]), 10)
        self.assertEqual(sum(path.stat().st_size for path in self.pack.rglob("*.*")) < 5_000_000, True)
        for case in second["cases"]:
            self.assertEqual(case["fixture_type"], "synthetic")
            self.assertEqual(case["license"], "MIT")
            self.assertEqual(case["frame_count"], 3)
            for frames in [case["raw_frames"], *case["processed_frames"].values()]:
                self.assertEqual(len(frames), 3)
                self.assertTrue(all(len(frame["sha256"]) == 64 and len(frame["pixel_sha256"]) == 64 for frame in frames))
        with self.assertRaises(FileExistsError):
            generate_benchmark_pack(other)

    def test_public_reference_raw_pixels_and_recipe_match(self):
        reference = load_json(ROOT / "sample_media" / "optical_benchmark_reference.json")
        self.assertEqual(reference["spec_sha256"], self.manifest["spec_sha256"])
        for expected, actual in zip(reference["cases"], self.manifest["cases"]):
            self.assertEqual(expected["id"], actual["id"])
            self.assertEqual([f["pixel_sha256"] for f in expected["raw_frames"]], [f["pixel_sha256"] for f in actual["raw_frames"]])

    def test_golden_false_positives_and_known_positive_calibration(self):
        golden = load_json(ROOT / "tests" / "golden" / "optical_benchmark.json")
        for variant, tasks in golden["by_variant"].items():
            for task, expected in tasks.items():
                actual = self.report["by_variant"][variant][task]
                self.assertEqual({key: actual[key] for key in expected}, expected, (variant, task))
        original = {r["case_id"]: r for r in self.report["records"] if r["variant"] == "original"}
        self.assertTrue(original["sensor_noise"]["predictions"]["text_like_components"])
        self.assertFalse(original["sensor_noise"]["ground_truth"]["text_like_components"])
        self.assertTrue(original["dark_text"]["predictions"]["text_like_components"])
        self.assertFalse(original["known_text"]["predictions"]["text_like_components"])
        self.assertTrue(original["known_text"]["ground_truth"]["text_like_components"])

    def test_ocr_disabled_is_untested_not_a_clean_negative(self):
        result = self.report["summary"]["ocr_text_presence"]
        self.assertEqual(result["evaluated"], 0)
        self.assertEqual(result["not_evaluated"], 40)
        self.assertIsNone(result["false_positive_rate"])
        self.assertIsNone(result["false_negative_rate"])

    def test_unknown_truth_and_missing_predictions_are_excluded(self):
        observations = [{"ground_truth": {"t": truth}, "predictions": {"t": value}} for truth, value in
                        ((None, True), (True, None), (False, None), (True, True), (False, True), (True, False), (False, False))]
        counts = confusion_counts(observations, "t")
        self.assertEqual(counts["unknown_ground_truth"], 1)
        self.assertEqual(counts["not_evaluated"], 2)
        self.assertEqual(counts["evaluated"], 4)
        self.assertEqual(counts["false_positive_rate"], .5)
        self.assertEqual(counts["false_negative_rate"], .5)
        self.assertEqual(self.report["summary"]["pixel_clipping"]["unknown_ground_truth"], 30)

    def test_optional_ocr_failures_and_false_words_are_not_hidden(self):
        class SimulatedOcr:
            engine_id = "simulated-output-accounting-test"
            def __init__(self, text, available=True, failure_reason=None):
                self.text, self.available, self.failure = text, available, failure_reason
            def run(self, request):
                return {"text": self.text, "available": self.available, "failure_reason": self.failure,
                        "engine_id": self.engine_id, "engine_version": "test"}
        for engine in (SimulatedOcr("word", False), SimulatedOcr(None), SimulatedOcr("", True, "timeout")):
            report = evaluate_benchmark_pack(self.pack, ocr_adapter=engine)
            self.assertEqual(report["summary"]["ocr_text_presence"]["not_evaluated"], 40)
        false_words = evaluate_benchmark_pack(self.pack, ocr_adapter=SimulatedOcr("DECODED"))
        self.assertEqual(false_words["summary"]["ocr_text_presence"]["false_positive"], 28)
        self.assertTrue(all(r["known_text_exact_match"] is False for r in false_words["records"] if r["ground_truth"]["ocr_text_presence"]))
        self.assertEqual(false_words["independent_experiment_count"], 0)
        self.assertNotIn("evidence_ladder", false_words)

    def _changed_manifest(self, change):
        path = self.pack / "benchmark_manifest.json"
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        manifest = copy.deepcopy(self.manifest)
        change(manifest)
        write_json(path, manifest)

    def test_modified_ground_truth_and_duplicate_cases_are_rejected(self):
        for change in (lambda m: m["cases"][0]["ground_truth"].update(ocr_text_presence=True),
                       lambda m: m["cases"].append(m["cases"][0])):
            self._changed_manifest(change)
            with self.assertRaises(ValueError):
                evaluate_benchmark_pack(self.pack)
        write_json(self.pack / "benchmark_manifest.json", self.manifest)

    def test_outside_paths_are_rejected_before_decode(self):
        self._changed_manifest(lambda m: m["cases"][0]["raw_frames"][0].update(path="../private.png"))
        with patch("cv2.imread", side_effect=AssertionError("must reject before decoding")):
            with self.assertRaises(ValueError):
                evaluate_benchmark_pack(self.pack)

    def test_replacement_bytes_and_self_asserted_hashes_cannot_change_recipe(self):
        frame = self.manifest["cases"][0]["raw_frames"][0]
        path = self.pack / frame["path"]
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(b"wrong file")
        with self.assertRaises(ValueError):
            evaluate_benchmark_pack(self.pack)
        image = np.full((160, 256, 3), 55, np.uint8)
        cv2.imwrite(str(path), image)
        self._changed_manifest(lambda m: m["cases"][0]["raw_frames"][0].update(sha256=sha256_file(path), pixel_sha256=pixel_sha256(image)))
        with self.assertRaisesRegex(ValueError, "raw content"):
            evaluate_benchmark_pack(self.pack)

    def test_processed_chain_is_verified_beyond_hashes(self):
        frame = self.manifest["cases"][0]["processed_frames"]["blur"][0]
        path = self.pack / frame["path"]
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        image = np.full((160, 256, 3), 70, np.uint8)
        cv2.imwrite(str(path), image)
        self._changed_manifest(lambda m: m["cases"][0]["processed_frames"]["blur"][0].update(sha256=sha256_file(path), pixel_sha256=pixel_sha256(image)))
        with self.assertRaisesRegex(ValueError, "processed content"):
            evaluate_benchmark_pack(self.pack)

    def test_repeated_artifact_is_persistent_but_not_independent_evidence(self):
        record = next(r for r in self.report["records"] if r["case_id"] == "compression_blocks" and r["variant"] == "original")
        self.assertEqual(record["metrics"]["frame_persistence"], 1)
        self.assertTrue(all(record["persistence_sensitivity"].values()))
        self.assertFalse(record["ground_truth"]["ocr_text_presence"])
        self.assertEqual(self.report["empirical_capture_count"], 0)

    def test_fixture_pipeline_keeps_false_ocr_and_repetition_exploratory(self):
        from laserlab.ocr_adapters import BaseOCRAdapter, OCRPayload
        class FalseWordEngine(BaseOCRAdapter):
            engine_id = "adversarial-false-word-test"
            def recognize(self, request):
                return OCRPayload(text="DECODED", confidence=.95)
        with tempfile.TemporaryDirectory() as temporary:
            experiment = Path(temporary) / "experiment"
            metadata = {"fixture_type": "synthetic", "fixture_id": "optical-probes-compression", "footage_class": "regression_fixture"}
            app_api.add_capture(experiment, self.pack / "compression_blocks" / "raw", "image-set", "laser",
                                all_frames=True, deduplicate=False, capture_metadata=metadata)
            # Deliberately wrong OCR is an adversarial plumbing test, not an engine benchmark result.
            with patch("laserlab.detectors._TESSERACT_ADAPTER", FalseWordEngine()):
                run = app_api.run_analysis(experiment, profile="baseline", control_generation="none")
            self.assertFalse(run["review_state"]["unblinded"])
            bundle = app_api.export_review_bundle(experiment, Path(temporary) / "sealed.zip")
            with zipfile.ZipFile(bundle) as archive:
                self.assertNotIn(b"optical-probes-compression", archive.read("report.json"))
            app_api.complete_review(experiment)
            report = app_api.unblind_latest_run(experiment)
            self.assertEqual(report["aggregate_statistics"]["evidence_ladder"], "not tested")
            self.assertIsNone(report["aggregate_statistics"]["permutation_p_value"])
            self.assertTrue(any("DECODED" in str(r.get("ocr_text")) for r in report["top_candidates"]))
            self.assertTrue(all(r["source_class"] == "synthetic_fixture" for r in report["top_candidates"]))

    def test_cli_preserves_reports_and_existing_fixture_fetch(self):
        from laserlab.cli import main
        with tempfile.TemporaryDirectory() as temporary, patch("laserlab.cli.configure_logging"), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            report = Path(temporary) / "report.json"
            self.assertEqual(main(["benchmark", "run", "--pack", str(self.pack), "--output", str(report)]), 0)
            before = report.read_bytes()
            with self.assertLogs("laserlab.cli", level="ERROR"):
                self.assertEqual(main(["benchmark", "run", "--pack", str(self.pack), "--output", str(report)]), 2)
            self.assertEqual(report.read_bytes(), before)
            with patch("laserlab.cli.fetch_fixtures", return_value=[]) as fetch:
                self.assertEqual(main(["fixtures", "fetch", "--output", temporary]), 0)
                fetch.assert_called_once()

    def test_offline_bundled_demo_remains_usable(self):
        from laserlab.demo_smoke import smoke_bundled_demo
        with patch("urllib.request.urlopen", side_effect=AssertionError("demo must be offline")):
            smoke_bundled_demo()


if __name__ == "__main__":
    unittest.main()
