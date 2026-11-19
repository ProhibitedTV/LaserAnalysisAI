"""Offline visual comparison of reported symbols and captured laser-light shapes.

This diagnostic compares two explicitly supplied images against each other
and against optional CodeOfReality font references. OCR is a FALLIBLE baseline,
not a decoder. Results never enter the primary blinded scientific score.
"""

from __future__ import annotations

from statistics import median
from typing import Any

from .branding import BRAND_FONT_VARIANTS
from .font_ocr import (
    TEMPLATE_VERSION,
    CodeOfRealityTemplateAdapter,
    _normalise_glyph,
    _source_mask,
)
from .ocr_adapters import OCRRequest, TesseractAdapter


def _mask_comparison(laser: Any, reported: Any) -> dict[str, Any]:
    import numpy as np

    a = _source_mask(laser)
    b = _source_mask(reported)
    if a is None or b is None:
        return {
            "status": "unavailable",
            "reason": "Each image must show an isolated, high-contrast glyph-like shape; blank, huge or crowded crops are rejected.",
            "normalized_pixel_difference": None,
            "foreground_intersection_over_union": None,
        }
    first = _normalise_glyph(a)
    second = _normalise_glyph(b)
    distance = float(np.abs(first.astype(np.float32) - second.astype(np.float32)).mean() / 255.0)
    fg_a = first > 127
    fg_b = second > 127
    union = int(np.logical_or(fg_a, fg_b).sum())
    if not union:
        return {
            "status": "unavailable",
            "reason": "No usable foreground after normalization",
            "normalized_pixel_difference": None,
            "foreground_intersection_over_union": None,
        }
    overlap = float(np.logical_and(fg_a, fg_b).sum() / union)
    return {
        "status": "measured",
        "reason": None,
        "normalized_pixel_difference": round(distance, 6),
        "foreground_intersection_over_union": round(overlap, 6),
    }


def _attempt_summary(attempt: dict[str, Any]) -> dict[str, Any]:
    boxes = attempt.get("word_boxes") or []
    details = boxes[0].get("metadata", {}) if boxes else {}
    return {
        "engine_id": attempt["engine_id"],
        "available": attempt["available"],
        "text": attempt["text"],
        "confidence": attempt.get("confidence"),
        "failure_reason": attempt.get("failure_reason"),
        "mean_pixel_distance": details.get("mean_pixel_distance"),
    }


def compare_reported_and_laser_symbols(
    laser_image: Any,
    reported_symbol_image: Any,
    *,
    variant: str = "all",
    with_tesseract: bool = True,
    control_laser_image: Any | None = None,
    control_laser_images: list[Any] | tuple[Any, ...] | None = None,
) -> dict[str, Any]:
    """Return descriptive comparison only; never assert origin or language."""
    import numpy as np

    if control_laser_images is not None and control_laser_image is not None:
        raise ValueError("Supply either one legacy control_laser_image or control_laser_images, not both")
    if control_laser_images is not None and not isinstance(control_laser_images, (list, tuple)):
        raise ValueError("control_laser_images must be a list or tuple of image crops")
    controls = (
        list(control_laser_images)
        if control_laser_images is not None
        else ([control_laser_image] if control_laser_image is not None else [])
    )
    if len(controls) > 32:
        raise ValueError("At most 32 control laser crops can be compared per diagnostic")

    if variant != "all" and variant not in BRAND_FONT_VARIANTS:
        raise ValueError("Unknown CodeOfReality font variant")
    for label, image in (
        ("laser", laser_image), ("reported symbol", reported_symbol_image),
        *((f"control laser {index + 1}", control) for index, control in enumerate(controls)),
    ):
        matrix = np.asarray(image)
        if matrix.ndim not in (2, 3) or matrix.size == 0:
            raise ValueError(f"The {label} crop must be a nonempty image")
        if min(matrix.shape[:2]) < 8 or max(matrix.shape[:2]) > 2048:
            raise ValueError(f"The {label} image must be between 8 and 2048 pixels on each side")

    raw_visual = _mask_comparison(laser_image, reported_symbol_image)
    control_comparisons = []
    for index, control in enumerate(controls, start=1):
        measured = _mask_comparison(control, reported_symbol_image)
        delta = None
        if raw_visual["status"] == "measured" and measured["status"] == "measured":
            delta = round(
                measured["normalized_pixel_difference"]
                - raw_visual["normalized_pixel_difference"], 6
            )
        control_comparisons.append({
            "control_index": index,
            "comparison": measured,
            "laser_more_visually_similar_than_control": None if delta is None else delta > 0,
            "difference_in_normalized_pixel_distance": delta,
            "matching_capture_conditions_verified": False,
        })

    measurable_distances = sorted(
        record["comparison"]["normalized_pixel_difference"]
        for record in control_comparisons
        if record["comparison"]["status"] == "measured"
    )
    laser_distance = (
        raw_visual["normalized_pixel_difference"]
        if raw_visual["status"] == "measured" else None
    )
    laser_better = laser_tied = laser_worse = fraction_as_similar = None
    if measurable_distances and laser_distance is not None:
        laser_better = sum(value > laser_distance for value in measurable_distances)
        laser_tied = sum(value == laser_distance for value in measurable_distances)
        laser_worse = sum(value < laser_distance for value in measurable_distances)
        # This is a descriptive proportion of selected crops, not a p-value.
        fraction_as_similar = round(
            (laser_tied + laser_worse) / len(measurable_distances), 6
        )
    control_summary = {
        "user_supplied_control_count": len(controls),
        "measured_control_count": len(measurable_distances),
        "unavailable_control_count": len(controls) - len(measurable_distances),
        "median_control_normalized_pixel_difference": (
            round(float(median(measurable_distances)), 6) if measurable_distances else None
        ),
        "laser_more_similar_than_control_count": laser_better,
        "laser_equal_to_control_count": laser_tied,
        "laser_less_similar_than_control_count": laser_worse,
        "fraction_controls_at_least_as_similar_as_laser": fraction_as_similar,
        "matching_capture_conditions_verified": False,
        "statistical_significance_estimated": False,
        "control_independence_verified": False,
    }
    variants = list(BRAND_FONT_VARIANTS) if variant == "all" else [variant]
    comparisons = []
    for name in variants:
        adapter = CodeOfRealityTemplateAdapter(name)
        laser_attempt = adapter.run(OCRRequest(
            image=laser_image,
            roi_reference={"id": "laser_symbol_crop"},
            preprocessing_metadata={"exploratory": True, "image_role": "laser"},
        ))
        reported_attempt = adapter.run(OCRRequest(
            image=reported_symbol_image,
            roi_reference={"id": "reported_symbol_crop"},
            preprocessing_metadata={"exploratory": True, "image_role": "reported_symbol"},
        ))
        a, b = laser_attempt.get("text"), reported_attempt.get("text")
        comparisons.append({
            "variant": name,
            "laser": _attempt_summary(laser_attempt),
            "reported_symbol": _attempt_summary(reported_attempt),
            "identical_reference_label": bool(a and b and a == b),
            "agreement_is_not_independent_evidence": True,
        })

    tesseract = None
    if with_tesseract:
        adapter = TesseractAdapter(psm=10)  # Single isolated character, not a text page.
        tesseract = {
            "laser": _attempt_summary(adapter.run(OCRRequest(
                laser_image, roi_reference={"id": "laser_symbol_crop"}
            ))),
            "reported_symbol": _attempt_summary(adapter.run(OCRRequest(
                reported_symbol_image, roi_reference={"id": "reported_symbol_crop"}
            ))),
            "untrained_on_codeofreality": True,
        }

    return {
        "schema_version": "1.0",
        "purpose": "exploratory-image-shape-comparison",
        "inputs": {
            "laser": "user_supplied_laser_crop",
            "reported_symbol": "user_supplied_reported_symbol_crop",
        },
        "font_reference_model": TEMPLATE_VERSION,
        "comparison": raw_visual,
        # Preserve the original single-control JSON contract for existing users.
        "laser_control": (
            {key: value for key, value in control_comparisons[0].items() if key != "control_index"}
            if len(control_comparisons) == 1 else None
        ),
        "control_comparisons": control_comparisons,
        "control_summary": control_summary,
        "font_attempts": comparisons,
        "tesseract": tesseract,
        "independent_replicates": 0,
        "user_supplied_control_crops": len(controls),
        "matched_negative_controls": 0,
        "statistical_significance_estimated": False,
        "language_or_common_origin_established": False,
        "caution": (
            "These are image-shape comparisons and fallible OCR labels, not "
            "a decoding, validated DMT phenomenology dataset, or evidence of common origin. "
            "Even multiple user-selected laser controls provide descriptive comparisons, "
            "not a significance test: capture matching, independence and blinded selection "
            "have not been verified. Compare against preregistered blinded matched controls "
            "before claiming pattern specificity."
        ),
    }
