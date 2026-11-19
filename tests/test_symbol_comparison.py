"""Reported-symbol versus laser-image comparison: offline, descriptive tests."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from laserlab.cli import build_parser, main
from laserlab.symbol_comparison import _mask_comparison, compare_reported_and_laser_symbols


def _rectangle() -> np.ndarray:
    image = np.zeros((96, 96), dtype=np.uint8)
    cv2.rectangle(image, (25, 13), (57, 79), 255, thickness=-1)
    return image


def _circle() -> np.ndarray:
    image = np.zeros((96, 96), dtype=np.uint8)
    cv2.circle(image, (43, 48), 30, 255, thickness=-1)
    return image


class StubFont:
    def __init__(self, variant):
        self.engine_id = "codeofreality-template:" + variant

    def run(self, request):
        return {
            "engine_id": self.engine_id,
            "available": True,
            "text": "a" if request.preprocessing_metadata.get("image_role") == "laser" else "a",
            "confidence": None,
            "failure_reason": None,
            "word_boxes": [],
        }


class StubTesseract:
    def __init__(self, **_kwargs):
        pass

    def run(self, request):
        return {
            "engine_id": "tesseract",
            "available": True,
            "text": "A",
            "confidence": 0.9,
            "failure_reason": None,
            "word_boxes": [],
        }


class SymbolComparisonTests(unittest.TestCase):
    def test_same_shape_is_zero_pixel_difference_with_full_mask_overlap(self):
        result = _mask_comparison(_rectangle(), _rectangle().copy())
        self.assertEqual(result["status"], "measured")
        self.assertEqual(result["normalized_pixel_difference"], 0)
        self.assertEqual(result["foreground_intersection_over_union"], 1)

    def test_different_shapes_have_nonzero_difference(self):
        result = _mask_comparison(_rectangle(), _circle())
        self.assertEqual(result["status"], "measured")
        self.assertGreater(result["normalized_pixel_difference"], 0)
        self.assertLess(result["foreground_intersection_over_union"], 1)

    def test_optional_laser_control_reports_descriptive_comparison_not_significance(self):
        with patch("laserlab.symbol_comparison.CodeOfRealityTemplateAdapter", StubFont):
            result = compare_reported_and_laser_symbols(
                _rectangle(), _rectangle(), variant="classic",
                with_tesseract=False, control_laser_image=_circle(),
            )
        control = result["laser_control"]
        self.assertEqual(result["comparison"]["normalized_pixel_difference"], 0)
        self.assertGreater(control["comparison"]["normalized_pixel_difference"], 0)
        self.assertTrue(control["laser_more_visually_similar_than_control"])
        self.assertGreater(control["difference_in_normalized_pixel_distance"], 0)
        self.assertFalse(control["matching_capture_conditions_verified"])
        self.assertEqual(result["user_supplied_control_crops"], 1)
        self.assertEqual(result["matched_negative_controls"], 0)
        self.assertFalse(result["statistical_significance_estimated"])
        self.assertFalse(result["language_or_common_origin_established"])

    def test_multiple_controls_yield_descriptive_baseline_not_p_value(self):
        with patch("laserlab.symbol_comparison.CodeOfRealityTemplateAdapter", StubFont):
            result = compare_reported_and_laser_symbols(
                _rectangle(), _rectangle(), variant="classic",
                with_tesseract=False, control_laser_images=[_circle(), _rectangle()],
            )
        self.assertIsNone(result["laser_control"])
        self.assertEqual(result["user_supplied_control_crops"], 2)
        self.assertEqual([c["control_index"] for c in result["control_comparisons"]], [1, 2])
        summary = result["control_summary"]
        self.assertEqual(summary["user_supplied_control_count"], 2)
        self.assertEqual(summary["measured_control_count"], 2)
        self.assertEqual(summary["unavailable_control_count"], 0)
        self.assertEqual(summary["laser_more_similar_than_control_count"], 1)
        self.assertEqual(summary["laser_equal_to_control_count"], 1)
        self.assertEqual(summary["laser_less_similar_than_control_count"], 0)
        self.assertEqual(summary["fraction_controls_at_least_as_similar_as_laser"], 0.5)
        self.assertGreater(summary["median_control_normalized_pixel_difference"], 0)
        self.assertFalse(summary["control_independence_verified"])
        self.assertFalse(summary["matching_capture_conditions_verified"])
        self.assertFalse(summary["statistical_significance_estimated"])
        self.assertEqual(result["matched_negative_controls"], 0)
        self.assertFalse(result["language_or_common_origin_established"])
        json.dumps(result, allow_nan=False)

    def test_unreadable_control_is_reported_without_fabricating_distance(self):
        with patch("laserlab.symbol_comparison.CodeOfRealityTemplateAdapter", StubFont):
            result = compare_reported_and_laser_symbols(
                _rectangle(), _rectangle(), variant="classic", with_tesseract=False,
                control_laser_images=[np.zeros((96, 96), np.uint8), _circle()],
            )
        self.assertEqual(result["control_comparisons"][0]["comparison"]["status"], "unavailable")
        self.assertIsNone(result["control_comparisons"][0]["difference_in_normalized_pixel_distance"])
        self.assertEqual(result["control_summary"]["measured_control_count"], 1)
        self.assertEqual(result["control_summary"]["unavailable_control_count"], 1)

    def test_control_input_limits_and_exclusivity(self):
        with self.assertRaisesRegex(ValueError, "either one legacy"):
            compare_reported_and_laser_symbols(
                _rectangle(), _rectangle(), with_tesseract=False,
                control_laser_image=_circle(), control_laser_images=[_circle()],
            )
        with self.assertRaisesRegex(ValueError, "At most 32"):
            compare_reported_and_laser_symbols(
                _rectangle(), _rectangle(), with_tesseract=False,
                control_laser_images=[_circle()] * 33,
            )
        with self.assertRaisesRegex(ValueError, "list or tuple"):
            compare_reported_and_laser_symbols(
                _rectangle(), _rectangle(), with_tesseract=False,
                control_laser_images=_circle(),
            )
        with self.assertRaisesRegex(ValueError, "control laser 2"):
            compare_reported_and_laser_symbols(
                _rectangle(), _rectangle(), with_tesseract=False,
                control_laser_images=[_circle(), np.empty((0, 0), np.uint8)],
            )

    def test_blank_and_unstructured_images_abstain(self):
        result = _mask_comparison(np.zeros((96, 96), np.uint8), _rectangle())
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["normalized_pixel_difference"])
        self.assertIsNone(result["foreground_intersection_over_union"])

    def test_reported_symbols_and_laser_ocr_are_annotated_but_never_decoded(self):
        with patch("laserlab.symbol_comparison.CodeOfRealityTemplateAdapter", StubFont), \
             patch("laserlab.symbol_comparison.TesseractAdapter", StubTesseract):
            report = compare_reported_and_laser_symbols(_rectangle(), _circle())
        self.assertEqual(report["schema_version"], "1.0")
        self.assertEqual(report["comparison"]["status"], "measured")
        self.assertEqual(len(report["font_attempts"]), 7)
        self.assertTrue(all(item["identical_reference_label"] for item in report["font_attempts"]))
        self.assertTrue(all(item["agreement_is_not_independent_evidence"] for item in report["font_attempts"]))
        self.assertEqual(report["tesseract"]["laser"]["text"], "A")
        self.assertTrue(report["tesseract"]["untrained_on_codeofreality"])
        self.assertEqual(report["independent_replicates"], 0)
        self.assertEqual(report["matched_negative_controls"], 0)
        self.assertFalse(report["language_or_common_origin_established"])
        self.assertFalse(report["statistical_significance_estimated"])
        json.dumps(report, allow_nan=False)

    def test_missing_fonts_do_not_suppress_independent_pixel_comparison(self):
        class UnavailableFont(StubFont):
            def run(self, request):
                return {
                    "engine_id": self.engine_id, "available": False, "text": None,
                    "confidence": None, "failure_reason": "not installed", "word_boxes": [],
                }

        with patch("laserlab.symbol_comparison.CodeOfRealityTemplateAdapter", UnavailableFont):
            result = compare_reported_and_laser_symbols(
                _rectangle(), _rectangle(), variant="oracle", with_tesseract=False,
            )
        self.assertEqual(result["comparison"]["normalized_pixel_difference"], 0)
        self.assertIsNone(result["tesseract"])
        self.assertEqual(len(result["font_attempts"]), 1)
        self.assertFalse(result["font_attempts"][0]["identical_reference_label"])
        self.assertFalse(result["font_attempts"][0]["laser"]["available"])

    def test_rejects_invalid_variants_and_out_of_bounds_images(self):
        with self.assertRaisesRegex(ValueError, "Unknown"):
            compare_reported_and_laser_symbols(_rectangle(), _circle(), variant="fake")
        with self.assertRaisesRegex(ValueError, "8 and 2048"):
            compare_reported_and_laser_symbols(np.zeros((3000, 8), np.uint8), _circle())
        with self.assertRaisesRegex(ValueError, "nonempty"):
            compare_reported_and_laser_symbols(np.empty((0, 0), np.uint8), _circle())

    def test_cli_is_explicit_and_structured(self):
        args = build_parser().parse_args([
            "symbol-compare", "--laser-image", "laser.png",
            "--reported-symbol-image", "reported.png", "--variant", "symbols",
            "--no-tesseract",
        ])
        self.assertEqual(args.variant, "symbols")
        self.assertTrue(args.no_tesseract)
        control_args = build_parser().parse_args([
            "symbol-compare", "--laser-image", "laser.png",
            "--reported-symbol-image", "reported.png", "--control-laser-image", "control.png",
        ])
        self.assertEqual(control_args.control_laser_image, ["control.png"])
        repeat_args = build_parser().parse_args([
            "symbol-compare", "--laser-image", "laser.png",
            "--reported-symbol-image", "reported.png",
            "--control-laser-image", "control-1.png",
            "--control-laser-image", "control-2.png",
        ])
        self.assertEqual(repeat_args.control_laser_image, ["control-1.png", "control-2.png"])

        output = io.StringIO()
        with patch("cv2.imread", side_effect=[_rectangle(), _rectangle()]), \
             patch("laserlab.symbol_comparison.compare_reported_and_laser_symbols",
                   return_value={"schema_version": "1.0", "language_or_common_origin_established": False}) as compare, \
             contextlib.redirect_stdout(output):
            self.assertEqual(main([
                "symbol-compare", "--laser-image", "laser.png",
                "--reported-symbol-image", "reported.png", "--no-tesseract",
            ]), 0)
        self.assertFalse(json.loads(output.getvalue())["language_or_common_origin_established"])
        self.assertFalse(compare.call_args.kwargs["with_tesseract"])
        self.assertIsNone(compare.call_args.kwargs["control_laser_images"])

    def test_cli_forwards_multiple_controls_in_original_order(self):
        output = io.StringIO()
        with patch("cv2.imread", side_effect=[
                 _rectangle(), _rectangle(), _circle(), _rectangle(),
             ]) as reader, patch(
                 "laserlab.symbol_comparison.compare_reported_and_laser_symbols",
                 return_value={"schema_version": "1.0", "language_or_common_origin_established": False},
             ) as compare, contextlib.redirect_stdout(output):
            code = main([
                "symbol-compare", "--laser-image", "laser.png",
                "--reported-symbol-image", "reported.png",
                "--control-laser-image", "first.png",
                "--control-laser-image", "second.png",
                "--no-tesseract",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(reader.call_count, 4)
        controls = compare.call_args.kwargs["control_laser_images"]
        self.assertEqual(len(controls), 2)
        self.assertTrue(np.array_equal(controls[0], _circle()))
        self.assertTrue(np.array_equal(controls[1], _rectangle()))
        self.assertEqual(json.loads(output.getvalue())["schema_version"], "1.0")


if __name__ == "__main__":
    unittest.main()
