"""Real pipeline/export and legacy migration checks for the inference boundary."""
from __future__ import annotations

import json
import csv
import os
import tempfile
import unittest
import zipfile
import io
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path

from laserlab import app_api
from laserlab.artifacts import load_json, write_json, sha256_file
from laserlab.manifest import load_manifest, latest_run_dir
from laserlab.pipeline import run_experiment, unblind_latest_run
from laserlab.synthetic import create_synthetic_negative, create_synthetic_positive


class ScientificOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.experiment = self.root / "experiment"
        # Software-generated test input exercises declared-recording plumbing;
        # it is not itself empirical research or a matched optical benchmark.
        laser = self.root / "laser"
        control = self.root / "control"
        create_synthetic_positive(laser / "sample.png")
        create_synthetic_negative(control / "sample.png")
        metadata = {"independent_pair_id": "private-pair-declaration", "pair_exchangeability_acknowledged": True}
        for source, role in ((laser, "laser"), (control, "matched_control")):
            app_api.add_capture(self.experiment, source, "image-set", role, capture_metadata=metadata)
        self.run = run_experiment(self.experiment, blind_seed=39)
        self.run_dir = latest_run_dir(self.experiment, load_manifest(self.experiment))

    def test_provenance_and_pair_counts_remain_sealed_then_use_capture_units(self):
        source_hashes = [source["sha256"] for source in json.loads((self.run_dir / ".laserlab_unblind.json").read_text())["manifest_sensitive"]["sources"]]
        for filename in ("results.json", "report.json", "report.html"):
            content = (self.run_dir / filename).read_text()
            self.assertNotIn("private-pair-declaration", content)
            for source_hash in source_hashes:
                self.assertNotIn(source_hash, content)
        report = app_api.load_latest_report(self.experiment)
        self.assertEqual(report["aggregate_statistics"]["inference"]["status"], "sealed")
        csv_path = app_api.export_candidates_csv(self.experiment, self.root / "blind.csv")
        self.assertNotIn("source_class", csv_path.read_text().splitlines()[0])
        blinded = app_api.export_review_bundle(self.experiment, self.root / "blind.zip")
        with zipfile.ZipFile(blinded) as archive:
            for name in ("manifest.json", "results.json", "report.json", "report.html"):
                self.assertNotIn(b"private-pair-declaration", archive.read(name))
        revealed = unblind_latest_run(self.experiment)
        stats = revealed["aggregate_statistics"]
        self.assertEqual(stats["inference"]["empirical_capture_counts"], {"laser": 1, "matched_control": 1})
        self.assertEqual(stats["inference"]["pair_count"], 1)
        self.assertEqual(stats["control_diagnostics"]["generated_null"]["frame_count"], 3)
        self.assertEqual(stats["evidence_ladder"], "insufficient independent samples")
        self.assertTrue(all(result["q_value"] is None for result in revealed["results"]))
        self.assertIn("generated_null", {item["source_class"] for item in revealed["results"]})
        report = app_api.load_latest_report(self.experiment)
        self.assertIn("not estimated", (self.run_dir / "report.html").read_text())
        self.assertIn("capture inference withheld", report["badges"])
        self.assertEqual({item["source_class"] for item in report["top_candidates"]},
                         {"generated_null", "empirical_laser", "declared_matched_control"})
        self.assertIn("Generated null probe", (self.run_dir / "report.html").read_text())
        self.assertIn("Empirical matched control (declared)", (self.run_dir / "report.html").read_text())
        csv_path = app_api.export_candidates_csv(self.experiment, self.root / "unblind.csv")
        with csv_path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual({row["source_class"] for row in rows},
                         {"generated_null", "empirical_laser", "declared_matched_control"})

    def test_legacy_gui_view_and_bundle_replace_claims_without_overwriting_source_artifacts(self):
        revealed = unblind_latest_run(self.experiment)
        revealed["aggregate_statistics"].pop("statistics_version")
        revealed["aggregate_statistics"].update(evidence_ladder="repeatable candidate", permutation_p_value=.0001)
        for result in revealed["results"]:
            result.pop("capture_source_sha256", None)
            result.pop("inference_metric_score", None)
            result["q_value"] = .0001
        write_json(self.run_dir / "results.json", revealed)
        write_json(self.run_dir / "report.json", {"aggregate_statistics": revealed["aggregate_statistics"]})
        (self.run_dir / "report.html").write_text("legacy result; retain unchanged")
        paths = [self.run_dir / name for name in ("results.json", "report.json", "report.html")]
        before = {path: sha256_file(path) for path in paths}
        report = app_api.load_latest_report(self.experiment)
        self.assertEqual(report["aggregate_statistics"]["evidence_ladder"], "not tested")
        self.assertTrue(report["local_paths"]["report_html"].endswith("report.statistics-v2.html"))
        bundle = app_api.export_review_bundle(self.experiment, self.root / "migrated.zip")
        with zipfile.ZipFile(bundle) as archive:
            for filename in ("results.json", "report.json"):
                record = json.loads(archive.read(filename))
                self.assertEqual(record["aggregate_statistics"]["evidence_ladder"], "not tested")
                self.assertIsNone(record["aggregate_statistics"]["permutation_p_value"])
            self.assertIn(b"superseded", archive.read("report.html"))
        self.assertEqual({path: sha256_file(path) for path in paths}, before)


class ScientificInterfaceTests(unittest.TestCase):
    def test_cli_preserves_explicit_pair_declarations(self):
        from laserlab.cli import main
        with patch("laserlab.cli.configure_logging"), patch("laserlab.cli.init_experiment", return_value={"captures": [{}]}) as ingest, redirect_stdout(io.StringIO()):
            code = main(["init", "--experiment", "trial", "--source", "recording.mp4", "--kind", "video",
                         "--label", "matched_control", "--independent-pair-id", "pair-01", "--acknowledge-pair-exchangeability"])
        self.assertEqual(code, 0)
        self.assertEqual(ingest.call_args.kwargs["capture_metadata"],
                         {"independent_pair_id": "pair-01", "pair_exchangeability_acknowledged": True})

    def test_metadata_does_not_invent_or_coerce_exchangeability(self):
        from laserlab.capture_protocol import normalize_capture_metadata
        metadata = normalize_capture_metadata({"pair_exchangeability_acknowledged": "true"})
        self.assertFalse(metadata["pair_exchangeability_acknowledged"])
        self.assertIsNone(metadata["independent_pair_id"])
        with self.assertRaises(ValueError):
            normalize_capture_metadata({"independent_pair_id": ["not-a-string"]})

    def test_gui_pair_fields_and_quality_reminders_are_explicit(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication
        from gui.lab_dashboard import LabDashboardWindow
        app = QApplication.instance() or QApplication([])
        window = LabDashboardWindow(preferences={"schema_version": 1, "recent_experiments": [], "last_source_directory": None})
        try:
            self.assertIsNone(window._capture_metadata()["independent_pair_id"])
            self.assertFalse(window._capture_metadata()["pair_exchangeability_acknowledged"])
            window.independent_pair_id.setText("pair-07")
            window.pair_exchangeability.setChecked(True)
            self.assertEqual(window._capture_metadata()["independent_pair_id"], "pair-07")
            self.assertTrue(window._capture_metadata()["pair_exchangeability_acknowledged"])
            window._update_quality_checklist({})
            text = window.quality_checklist.toPlainText()
            self.assertIn("not recorded controls", text)
            self.assertIn("FDR withheld", text)
            self.assertNotIn("multiple comparisons corrected", text)
            window.latest_report = {"review_state": {"unblinded": True}}
            window._populate_candidate_table({"top_candidates": [{"blind_id": "B1", "source_class": "generated_null",
                                                "unblinded_label": "control", "control_type": "rotated"}]}, unblinded=True)
            self.assertIn("Generated null probe", window.candidate_table.item(0, 1).text())
            self.assertIn("Generated null probe", window.candidate_table.item(0, 1).toolTip())
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
