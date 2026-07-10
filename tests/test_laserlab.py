from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from laserlab.artifacts import sha256_json

try:
    import cv2  # noqa: F401
    import numpy  # noqa: F401

    HAS_IMAGE_STACK = True
except ImportError:
    HAS_IMAGE_STACK = False

try:
    import PyQt5  # noqa: F401

    HAS_PYQT = True
except ImportError:
    HAS_PYQT = False


class HashingTests(unittest.TestCase):
    def test_sha256_json_is_stable(self) -> None:
        left = {"b": 2, "a": [3, 1]}
        right = {"a": [3, 1], "b": 2}
        self.assertEqual(sha256_json(left), sha256_json(right))

    def test_fixture_catalog_separates_redistributable_sources(self) -> None:
        from laserlab.fixtures import list_fixtures

        redistributable = list_fixtures()
        full_catalog = list_fixtures(include_restricted=True)
        self.assertGreaterEqual(len(redistributable), 3)
        self.assertGreater(len(full_catalog), len(redistributable))
        self.assertTrue(all(item["redistributable"] for item in redistributable))


@unittest.skipUnless(HAS_IMAGE_STACK, "OpenCV and NumPy are required for image pipeline tests")
class LaserLabPipelineTests(unittest.TestCase):
    def test_image_set_ingest_run_and_report(self) -> None:
        from laserlab import app_api
        from laserlab.ingest import init_experiment
        from laserlab.manifest import load_manifest
        from laserlab.pipeline import run_experiment
        from laserlab.synthetic import create_synthetic_negative, create_synthetic_positive

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_laser = root / "laser"
            source_control = root / "control"
            experiment = root / "experiment"

            create_synthetic_positive(source_laser / "laser_001.png", text="SIGNAL 314")
            create_synthetic_negative(source_control / "control_001.png")

            init_experiment(source_laser, "image-set", "laser", experiment)
            init_experiment(source_control, "image-set", "control", experiment)

            manifest = load_manifest(experiment)
            self.assertEqual(len(manifest["captures"]), 2)
            self.assertEqual(manifest["captures"][0]["frames"][0]["frame_index"], 0)
            self.assertTrue((experiment / manifest["captures"][0]["frames"][0]["path"]).exists())

            run = run_experiment(experiment, profile_name="baseline", blind_seed=123)
            run_dir = experiment / "runs" / run["run_id"]

            self.assertTrue((run_dir / "results.json").exists())
            self.assertTrue((run_dir / "report.json").exists())
            self.assertTrue((run_dir / "report.html").exists())
            self.assertGreater(len(run["results"]), 0)
            self.assertIn("permutation_p_value", run["aggregate_statistics"])
            self.assertIn("evidence_ladder", run["aggregate_statistics"])

            report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["run_id"], run["run_id"])
            self.assertIn("top_candidates", report)
            self.assertIn("source_path", report["top_candidates"][0])

            latest = app_api.load_latest_report(experiment)
            self.assertEqual(latest["run_id"], run["run_id"])
            csv_path = app_api.export_candidates_csv(experiment, root / "candidates.csv")
            self.assertTrue(csv_path.exists())
            self.assertIn("source_path", csv_path.read_text(encoding="utf-8").splitlines()[0])

    def test_tesseract_is_optional(self) -> None:
        from laserlab.detectors import run_ocr
        from laserlab.synthetic import create_synthetic_positive
        import cv2

        with tempfile.TemporaryDirectory() as temp:
            image_path = create_synthetic_positive(Path(temp) / "positive.png")
            image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
            result = run_ocr(image)
            self.assertIn("available", result)
            self.assertIn("text", result)

    def test_wide_profile_has_parameter_sweep_variants(self) -> None:
        from laserlab.manifest import WIDE_PROFILE
        from laserlab.preprocessing import apply_profile_variants
        from laserlab.synthetic import create_synthetic_positive
        import cv2

        with tempfile.TemporaryDirectory() as temp:
            image_path = create_synthetic_positive(Path(temp) / "positive.png")
            image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            processed = apply_profile_variants(image, WIDE_PROFILE)

        variant_names = {item.variant_name for item in processed}
        self.assertGreaterEqual(len(processed), 15)
        self.assertIn("threshold_128", variant_names)
        self.assertIn("adaptive_51", variant_names)
        self.assertIn("resize_2x_otsu", variant_names)

    def test_app_api_fixture_style_flow(self) -> None:
        from laserlab import app_api
        from laserlab.synthetic import create_synthetic_negative, create_synthetic_positive

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            laser = root / "laser"
            control = root / "control"
            experiment = root / "experiment"
            create_synthetic_positive(laser / "laser.png")
            create_synthetic_negative(control / "control.png")

            manifest = app_api.create_experiment(experiment)
            self.assertIn("experiment_id", manifest)
            app_api.add_capture(experiment, laser, "image-set", "laser", max_frames=1)
            app_api.add_capture(experiment, control, "image-set", "control", max_frames=1)
            run = app_api.run_analysis(experiment, profile="baseline", blind_seed=99)
            report = app_api.load_latest_report(experiment)

            self.assertEqual(report["run_id"], run["run_id"])
            self.assertIn("local_paths", report)


@unittest.skipUnless(HAS_PYQT, "PyQt5 is required for dashboard smoke tests")
class LaserLabGuiTests(unittest.TestCase):
    def test_dashboard_instantiates_core_tabs(self) -> None:
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication
        from gui.lab_dashboard import LabDashboardWindow

        app = QApplication.instance() or QApplication([])
        window = LabDashboardWindow()
        try:
            self.assertEqual(window.tabs.count(), 5)
            self.assertEqual(window.tabs.tabText(0), "Experiment")
            self.assertEqual(window.tabs.tabText(2), "Review")
            self.assertGreaterEqual(window.fixture_table.rowCount(), 4)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
