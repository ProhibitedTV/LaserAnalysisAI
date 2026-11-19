"""Synthetic calibration and safety tests for the opt-in reference-font OCR.

Tests do not redistribute or require the CodeOfReality font binaries.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from laserlab.branding import BRAND_FONT_VARIANTS, KNOWN_FONT_SHA256
from laserlab.font_ocr import (
    FONT_OCR_ENV,
    CodeOfRealityTemplateAdapter,
    _match_reference,
    _normalise_glyph,
    _reference_templates,
    _source_mask,
    configured_font_ocr_adapters,
    reference_alphabet,
)
from laserlab.detectors import DetectorContext, run_roi_ocr
from laserlab.ocr_adapters import DeterministicStubAdapter, OCRPayload, OCRRequest


def _synthetic_reference() -> tuple[np.ndarray, dict[str, np.ndarray]]:
    canvas = np.zeros((110, 220), dtype=np.uint8)
    first = np.zeros((110, 90), dtype=np.uint8)
    second = np.zeros((110, 90), dtype=np.uint8)
    for image, character in ((first, "A"), (second, "B")):
        cv2.putText(image, character, (5, 84), cv2.FONT_HERSHEY_SIMPLEX, 2, 255, 3, cv2.LINE_AA)
    canvas[:, 10:100] = first
    canvas[:, 120:210] = second
    return canvas, {"a": _normalise_glyph(first), "b": _normalise_glyph(second)}


class FontOCRTests(unittest.TestCase):
    def test_each_variant_has_an_explicit_reference_alphabet(self):
        self.assertEqual(set(BRAND_FONT_VARIANTS), {
            "classic", "classic-ttf", "circuit", "oracle",
            "symbols", "symbols-3d", "symbols-outline",
        })
        for variant in BRAND_FONT_VARIANTS:
            alphabet = reference_alphabet(variant)
            self.assertEqual(len(alphabet), len(set(alphabet)))
            self.assertIn("a", alphabet)
            self.assertNotIn("?", alphabet)
        self.assertNotIn("A", reference_alphabet("symbols"))
        self.assertNotIn("0", reference_alphabet("classic"))
        self.assertIn("0", reference_alphabet("oracle"))
        with self.assertRaises(ValueError):
            reference_alphabet("unapproved")

    def test_selected_variants_are_explicit_and_safe(self):
        with patch.dict(os.environ, {FONT_OCR_ENV: ""}):
            self.assertEqual(configured_font_ocr_adapters(), [])
        with patch.dict(os.environ, {FONT_OCR_ENV: "classic,oracle,classic"}):
            self.assertEqual([a.variant for a in configured_font_ocr_adapters()], ["classic", "oracle"])
        with patch.dict(os.environ, {FONT_OCR_ENV: "all"}):
            self.assertEqual(len(configured_font_ocr_adapters()), 7)
        with patch.dict(os.environ, {FONT_OCR_ENV: "unknown,classic"}):
            self.assertEqual(configured_font_ocr_adapters(), [])

    def test_synthetic_isolated_glyphs_match_without_training_claims(self):
        image, templates = _synthetic_reference()
        payload = _match_reference(image, templates)
        self.assertEqual(payload.text, "ab")
        self.assertIsNone(payload.confidence)
        self.assertEqual(len(payload.character_boxes), 2)
        self.assertTrue(payload.word_boxes[0]["unvalidated_for_recorded_laser_footage"])
        self.assertEqual(payload.word_boxes[0]["method"], "isolated_glyph_template_comparison")
        inverted = _match_reference(255 - image, templates)
        self.assertEqual(inverted.text, "ab")

    def test_disjoint_vertical_glyphs_cannot_be_combined_into_one_word(self):
        image, templates = _synthetic_reference()
        vertically_separated = np.zeros((250, image.shape[1]), dtype=np.uint8)
        vertically_separated[5:115, :110] = image[:, :110]
        vertically_separated[130:240, 110:] = image[:, 110:]
        result = _match_reference(vertically_separated, templates)
        self.assertIsNone(result.text)
        self.assertEqual(len(result.character_boxes), 0)

    def test_character_boxes_track_each_glyph_not_the_full_word_height(self):
        image, templates = _synthetic_reference()
        staggered = np.zeros((155, image.shape[1]), dtype=np.uint8)
        staggered[12:122, :110] = image[:, :110]
        staggered[26:136, 110:] = image[:, 110:]
        result = _match_reference(staggered, templates)
        self.assertEqual(result.text, "ab")
        self.assertEqual(len(result.character_boxes), 2)
        left_box, right_box = result.character_boxes
        self.assertGreater(right_box["y"], left_box["y"])
        self.assertLess(left_box["height"], result.word_boxes[0]["height"])
        self.assertLess(right_box["height"], result.word_boxes[0]["height"])
        self.assertEqual(
            result.word_boxes[0]["height"],
            max(box["y"] + box["height"] for box in result.character_boxes)
            - min(box["y"] for box in result.character_boxes),
        )

    def test_multiscale_reference_recovers_small_glyph_shape_without_false_confidence(self):
        image, original = _synthetic_reference()
        # Deliberately poor large-size references plus exact small-size
        # references. Only the best match per CHARACTER should be ranked;
        # template-to-template competition would cause false ambiguity.
        templates = {
            letter: (np.zeros((32, 32), dtype=np.uint8), glyph)
            for letter, glyph in original.items()
        }
        payload = _match_reference(image, templates)
        self.assertEqual(payload.text, "ab")
        self.assertIsNone(payload.confidence)
        self.assertEqual(payload.word_boxes[0]["reference_sizes_px"], [96, 64, 40, 24])
        self.assertEqual(len(payload.character_boxes), 2)

    def test_multiscale_duplicate_shapes_abstain_instead_of_guessing(self):
        image, original = _synthetic_reference()
        duplicate = original["a"].copy()
        templates = {
            "a": (np.zeros((32, 32), dtype=np.uint8), original["a"]),
            "b": (np.zeros((32, 32), dtype=np.uint8), original["b"]),
            "c": (duplicate,),
        }
        self.assertIsNone(_match_reference(image, templates).text)

    def test_reference_alphabet_is_not_a_translation_key(self):
        self.assertNotEqual(reference_alphabet("oracle"), reference_alphabet("classic"))
        self.assertTrue(all(ch.islower() or ch.isdigit() for ch in reference_alphabet("symbols")))
        self.assertEqual(reference_alphabet("classic"), reference_alphabet("classic-ttf"))

    def test_ambiguous_or_unstructured_images_abstain(self):
        image, templates = _synthetic_reference()
        ambiguous = {**templates, "c": templates["a"].copy()}
        self.assertIsNone(_match_reference(image, ambiguous).text)
        self.assertIsNone(_match_reference(np.zeros((100, 100), dtype=np.uint8), templates).text)
        noise = np.random.default_rng(123).integers(0, 255, (70, 80), dtype=np.uint8)
        self.assertIsNone(_match_reference(noise, templates).text)
        self.assertIsNone(_source_mask(np.zeros((6, 6), dtype=np.uint8)))

    def test_missing_font_reports_explicit_unavailability(self):
        image, _ = _synthetic_reference()
        with tempfile.TemporaryDirectory() as directory, patch(
            "laserlab.font_ocr.brand_font_path", return_value=Path(directory) / "missing.ttf"
        ):
            attempt = CodeOfRealityTemplateAdapter("oracle").run(OCRRequest(image))
        self.assertFalse(attempt["available"])
        self.assertIsNone(attempt["text"])
        self.assertIn("not installed", attempt["failure_reason"])

    def test_unreviewed_font_bytes_are_not_treated_as_codeofreality_reference(self):
        image, _ = _synthetic_reference()
        with tempfile.TemporaryDirectory() as directory:
            unknown = Path(directory) / "CodeOfReality-Oracle.ttf"
            unknown.write_bytes(b"synthetic unreviewed font bytes" * 100)
            with patch("laserlab.font_ocr.brand_font_path", return_value=unknown):
                attempt = CodeOfRealityTemplateAdapter("oracle").run(OCRRequest(image))
        self.assertFalse(attempt["available"])
        self.assertIsNone(attempt["text"])
        self.assertIn("fingerprint", attempt["failure_reason"])

    def test_normalized_attempts_preserve_experimental_engine_and_roi(self):
        image, templates = _synthetic_reference()
        with tempfile.TemporaryDirectory() as directory:
            font = Path(directory) / "font.ttf"
            font.write_bytes(b"x" * 2048)
            with patch("laserlab.font_ocr.brand_font_path", return_value=font), patch(
                "laserlab.font_ocr._font_sha256",
                return_value=KNOWN_FONT_SHA256["CodeOfReality-Oracle.ttf"],
            ), patch(
                "laserlab.font_ocr._reference_templates", return_value=templates
            ):
                result = CodeOfRealityTemplateAdapter("oracle").run(OCRRequest(
                    image, roi_reference={"id": "reference-shape"}, preprocessing_metadata={"variant": "baseline"},
                ))
        self.assertEqual(result["engine_id"], "codeofreality-template:oracle")
        self.assertEqual(result["text"], "ab")
        self.assertIsNone(result["confidence"])
        self.assertEqual(result["roi_reference"], {"id": "reference-shape"})
        json.dumps(result, allow_nan=False)

    def test_template_attempts_do_not_replace_primary_tesseract_score(self):
        image, _ = _synthetic_reference()
        ctx = DetectorContext(
            experiment_dir=Path("."), run_dir=Path("."), blind_id="blind-1",
            variant_name="raw", original_image=image,
        )
        rois = [{
            "id": "roi-001", "score": 0.9, "fallback": False,
            "bbox": {"x": 0, "y": 0, "width": 220, "height": 110},
            "processed_bbox": {"x": 0, "y": 0, "width": 220, "height": 110},
        }]
        tesseract = DeterministicStubAdapter("tesseract", OCRPayload(text="TESSERACT", confidence=0.9))
        template = DeterministicStubAdapter("codeofreality-template:oracle", OCRPayload(text="ab"))
        with patch("laserlab.detectors._TESSERACT_ADAPTER", tesseract), patch(
            "laserlab.detectors.configured_font_ocr_adapters", return_value=[template]
        ):
            legacy, attempts, summary = run_roi_ocr(image, rois, ctx)
        self.assertEqual(legacy["text"], "TESSERACT")
        self.assertEqual(legacy["engine"], "tesseract")
        self.assertEqual(len(attempts), 2)
        self.assertIn("codeofreality-template:oracle", summary["engine_ids"])
        self.assertEqual(summary["attempt_count"], 2)
        self.assertEqual(summary["agreement_scope"], "per_roi")
        self.assertTrue(summary["primary_agreement_only"])
        self.assertEqual(summary["experimental_agreement_scope"], "separate_correlated_reference_variants")
        self.assertEqual(summary["roi_results"][0]["agreement"]["total_attempts"], 1)
        experimental = summary["roi_results"][0]["experimental_codeofreality"]
        self.assertEqual(experimental["agreement"]["total_attempts"], 1)
        self.assertIn("unvalidated", experimental["interpretation"])

    def test_multiple_correlated_font_attempts_cannot_outvote_primary(self):
        image, _ = _synthetic_reference()
        ctx = DetectorContext(Path("."), Path("."), "blind-1", "raw", image)
        rois = [{
            "id": "roi-001", "score": 0.9, "fallback": False,
            "bbox": {"x": 0, "y": 0, "width": 220, "height": 110},
            "processed_bbox": {"x": 0, "y": 0, "width": 220, "height": 110},
        }]
        primary = DeterministicStubAdapter("tesseract", OCRPayload(text="unrelated", confidence=0.9))
        correlated = [
            DeterministicStubAdapter(f"codeofreality-template:{variant}", OCRPayload(text="abc"))
            for variant in BRAND_FONT_VARIANTS
        ]
        with patch("laserlab.detectors._TESSERACT_ADAPTER", primary), patch(
            "laserlab.detectors.configured_font_ocr_adapters", return_value=correlated
        ):
            legacy, attempts, summary = run_roi_ocr(image, rois, ctx)
        self.assertEqual(legacy["text"], "unrelated")
        self.assertEqual(len(attempts), 8)
        result = summary["roi_results"][0]
        self.assertEqual(result["agreement"]["consensus"]["text"], "unrelated")
        self.assertEqual(result["agreement"]["total_attempts"], 1)
        self.assertEqual(result["experimental_codeofreality"]["agreement"]["total_attempts"], 7)
        self.assertEqual(summary["agreement_scope"], "per_roi")
        self.assertTrue(summary["primary_agreement_only"])
        self.assertEqual(summary["experimental_agreement_scope"], "separate_correlated_reference_variants")



if __name__ == "__main__":
    unittest.main()
