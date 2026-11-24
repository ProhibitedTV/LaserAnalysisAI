"""Standalone template OCR must distinguish incomplete execution from no match."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

import numpy as np

from laserlab.cli import main
from laserlab.font_ocr import CodeOfRealityTemplateAdapter
from laserlab.ocr_adapters import OCRPayload


class FontOCRCLITests(unittest.TestCase):
    def run_cli(self, availability, payload, variant="classic"):
        output = io.StringIO()
        with patch("cv2.imread", return_value=np.zeros((32, 32, 3), dtype=np.uint8)), \
             patch.object(CodeOfRealityTemplateAdapter, "availability", return_value=availability), \
             patch.object(CodeOfRealityTemplateAdapter, "recognize", return_value=payload), \
             contextlib.redirect_stdout(output):
            code = main(["font-ocr", "--image", "dummy.png", "--variant", variant])
        return code, json.loads(output.getvalue())

    def test_completed_abstention_is_not_an_execution_failure(self):
        code, result = self.run_cli((True, None), OCRPayload(text=None))
        self.assertEqual(code, 0)
        self.assertTrue(result["comparison_complete"])
        self.assertFalse(result["scientific_accuracy_validated"])
        attempt = result["attempts"][0]
        self.assertIsNone(attempt["text"])
        self.assertIsNone(attempt["failure_reason"])
        self.assertTrue(attempt["preprocessing_metadata"]["user_supplied_image"])
        self.assertNotIn("known_glyph_reference", attempt["preprocessing_metadata"])
        self.assertIsNone(attempt["settings"]["language"])

    def test_unavailable_font_is_incomplete_but_keeps_attempt(self):
        code, result = self.run_cli((False, "font missing"), OCRPayload())
        self.assertEqual(code, 2)
        self.assertFalse(result["comparison_complete"])
        self.assertFalse(result["attempts"][0]["available"])
        self.assertEqual(result["attempts"][0]["failure_reason"], "font missing")

    def test_recognition_error_is_incomplete(self):
        code, result = self.run_cli((True, None), OCRPayload(failure_reason="synthetic error"))
        self.assertEqual(code, 2)
        self.assertFalse(result["comparison_complete"])
        self.assertEqual(result["attempts"][0]["failure_reason"], "synthetic error")

    def test_all_variants_are_preserved_when_unavailable(self):
        code, result = self.run_cli((False, "font missing"), OCRPayload(), "all")
        self.assertEqual(code, 2)
        self.assertFalse(result["comparison_complete"])
        self.assertEqual(len(result["attempts"]), 7)
        self.assertEqual(len({a["engine_id"] for a in result["attempts"]}), 7)

    def test_match_is_completed_but_not_scientific_validation(self):
        code, result = self.run_cli((True, None), OCRPayload(text="a"))
        self.assertEqual(code, 0)
        self.assertTrue(result["comparison_complete"])
        self.assertFalse(result["scientific_accuracy_validated"])
        self.assertEqual(result["attempts"][0]["text"], "a")


if __name__ == "__main__":
    unittest.main()
