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


if __name__ == "__main__":
    unittest.main()
