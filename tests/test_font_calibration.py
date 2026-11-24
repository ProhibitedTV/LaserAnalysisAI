"""Synthetic-only CodeOfReality font calibration tests."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest.mock import patch

import numpy as np
from PIL import ImageFont

from laserlab import font_calibration as fc
from laserlab.cli import main as cli_main


class FontCalibrationTests(unittest.TestCase):
    def test_rendered_glyph_has_strict_bounded_canvas(self):
        font = ImageFont.load_default()
        image = fc._render_glyph(font, "a")
        self.assertEqual(image.shape, (128, 128))
        self.assertEqual(image.dtype, np.uint8)
        self.assertGreater(int(image.max()), 0)
        self.assertEqual(int(image[0, 0]), 0)

    def test_partial_calibration_has_truthful_synthetic_scope_and_totals(self):
        def fake_variant(variant):
            if variant == "oracle":
                return {
                    "variant": variant, "status": "evaluated", "sample_count": 4,
                    "correct_matches": 2, "incorrect_matches": 1, "abstentions": 1,
                    "unrenderable_samples": 0, "failed_attempts": 0,
                    "negative_control_count": 3, "negative_control_false_accepts": 0,
                    "negative_control_rejections": 3, "negative_control_failed_attempts": 0,
                }
            return {
                "variant": variant, "status": "unavailable", "sample_count": 0,
                "correct_matches": 0, "incorrect_matches": 0, "abstentions": 0,
                "unrenderable_samples": 0, "failed_attempts": 0,
                "negative_control_count": 0, "negative_control_false_accepts": 0,
                "negative_control_rejections": 0, "negative_control_failed_attempts": 0,
            }

        with patch.object(fc, "_calibrate_variant", side_effect=fake_variant):
            record = fc.calibrate_reference_fonts()
        self.assertEqual(record["variant_count"], 7)
        self.assertEqual(record["evaluated_variants"], 1)
        self.assertEqual(record["totals"]["sample_count"], 4)
        self.assertEqual(record["totals"]["correct_matches"], 2)
        self.assertEqual(record["totals"]["incorrect_matches"], 1)
        self.assertEqual(record["totals"]["abstentions"], 1)
        self.assertEqual(record["totals"]["negative_control_rejections"], 3)
        self.assertEqual(record["totals"]["negative_control_failed_attempts"], 0)
        self.assertEqual(record["independent_laser_capture_count"], 0)
        self.assertFalse(record["empirical_accuracy_validated"])
        self.assertEqual(record["reference_sizes_px"], [96, 64, 40, 24])
        with self.assertRaisesRegex(ValueError, "Unknown"):
            fc.calibrate_reference_fonts("invented")

    def test_actual_probe_path_reports_abstentions_and_no_implied_success(self):
        real_font = ImageFont.load_default()

        class StubAdapter:
            def __init__(self, variant):
                self.variant = variant

            def availability(self):
                return True, None

            def run(self, request):
                return {
                    "available": True,
                    "failure_reason": None,
                    "text": None,  # Always abstain rather than invent glyph text.
                }

        with patch.object(fc, "CodeOfRealityTemplateAdapter", StubAdapter), \
             patch.object(fc.ImageFont if hasattr(fc, "ImageFont") else ImageFont, "truetype", return_value=real_font), \
             patch.object(fc, "brand_font_path", return_value="/dummy/font.ttf"):
            record = fc._calibrate_variant("classic")
        self.assertEqual(record["status"], "evaluated")
        self.assertEqual(record["sample_count"], 120)
        self.assertEqual(record["abstentions"], 120)
        self.assertEqual(record["correct_matches"], 0)
        self.assertEqual(record["negative_control_count"], 3)
        self.assertEqual(record["negative_control_false_accepts"], 0)
        self.assertEqual(record["negative_control_rejections"], 3)
        self.assertEqual(record["negative_control_failed_attempts"], 0)

    def test_failed_controls_are_not_successful_rejections(self):
        real_font = ImageFont.load_default()

        class StubAdapter:
            def __init__(self, variant):
                pass

            def availability(self):
                return True, None

            def run(self, request):
                name = request.roi_reference.get("name")
                if name == "blank":
                    return {"available": False, "failure_reason": None, "text": None}
                if name == "uniform":
                    return {"available": True, "failure_reason": "synthetic error", "text": "a"}
                if name == "seeded_noise":
                    return {"available": True, "failure_reason": None, "text": "a"}
                return {"available": True, "failure_reason": None, "text": None}

        with patch.object(fc, "CodeOfRealityTemplateAdapter", StubAdapter), patch.object(
            ImageFont, "truetype", return_value=real_font
        ), patch.object(fc, "brand_font_path", return_value="/dummy/font.ttf"):
            report = fc.calibrate_reference_fonts("classic")
        record = report["variants"][0]
        self.assertEqual(record["status"], "incomplete")
        self.assertEqual(report["evaluated_variants"], 0)
        self.assertEqual(record["negative_control_count"], 3)
        self.assertEqual(record["negative_control_failed_attempts"], 2)
        self.assertEqual(record["negative_control_false_accepts"], 1)
        self.assertEqual(record["negative_control_rejections"], 0)
        self.assertEqual(report["totals"]["negative_control_failed_attempts"], 2)

    def test_failed_positive_attempt_also_marks_calibration_incomplete(self):
        real_font = ImageFont.load_default()

        class StubAdapter:
            def __init__(self, variant):
                pass

            def availability(self):
                return True, None

            def run(self, request):
                failure = "synthetic error" if request.roi_reference["id"] == "synthetic_font_calibration" else None
                return {"available": True, "failure_reason": failure, "text": None}

        with patch.object(fc, "CodeOfRealityTemplateAdapter", StubAdapter), patch.object(
            ImageFont, "truetype", return_value=real_font
        ), patch.object(fc, "brand_font_path", return_value="/dummy/font.ttf"):
            record = fc._calibrate_variant("classic")
        self.assertEqual(record["status"], "incomplete")
        self.assertEqual(record["failed_attempts"], 120)
        self.assertEqual(record["negative_control_rejections"], 3)
        self.assertEqual(record["negative_control_failed_attempts"], 0)

    def test_cli_returns_failure_if_any_variant_has_not_been_calibrated(self):
        record = {
            "variant_count": 7,
            "evaluated_variants": 4,
            "empirical_accuracy_validated": False,
        }
        output = io.StringIO()
        with patch("laserlab.font_calibration.calibrate_reference_fonts", return_value=record), \
             contextlib.redirect_stdout(output):
            code = cli_main(["font-calibrate", "--variant", "all"])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(output.getvalue())["empirical_accuracy_validated"])


if __name__ == "__main__":
    unittest.main()
