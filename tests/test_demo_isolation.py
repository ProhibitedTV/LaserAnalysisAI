"""Practice experiments must never reuse personal research or lose their warning."""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from laserlab import app_api
from laserlab.manifest import load_manifest


class DemoIsolationTests(unittest.TestCase):
    def test_repeated_demo_never_changes_existing_personal_experiment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve() / "personal"
            app_api.create_experiment(base)
            before = (base / "manifest.json").read_bytes()
            with patch("laserlab.app_api.add_capture"), patch("laserlab.app_api.run_analysis", return_value={}):
                first = app_api.run_bundled_demo(base)
                second = app_api.run_bundled_demo(base)
            self.assertNotEqual(first["experiment_dir"], second["experiment_dir"])
            self.assertNotEqual(Path(first["experiment_dir"]), base)
            self.assertEqual((base / "manifest.json").read_bytes(), before)
            self.assertEqual(load_manifest(Path(first["experiment_dir"]))["experiment_purpose"], "demo")

    def test_failed_demo_removes_only_its_new_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve() / "personal"
            app_api.create_experiment(base)
            before = (base / "manifest.json").read_bytes()
            with patch("laserlab.app_api.add_capture", side_effect=ValueError("Unsupported video")):
                with self.assertRaisesRegex(ValueError, "Unsupported video"):
                    app_api.run_bundled_demo(base)
            self.assertEqual(list(Path(temporary).resolve().iterdir()), [base])
            self.assertEqual((base / "manifest.json").read_bytes(), before)

    def test_demo_warning_survives_blinding_reports_unblinding_and_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            payload = app_api.run_bundled_demo(Path(temporary) / "sample", max_frames=1)
            experiment = Path(payload["experiment_dir"])
            manifest = load_manifest(experiment)
            report = app_api.load_latest_report(experiment)
            self.assertEqual(payload["run"]["experiment_purpose"], "demo")
            self.assertEqual(manifest["experiment_purpose"], "demo")
            self.assertEqual(report["experiment_purpose"], "demo")
            self.assertFalse(report["review_state"]["unblinded"])
            self.assertEqual(report["aggregate_statistics"]["evidence_ladder"], "blinded review")
            self.assertNotIn("unblinded_label", json.dumps(report))
            self.assertIn("practice demo only", report["badges"])
            bundle = app_api.export_review_bundle(experiment, Path(temporary) / "practice.zip")
            with zipfile.ZipFile(bundle) as archive:
                for name in ("manifest.json", "results.json", "report.json"):
                    self.assertEqual(json.loads(archive.read(name))["experiment_purpose"], "demo")
                self.assertIn(b"PRACTICE DEMO", archive.read("README.txt"))
                self.assertIn(b"PRACTICE DEMO", archive.read("report.html"))
                self.assertFalse(any(name.startswith("media/") for name in archive.namelist()))
            app_api.complete_review(experiment)
            unblinded = app_api.unblind_latest_run(experiment)
            self.assertTrue(unblinded["review_state"]["unblinded"])
            self.assertEqual(unblinded["experiment_purpose"], "demo")
            self.assertIn("practice demo only", unblinded["badges"])


if __name__ == "__main__":
    unittest.main()
