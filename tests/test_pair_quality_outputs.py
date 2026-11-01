"""Pair-quality checks survive the real sealed-review and export boundaries."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from laserlab import app_api
from laserlab.artifacts import load_json, sha256_file, write_json
from laserlab.manifest import latest_run_dir, load_manifest
from laserlab.pipeline import run_experiment, unblind_latest_run
from laserlab.stats import current_statistics, summarize_results
from laserlab.synthetic import create_synthetic_negative, create_synthetic_positive

try:
    from test_capture_inference import pairs
except ModuleNotFoundError:  # Also support direct module execution from the repo root.
    from tests.test_capture_inference import pairs


def varied_positive_pairs():
    records = pairs()
    for index, record in enumerate(records):
        if record["unblinded_label"] == "laser":
            for key in ("structure_score", "primary_metric_score", "inference_metric_score"):
                record[key] -= index * .005
    return records


class PairQualityInferenceBoundaryTests(unittest.TestCase):
    def test_quality_failure_withholds_an_otherwise_positive_five_pair_result(self):
        records = varied_positive_pairs()
        baseline = summarize_results(records, seed=31)
        self.assertEqual(baseline["evidence_ladder"], "above-control candidate")
        self.assertEqual(baseline["permutation_p_value"], 1 / 32)
        self.assertIsNotNone(baseline["cohen_d"])
        for status in ("mismatch", "unknown"):
            with self.subTest(status=status):
                gate = {"version": "pair-quality-v1", "status": status,
                        "requires_exploratory": True,
                        "summary": "The proposed control has unresolved comparison details."}
                gated = summarize_results(records, seed=31, quality_gate=gate)
                self.assertEqual(gated["evidence_ladder"], "not tested")
                self.assertNotEqual(gated["inference"]["status"], "tested")
                self.assertIsNone(gated["permutation_p_value"])
                self.assertIsNone(gated["cohen_d"])
                self.assertIsNone(gated["minimum_q_value"])
                self.assertFalse(gated["control_diagnostics"]["declared_matched_control"]["used_for_inference"])
                self.assertNotEqual(gated["laser_confidence_interval"]["unit"], "empirical capture")
                # Scores remain useful descriptively; the gate changes inference, not detectors.
                self.assertIsNotNone(gated["laser_mean_score"])
                self.assertIsNotNone(gated["control_mean_score"])

    def test_same_statistics_version_cannot_bypass_a_saved_quality_gate(self):
        records = varied_positive_pairs()
        aggregate = summarize_results(records, seed=31)
        run = {"blind_seed": 31, "review_state": {"unblinded": True}, "results": records,
               "aggregate_statistics": aggregate,
               "pre_run_quality": {"version": "pair-quality-v1", "status": "mismatch",
                                   "requires_exploratory": True,
                                   "summary": "The camera settings differ."}}
        original = copy.deepcopy(run)
        updated = current_statistics(run)
        self.assertEqual(updated["aggregate_statistics"]["evidence_ladder"], "not tested")
        self.assertIsNone(updated["aggregate_statistics"]["permutation_p_value"])
        self.assertIsNone(updated["aggregate_statistics"]["cohen_d"])
        self.assertEqual(run, original)


class PairQualityOutputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.experiment = self.root / "experiment"
        laser = self.root / "laser"
        control = self.root / "control"
        # These generated images test the declared-recording plumbing. They are
        # not empirical captures or a benchmark of actual optical comparability.
        create_synthetic_positive(laser / "sample.png", size=(160, 96))
        create_synthetic_negative(control / "sample.png", size=(80, 64))
        metadata = {"independent_pair_id": "private-quality-pair-marker",
                    "pair_exchangeability_acknowledged": True,
                    "camera": "private camera description", "exposure": "manual 1/60",
                    "focus_mode": "manual", "compression_history": "original camera file",
                    "camera_fixed": True, "beam_path_fixed": True,
                    "projected_region_not_saturated": True}
        for source, role in ((laser, "laser"), (control, "matched_control")):
            app_api.add_capture(self.experiment, source, "image-set", role,
                                capture_metadata=metadata)

    def _run(self):
        record = run_experiment(self.experiment, blind_seed=37, control_generation="none")
        run_dir = latest_run_dir(self.experiment, load_manifest(self.experiment))
        return record, run_dir

    def test_read_only_assessment_is_recomputed_then_sealed_until_explicit_unblind(self):
        paths = [self.experiment / "manifest.json", *self.experiment.glob("frames/*/*")]
        before = {path: sha256_file(path) for path in paths}
        assessment = app_api.assess_pair_quality(self.experiment)
        self.assertEqual(assessment["status"], "mismatch")
        self.assertTrue(assessment["requires_exploratory"])
        self.assertEqual({path: sha256_file(path) for path in paths}, before)
        self.assertNotIn("private camera description", json.dumps(assessment))
        self.assertNotIn(str(self.root), json.dumps(assessment))

        # Altering a returned preflight object cannot suppress the pipeline's own check.
        assessment["requires_exploratory"] = False
        record, run_dir = self._run()
        payload = load_json(run_dir / ".laserlab_unblind.json")
        saved = payload["pre_run_quality"]
        self.assertEqual(saved["status"], "mismatch")
        self.assertTrue(saved["requires_exploratory"])
        with self.assertRaises(ValueError):
            app_api.assess_pair_quality(self.experiment)
        for name in ("results.json", "report.json", "report.html"):
            content = (run_dir / name).read_text(encoding="utf-8")
            self.assertNotIn("private-quality-pair-marker", content)
            self.assertNotIn("requires_exploratory", content)
            self.assertNotIn("private camera description", content)
        self.assertEqual(record.get("pre_run_quality", {"sealed": True}), {"sealed": True})
        manifest = load_manifest(self.experiment)
        self.assertEqual(manifest.get("pre_run_quality", {"sealed": True}), {"sealed": True})
        bundle = app_api.export_review_bundle(self.experiment, self.root / "sealed.zip")
        with zipfile.ZipFile(bundle) as archive:
            for name in ("manifest.json", "results.json", "report.json", "report.html"):
                content = archive.read(name)
                self.assertNotIn(b"private-quality-pair-marker", content)
                self.assertNotIn(b"requires_exploratory", content)
                self.assertNotIn(b"private camera description", content)

        revealed = unblind_latest_run(self.experiment)
        self.assertEqual(revealed["pre_run_quality"], saved)
        self.assertNotIn(revealed["aggregate_statistics"]["evidence_ladder"],
                         ("above-control candidate", "repeatable candidate"))
        self.assertNotEqual(revealed["aggregate_statistics"]["inference"]["status"], "tested")
        self.assertIsNone(revealed["aggregate_statistics"]["permutation_p_value"])
        report = app_api.load_latest_report(self.experiment)
        self.assertEqual(report["pair_quality_report_version"], 1)
        self.assertEqual(report["pre_run_quality"], saved)
        self.assertIn("Pair Quality", (run_dir / "report.html").read_text(encoding="utf-8"))
        bundle = app_api.export_review_bundle(self.experiment, self.root / "revealed.zip")
        with zipfile.ZipFile(bundle) as archive:
            for name in ("results.json", "report.json"):
                content = json.loads(archive.read(name))
                self.assertEqual(content["pre_run_quality"], saved)
                self.assertIsNone(content["aggregate_statistics"]["permutation_p_value"])

    def test_same_statistics_legacy_view_adds_unassessed_notice_and_preserves_artifacts(self):
        _, run_dir = self._run()
        unblind_latest_run(self.experiment)
        results = load_json(run_dir / "results.json")
        results.pop("pre_run_quality", None)
        write_json(run_dir / "results.json", results)
        report = load_json(run_dir / "report.json")
        report.pop("pre_run_quality", None)
        report.pop("pair_quality_report_version", None)
        write_json(run_dir / "report.json", report)
        (run_dir / "report.html").write_text("Original report: preserve these bytes.", encoding="utf-8")
        paths = [run_dir / name for name in ("results.json", "report.json", "report.html")]
        before = {path: sha256_file(path) for path in paths}

        current = app_api.load_latest_report(self.experiment)
        self.assertEqual(current["pair_quality_report_version"], 1)
        self.assertTrue(current["local_paths"]["report_json"].endswith("report.pair-quality-v1.json"))
        html_path = Path(current["local_paths"]["report_html"])
        self.assertTrue(html_path.name.endswith("report.pair-quality-v1.html"))
        self.assertIn("not assessed", html_path.read_text(encoding="utf-8").casefold())
        self.assertNotEqual((current["pre_run_quality"] or {}).get("status"), "consistent")
        self.assertFalse((current["pre_run_quality"] or {}).get("pairs"))
        bundle = app_api.export_review_bundle(self.experiment, self.root / "legacy.zip")
        with zipfile.ZipFile(bundle) as archive:
            self.assertIn(b"not assessed", archive.read("report.html").lower())
        self.assertEqual({path: sha256_file(path) for path in paths}, before)


if __name__ == "__main__":
    unittest.main()
