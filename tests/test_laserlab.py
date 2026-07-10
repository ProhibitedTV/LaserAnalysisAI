from __future__ import annotations

import json
import platform
import tempfile
import unittest
import zipfile
from pathlib import Path

from laserlab.artifacts import sha256_json
from scripts.build_release import default_target, executable_name

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
    def test_release_target_and_executable_names(self) -> None:
        self.assertRegex(default_target(), r"^(windows|macos|linux)-(?:x86_64|arm64)$")
        expected = "LaserLab.exe" if platform.system() == "Windows" else "LaserLab"
        self.assertEqual(executable_name("LaserLab"), expected)

    def test_sha256_json_is_stable(self) -> None:
        left = {"b": 2, "a": [3, 1]}
        right = {"a": [3, 1], "b": 2}
        self.assertEqual(sha256_json(left), sha256_json(right))

    def test_fixture_catalog_separates_redistributable_sources(self) -> None:
        from laserlab.fixtures import list_fixtures, validate_fixture_catalog

        redistributable = list_fixtures()
        full_catalog = list_fixtures(include_restricted=True)
        self.assertGreaterEqual(len(redistributable), 3)
        self.assertGreater(len(full_catalog), len(redistributable))
        self.assertTrue(all(item["redistributable"] for item in redistributable))
        media_dir = Path(__file__).resolve().parents[1] / "sample_media"
        self.assertEqual(validate_fixture_catalog(media_dir, require_bundled_files=True), [])
        manifest = json.loads((media_dir / "fixture_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {item["id"] for item in manifest["fixtures"]},
            {item["id"] for item in redistributable},
        )


class ProtocolPresetTests(unittest.TestCase):
    def test_protocol_presets_are_listable_and_describable(self) -> None:
        from laserlab.protocols import describe_protocol, list_protocol_presets

        presets = list_protocol_presets()
        ids = {item["id"] for item in presets}

        self.assertEqual(ids, {"diffraction", "speckle", "ocr", "anomaly"})
        self.assertIn("2D FFT", describe_protocol("diffraction"))
        self.assertIn("speckle", describe_protocol("speckle").lower())


@unittest.skipUnless(HAS_IMAGE_STACK, "OpenCV and NumPy are required for image pipeline tests")
class LaserLabPipelineTests(unittest.TestCase):
    def test_scientific_metrics_detect_synthetic_fixtures(self) -> None:
        import cv2

        from laserlab.scientific import (
            benjamini_hochberg_q_values,
            fft_spectrum_metrics,
            glcm_texture_metrics,
            phase_registration_metrics,
            speckle_contrast_metrics,
        )
        from laserlab.synthetic import (
            create_shifted_copy,
            create_synthetic_grating,
            create_synthetic_positive,
            create_synthetic_speckle,
        )

        golden = json.loads(
            (Path(__file__).parent / "golden" / "scientific_summary.json").read_text(encoding="utf-8")
        )["scientific_metrics"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            grating = cv2.imread(str(create_synthetic_grating(root / "grating.png")), cv2.IMREAD_COLOR)
            speckle = cv2.imread(str(create_synthetic_speckle(root / "speckle.png")), cv2.IMREAD_COLOR)
            positive = create_synthetic_positive(root / "positive.png")
            shifted = create_shifted_copy(positive, root / "shifted.png", shift_x=7, shift_y=4)

            fft = fft_spectrum_metrics(grating)
            speckle_metrics = speckle_contrast_metrics(speckle)
            texture = glcm_texture_metrics(speckle)
            registration = phase_registration_metrics(
                cv2.imread(str(positive), cv2.IMREAD_COLOR),
                cv2.imread(str(shifted), cv2.IMREAD_COLOR),
            )

        self.assertGreater(fft["peak_prominence"], golden["fft_peak_prominence_min"])
        self.assertGreater(fft["ring_energy_ratio"], 0.0)
        self.assertGreater(speckle_metrics["spatial_contrast_mean"], golden["speckle_contrast_min"])
        self.assertLess(speckle_metrics["spatial_contrast_mean"], golden["speckle_contrast_max"])
        self.assertIn("entropy", texture)
        tolerance = golden["phase_shift_tolerance_px"]
        self.assertAlmostEqual(registration["shift_x"], 7.0, delta=tolerance)
        self.assertAlmostEqual(registration["shift_y"], 4.0, delta=tolerance)
        self.assertGreater(registration["response"], golden["phase_registration_response_min"])
        self.assertEqual(benjamini_hochberg_q_values([0.01, 0.04, 0.03]), [0.03, 0.04, 0.04])

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
            self.assertIn("primary_metric_score", report["top_candidates"][0])
            self.assertIn("multiple comparisons corrected", report["badges"])

            latest = app_api.load_latest_report(experiment)
            self.assertEqual(latest["run_id"], run["run_id"])
            csv_path = app_api.export_candidates_csv(experiment, root / "candidates.csv")
            self.assertTrue(csv_path.exists())
            header = csv_path.read_text(encoding="utf-8").splitlines()[0]
            self.assertIn("source_path", header)
            self.assertIn("primary_metric_score", header)

            bundle_path = app_api.export_review_bundle(experiment, root / "review_bundle.zip")
            self.assertTrue(bundle_path.exists())
            with zipfile.ZipFile(bundle_path) as bundle:
                names = set(bundle.namelist())
            self.assertIn("manifest.json", names)
            self.assertIn("report.json", names)
            self.assertIn("results.json", names)
            self.assertIn("environment.json", names)
            self.assertIn("README.txt", names)

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

    def test_matched_null_fixture_cannot_promote_above_control(self) -> None:
        from laserlab.ingest import init_experiment
        from laserlab.pipeline import run_experiment
        from laserlab.synthetic import create_synthetic_negative

        golden = json.loads(
            (Path(__file__).parent / "golden" / "scientific_summary.json").read_text(encoding="utf-8")
        )["null_run"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            laser = root / "laser"
            control = root / "control"
            experiment = root / "experiment"
            create_synthetic_negative(laser / "null.png")
            create_synthetic_negative(control / "null.png")
            init_experiment(laser, "image-set", "laser", experiment, max_frames=1)
            init_experiment(control, "image-set", "control", experiment, max_frames=1)
            run = run_experiment(experiment, profile_name="baseline", blind_seed=314)

        ladder = run["aggregate_statistics"]["evidence_ladder"]
        self.assertIn(ladder, golden["allowed_evidence_levels"])
        self.assertNotIn(ladder, golden["forbidden_evidence_levels"])

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
            app_api.add_capture(
                experiment,
                laser,
                "image-set",
                "laser",
                max_frames=1,
                capture_metadata={
                    "fixture_id": "synthetic-test-positive",
                    "fixture_title": "Synthetic test positive",
                    "limitations": "Unit-test fixture only",
                },
            )
            app_api.add_capture(experiment, control, "image-set", "control", max_frames=1)
            run = app_api.run_analysis(experiment, profile="baseline", blind_seed=99)
            report = app_api.load_latest_report(experiment)

            self.assertEqual(report["run_id"], run["run_id"])
            self.assertIn("local_paths", report)
            self.assertEqual(report["source_provenance"][0]["fixture_id"], "synthetic-test-positive")
            self.assertIn(
                "Unit-test fixture only",
                Path(report["local_paths"]["report_html"]).read_text(encoding="utf-8"),
            )

            manifest = app_api.update_analysis_plan(
                experiment,
                protocol="diffraction",
                primary_metric="fft_peak_prominence",
                preprocessing_intensity="wide",
                control_generation="strict",
                frame_sampling_mode="capped_all_frames",
                roi={"x": 0, "y": 0, "width": 120, "height": 80},
            )
            self.assertEqual(manifest["analysis_plan"]["frame_sampling_mode"], "capped_all_frames")
            estimate = app_api.estimate_run(experiment, profile="wide", protocol="diffraction", control_generation="strict")
            self.assertEqual(estimate["control_generation"], "strict")
            self.assertGreater(estimate["detector_records"], 0)


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
            self.assertEqual(window.tabs.count(), 9)
            self.assertEqual(window.tabs.tabText(0), "Home")
            self.assertEqual(window.tabs.tabText(1), "Experiment Setup")
            self.assertEqual(window.tabs.tabText(4), "Review")
            self.assertGreaterEqual(window.fixture_table.rowCount(), 4)
            self.assertEqual(window.home_demo_button.text(), "Run bundled demo")
            self.assertGreater(window.protocol_combo.count(), 3)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
