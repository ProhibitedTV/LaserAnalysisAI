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


if __name__ == "__main__":
    unittest.main()
