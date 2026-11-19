"""Reproducible, synthetic self-consistency probes for reference-glyph OCR.

Samples are generated *from the same installed fonts* used for templates.
Consequently, scores are calibration diagnostics, NOT estimates of accuracy
on independent laser footage or evidence that encoded text exists in an image.
"""

from __future__ import annotations

from typing import Any

from .branding import BRAND_FONT_VARIANTS, brand_font_path
from .font_ocr import CodeOfRealityTemplateAdapter, TEMPLATE_VERSION, reference_alphabet
from .ocr_adapters import OCRRequest


CALIBRATION_SIZES = (96, 64, 40, 24)
CANVAS_SIZE = 128


def _render_glyph(font: Any, character: str) -> Any | None:
    """Center a single font mask on an otherwise empty image."""
    import numpy as np

    mask = font.getmask(character, mode="L")
    width, height = mask.size
    if width <= 0 or height <= 0 or width > CANVAS_SIZE - 4 or height > CANVAS_SIZE - 4:
        return None
    source = np.frombuffer(bytes(mask), dtype=np.uint8).reshape(height, width)
    canvas = np.zeros((CANVAS_SIZE, CANVAS_SIZE), dtype=np.uint8)
    x = (CANVAS_SIZE - width) // 2
    y = (CANVAS_SIZE - height) // 2
    canvas[y:y + height, x:x + width] = source
    return canvas


def _control_images() -> list[tuple[str, Any]]:
    """Fixed nonsensical controls, not independent real-world negatives."""
    import numpy as np

    return [
        ("blank", np.zeros((CANVAS_SIZE, CANVAS_SIZE), dtype=np.uint8)),
        ("uniform", np.full((CANVAS_SIZE, CANVAS_SIZE), 90, dtype=np.uint8)),
        ("seeded_noise", np.random.default_rng(1417).integers(
            0, 256, (CANVAS_SIZE, CANVAS_SIZE), dtype=np.uint8
        )),
    ]


def _calibrate_variant(variant: str) -> dict[str, Any]:
    from PIL import ImageFont

    adapter = CodeOfRealityTemplateAdapter(variant)
    available, failure_reason = adapter.availability()
    record: dict[str, Any] = {
        "variant": variant,
        "status": "unavailable" if not available else "evaluated",
        "reason": failure_reason,
        "sample_count": 0,
        "correct_matches": 0,
        "incorrect_matches": 0,
        "abstentions": 0,
        "unrenderable_samples": 0,
        "failed_attempts": 0,
        "negative_control_count": 0,
        "negative_control_false_accepts": 0,
    }
    if not available:
        return record
    glyphs = reference_alphabet(variant)
    path = brand_font_path(variant)
    try:
        for size in CALIBRATION_SIZES:
            font = ImageFont.truetype(str(path), size)
            for character in glyphs:
                image = _render_glyph(font, character)
                if image is None:
                    record["unrenderable_samples"] += 1
                    continue
                request = OCRRequest(
                    image=image,
                    roi_reference={"id": "synthetic_font_calibration"},
                    preprocessing_metadata={"synthetic": True, "reference_size_px": size},
                )
                attempt = adapter.run(request)
                record["sample_count"] += 1
                if attempt.get("failure_reason") is not None or not attempt.get("available"):
                    record["failed_attempts"] += 1
                elif attempt.get("text") == character:
                    record["correct_matches"] += 1
                elif attempt.get("text") is None or attempt.get("text") == "":
                    record["abstentions"] += 1
                else:
                    record["incorrect_matches"] += 1
        for name, image in _control_images():
            attempt = adapter.run(OCRRequest(
                image=image,
                roi_reference={"id": "synthetic_negative_control", "name": name},
                preprocessing_metadata={"synthetic": True},
            ))
            record["negative_control_count"] += 1
            if attempt.get("text"):
                record["negative_control_false_accepts"] += 1
    except (OSError, RuntimeError, ValueError, ImportError) as exc:
        record["status"] = "probe_failed"
        record["reason"] = type(exc).__name__
    return record


def calibrate_reference_fonts(variant: str = "all") -> dict[str, Any]:
    """Perform descriptive per-font synthetic probes without saving media."""
    if variant != "all" and variant not in BRAND_FONT_VARIANTS:
        raise ValueError("Unknown CodeOfReality variant")
    variants = list(BRAND_FONT_VARIANTS) if variant == "all" else [variant]
    records = [_calibrate_variant(name) for name in variants]
    totals = {
        field: sum(item[field] for item in records)
        for field in (
            "sample_count", "correct_matches", "incorrect_matches", "abstentions",
            "unrenderable_samples", "failed_attempts", "negative_control_count",
            "negative_control_false_accepts",
        )
    }
    return {
        "schema_version": "1.0",
        "purpose": "synthetic-font-self-consistency-only",
        "independent_laser_capture_count": 0,
        "empirical_accuracy_validated": False,
        "template_version": TEMPLATE_VERSION,
        "reference_sizes_px": list(CALIBRATION_SIZES),
        "variant_count": len(records),
        "evaluated_variants": sum(item["status"] == "evaluated" for item in records),
        "totals": totals,
        "variants": records,
    }
