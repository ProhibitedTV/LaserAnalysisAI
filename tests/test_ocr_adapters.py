from __future__ import annotations

import json
import math
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from laserlab.ocr_adapters import (
    DeterministicStubAdapter,
    FailingStubAdapter,
    OCRPayload,
    OCRRequest,
    TesseractAdapter,
    UnavailableStubAdapter,
    run_ocr_ensemble,
    summarize_ocr_attempts,
)


class OCRRequestTests(unittest.TestCase):
    def test_request_rejects_invalid_timeout_and_metadata(self) -> None:
        with self.assertRaises(ValueError):
            OCRRequest(object(), timeout_seconds=0)
        with self.assertRaises(TypeError):
            OCRRequest(object(), preprocessing_metadata=[("profile", "wide")])  # type: ignore[arg-type]

    def test_attempt_is_strict_json_safe_and_preserves_audit_metadata(self) -> None:
        request = OCRRequest(
            image=object(),
            roi_reference={"path": Path("crops/roi.png"), "index": 4},
            preprocessing_metadata={"profile": "wide", "threshold": math.nan, "steps": ("gray", "otsu")},
            timeout_seconds=None,
            language="eng",
            script="Latin",
        )
        adapter = DeterministicStubAdapter(
            "stub-a",
            OCRPayload(
                text="CODE",
                confidence=87.5,
                word_boxes=[
                    {
                        "text": "CODE",
                        "confidence": "92",
                        "x": 1,
                        "y": 2,
                        "width": 20,
                        "height": 8,
                        "line": 3,
                    }
                ],
                character_boxes=[{"character": "C", "x": 1, "y": 2, "width": 4, "height": 8}],
            ),
            version="1.2.3",
        )

        attempt = adapter.run(request)

        self.assertEqual(attempt["engine_id"], "stub-a")
        self.assertEqual(attempt["engine_version"], "1.2.3")
        self.assertAlmostEqual(attempt["confidence"], 0.875)
        self.assertAlmostEqual(attempt["word_boxes"][0]["confidence"], 0.92)
        self.assertEqual(attempt["word_boxes"][0]["metadata"], {"line": 3})
        self.assertEqual(attempt["roi_reference"]["path"], "crops\\roi.png" if sys.platform == "win32" else "crops/roi.png")
        self.assertIsNone(attempt["preprocessing_metadata"]["threshold"])
        self.assertEqual(attempt["settings"]["script"], "Latin")
        json.dumps(attempt, allow_nan=False)

    def test_empty_and_null_outputs_remain_distinct(self) -> None:
        request = OCRRequest(object())
        empty = DeterministicStubAdapter("empty", OCRPayload(text="", confidence=None)).run(request)
        null = DeterministicStubAdapter("null", OCRPayload(text=None, confidence=None)).run(request)

        self.assertEqual(empty["text"], "")
        self.assertIsNone(null["text"])
        self.assertIsNone(empty["confidence"])
        self.assertEqual(empty["word_boxes"], [])
        self.assertEqual(null["character_boxes"], [])
        self.assertIsNone(empty["failure_reason"])


class AdapterFailureTests(unittest.TestCase):
    def test_unavailable_engine_is_a_complete_attempt(self) -> None:
        attempt = UnavailableStubAdapter(reason="not installed").run(OCRRequest(object()))

        self.assertFalse(attempt["available"])
        self.assertEqual(attempt["failure_reason"], "not installed")
        self.assertIsNone(attempt["text"])
        self.assertGreaterEqual(attempt["runtime_ms"], 0.0)

    def test_engine_exception_is_contained_without_hiding_attempt(self) -> None:
        attempt = FailingStubAdapter(message="decoder crashed").run(OCRRequest(object()))

        self.assertTrue(attempt["available"])
        self.assertEqual(attempt["failure_reason"], "RuntimeError: decoder crashed")
        self.assertIsNone(attempt["text"])


class EnsembleTests(unittest.TestCase):
    def test_ensemble_includes_empty_null_unavailable_and_failed_attempts(self) -> None:
        adapters = [
            DeterministicStubAdapter("text", OCRPayload(text=" Signal ")),
            DeterministicStubAdapter("empty", OCRPayload(text="")),
            UnavailableStubAdapter("missing"),
            FailingStubAdapter("broken"),
        ]

        result = run_ocr_ensemble(adapters, OCRRequest(object()))
        agreement = result["agreement"]

        self.assertEqual(len(result["attempts"]), 4)
        self.assertEqual(agreement["total_attempts"], 4)
        self.assertEqual(agreement["available_attempts"], 3)
        self.assertEqual(agreement["unavailable_attempts"], 1)
        self.assertEqual(agreement["failed_attempts"], 2)
        self.assertEqual(agreement["nonempty_text_attempts"], 1)
        self.assertEqual(agreement["empty_text_attempts"], 1)
        self.assertEqual(agreement["null_text_attempts"], 2)
        self.assertEqual(len(agreement["pairwise"]), 6)
        self.assertEqual(agreement["distinct_output_count"], 3)
        self.assertFalse(agreement["all_attempts_agree"])
        json.dumps(result, allow_nan=False)

    def test_agreement_normalizes_case_unicode_and_whitespace(self) -> None:
        result = run_ocr_ensemble(
            [
                DeterministicStubAdapter("one", OCRPayload(text="ＣＯＤＥ  17")),
                DeterministicStubAdapter("two", OCRPayload(text="code\n17")),
                DeterministicStubAdapter("three", OCRPayload(text="Code 17")),
            ],
            OCRRequest(object()),
        )

        agreement = result["agreement"]
        self.assertTrue(agreement["all_attempts_agree"])
        self.assertEqual(agreement["pairwise_agreement_rate"], 1.0)
        self.assertEqual(agreement["consensus"]["state"], "text")
        self.assertEqual(agreement["consensus"]["text"], "code 17")

    def test_empty_agrees_with_empty_but_not_null(self) -> None:
        result = run_ocr_ensemble(
            [
                DeterministicStubAdapter("empty-a", OCRPayload(text="")),
                DeterministicStubAdapter("empty-b", OCRPayload(text="   ")),
                DeterministicStubAdapter("null", OCRPayload(text=None)),
            ],
            OCRRequest(object()),
        )

        agreement = result["agreement"]
        self.assertEqual(agreement["empty_text_attempts"], 2)
        self.assertEqual(agreement["null_text_attempts"], 1)
        self.assertEqual(agreement["pairwise_agreement_rate"], 1 / 3)
        self.assertEqual(agreement["consensus"]["state"], "empty")
        self.assertEqual(agreement["consensus"]["text"], "")

    def test_tied_outputs_do_not_claim_consensus(self) -> None:
        result = run_ocr_ensemble(
            [
                DeterministicStubAdapter("a", OCRPayload(text="A")),
                DeterministicStubAdapter("b", OCRPayload(text="B")),
            ],
            OCRRequest(object()),
        )
        self.assertEqual(result["agreement"]["consensus"]["state"], "tie")
        self.assertFalse(result["agreement"]["consensus"]["unique"])
        self.assertIsNone(result["agreement"]["consensus"]["text"])

    def test_empty_ensemble_has_explicit_no_consensus_state(self) -> None:
        result = run_ocr_ensemble([], OCRRequest(object()))
        self.assertEqual(result["attempts"], [])
        self.assertEqual(result["agreement"]["total_attempts"], 0)
        self.assertEqual(result["agreement"]["consensus"]["state"], "none")
        self.assertEqual(result["agreement"]["pairwise_agreement_rate"], 0.0)

    def test_summary_rejects_incomplete_attempts(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing required fields"):
            summarize_ocr_attempts([{"engine_id": "partial"}])


class TesseractAdapterTests(unittest.TestCase):
    class FakeImage:
        shape = (10, 20)

    def test_optional_adapter_maps_tesseract_output_and_settings(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        def image_to_string(image: object, **kwargs: object) -> str:
            calls.append(("string", kwargs))
            return "TEST\n"

        def image_to_data(image: object, **kwargs: object) -> dict[str, list[object]]:
            calls.append(("data", kwargs))
            return {
                "text": ["", "TEST"],
                "conf": ["-1", "87"],
                "left": [0, 1],
                "top": [0, 2],
                "width": [0, 12],
                "height": [0, 6],
            }

        def image_to_boxes(image: object, **kwargs: object) -> str:
            calls.append(("boxes", kwargs))
            return "T 1 2 4 8 0\n"

        fake_module = types.SimpleNamespace(
            get_tesseract_version=lambda: "5.3.4",
            image_to_string=image_to_string,
            image_to_data=image_to_data,
            image_to_boxes=image_to_boxes,
            Output=types.SimpleNamespace(DICT="DICT"),
            pytesseract=types.SimpleNamespace(tesseract_cmd="tesseract"),
        )
        request = OCRRequest(
            self.FakeImage(),
            timeout_seconds=5.0,
            language="eng",
            script="Latin",
            roi_reference="roi-2",
        )

        with patch.dict(sys.modules, {"pytesseract": fake_module}):
            attempt = TesseractAdapter(psm=11, extra_config="-c preserve_interword_spaces=1").run(request)

        self.assertTrue(attempt["available"])
        self.assertIsNone(attempt["failure_reason"])
        self.assertEqual(attempt["engine_version"], "5.3.4")
        self.assertEqual(attempt["text"], "TEST")
        self.assertAlmostEqual(attempt["confidence"], 0.87)
        self.assertEqual(attempt["word_boxes"][0]["text"], "TEST")
        self.assertEqual(attempt["character_boxes"][0]["character"], "T")
        self.assertEqual(attempt["character_boxes"][0]["y"], 2)
        self.assertEqual(attempt["character_boxes"][0]["metadata"]["coordinate_origin"], "top_left")
        self.assertEqual([name for name, _ in calls], ["string", "data", "boxes"])
        for _, kwargs in calls:
            self.assertEqual(kwargs["lang"], "eng+script/Latin")
            self.assertIn("--psm 11", str(kwargs["config"]))
            self.assertGreater(float(kwargs["timeout"]), 0.0)

    def test_missing_tesseract_is_reported_as_unavailable(self) -> None:
        adapter = TesseractAdapter()
        with patch.object(adapter, "_module", side_effect=RuntimeError("not installed")):
            attempt = adapter.run(OCRRequest(object()))

        self.assertFalse(attempt["available"])
        self.assertIn("not installed", attempt["failure_reason"])
        self.assertIsNone(attempt["text"])


if __name__ == "__main__":
    unittest.main()
