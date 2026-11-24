"""Experimental, opt-in CodeOfReality reference-glyph OCR adapter.

A supplied OpenType/TrueType font describes shapes; it does not train Tesseract
or establish that any pattern is written language. This module only proposes
strict template matches for isolated, visibly separated reference glyphs.
All existing control comparisons and primary scientific scores remain unchanged.

Font binaries are loaded from user-provided local files, never downloaded.
"""

from __future__ import annotations

import os
import string
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from .branding import BRAND_FONT_VARIANTS, KNOWN_FONT_SHA256, _font_sha256, brand_font_path
from .ocr_adapters import BaseOCRAdapter, OCRPayload, OCRRequest


FONT_OCR_ENV = "LASERLAB_FONT_OCR_VARIANTS"
TEMPLATE_VERSION = "isolated-glyph-multiscale-v2"
# Several small stylized glyphs alias when only a 96 px template is used.
_REFERENCE_SIZES = (96, 64, 40, 24)
_CANVAS = 32
_MAX_GLYPHS = 32
_MAX_IMAGE_DIM = 2048
_MAX_DISTANCE = 0.085  # Normalized mean absolute pixel difference (not probability).
_MIN_MARGIN = 0.018    # Reject ambiguous matches.
_CLASSIC_CHARS = string.ascii_lowercase + "1234"
_SYMBOL_CHARS = string.ascii_lowercase + "1234567"
_EXTENDED_CHARS = string.ascii_lowercase + string.ascii_uppercase + string.digits + "[]"


def reference_alphabet(variant: str) -> str:
    """Use only characters actually encoded in the supplied reference fonts."""
    if variant not in BRAND_FONT_VARIANTS:
        raise ValueError("Unknown CodeOfReality font variant")
    if variant in {"classic", "classic-ttf"}:
        return _CLASSIC_CHARS
    if variant.startswith("symbols"):
        # The Symbols fonts map upper and lower case to identical glyphs;
        # prefer lowercase instead of claiming to distinguish them.
        return _SYMBOL_CHARS
    return _EXTENDED_CHARS


def configured_font_ocr_adapters() -> list["CodeOfRealityTemplateAdapter"]:
    """Return explicit research adapters selected with LASERLAB_FONT_OCR_VARIANTS.

    Empty/unset means the scientific pipeline remains identical to previous
    versions. Set to 'all' or e.g. 'classic,oracle' for side-by-side attempts.
    Invalid values are ignored safely without turning on heuristic OCR.
    """
    value = os.environ.get(FONT_OCR_ENV, "").strip().lower()
    if not value:
        return []
    if value == "all":
        variants = list(BRAND_FONT_VARIANTS)
    else:
        variants = [item.strip() for item in value.split(",")]
    if not variants or any(item not in BRAND_FONT_VARIANTS for item in variants):
        return []
    return [CodeOfRealityTemplateAdapter(item) for item in dict.fromkeys(variants)]


def _normalise_glyph(image: Any) -> Any:
    """Crop nonzero pixels, preserve aspect ratio and letterbox consistently."""
    import cv2
    import numpy as np

    matrix = np.asarray(image, dtype=np.uint8)
    if matrix.ndim != 2 or matrix.size == 0:
        return np.zeros((_CANVAS, _CANVAS), dtype=np.uint8)
    ys, xs = np.nonzero(matrix)
    if not len(xs):
        return np.zeros((_CANVAS, _CANVAS), dtype=np.uint8)
    patch = matrix[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    height, width = patch.shape
    ratio = (_CANVAS - 4) / max(height, width)
    target_w = max(1, round(width * ratio))
    target_h = max(1, round(height * ratio))
    method = cv2.INTER_AREA if ratio < 1 else cv2.INTER_LINEAR
    patch = cv2.resize(patch, (target_w, target_h), interpolation=method)
    canvas = np.zeros((_CANVAS, _CANVAS), dtype=np.uint8)
    top = (_CANVAS - target_h) // 2
    left = (_CANVAS - target_w) // 2
    canvas[top:top + target_h, left:left + target_w] = patch
    return canvas


@lru_cache(maxsize=16)
def _reference_templates(variant: str, filename: str, stamp: int) -> dict[str, Any]:
    """Render provided font glyphs on demand, without static training assets."""
    import numpy as np
    from PIL import ImageFont

    fonts = [ImageFont.truetype(filename, size) for size in _REFERENCE_SIZES]
    templates = {}
    for character in reference_alphabet(variant):
        samples = []
        for font in fonts:
            mask = font.getmask(character, mode="L")
            width, height = mask.size
            if width <= 0 or height <= 0:
                continue
            image = np.frombuffer(bytes(mask), dtype=np.uint8).reshape(height, width)
            if image.any():
                samples.append(_normalise_glyph(image))
        if samples:
            templates[character] = tuple(samples)
    return templates


def _source_mask(image: Any) -> Any:
    """Find high-contrast strokes, rejecting blank/oversized/dense regions."""
    import cv2
    import numpy as np

    source = np.asarray(image)
    if source.ndim not in (2, 3) or source.size == 0:
        return None
    if max(source.shape[:2]) > _MAX_IMAGE_DIM or min(source.shape[:2]) < 8:
        return None
    if source.ndim == 3:
        if source.shape[2] == 4:
            source = cv2.cvtColor(source, cv2.COLOR_BGRA2GRAY)
        elif source.shape[2] == 3:
            source = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
        else:
            return None
    gray = np.clip(source, 0, 255).astype(np.uint8)
    if int(gray.max()) - int(gray.min()) < 30:
        return None
    threshold, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    borders = np.concatenate((gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]))
    # Infer the background polarity from the border; reject near-inverted noise.
    background_bright = float(np.median(borders)) > threshold
    mask = (gray <= threshold) if background_bright else (gray > threshold)
    occupied = float(mask.mean())
    if occupied < 0.003 or occupied > 0.45:
        return None
    return (mask.astype(np.uint8) * 255)


def _column_spans(mask: Any) -> list[tuple[int, int]]:
    import numpy as np

    active = np.any(mask > 0, axis=0).astype(np.int8)
    edge = np.diff(np.pad(active, (1, 1)))
    starts = np.flatnonzero(edge == 1)
    stops = np.flatnonzero(edge == -1)
    return list(zip((int(x) for x in starts), (int(x) for x in stops)))


def _match_reference(image: Any, templates: dict[str, Any]) -> OCRPayload:
    """Abstain entirely if any segment is ambiguous or cannot be matched.

    Designed for one line of clean, isolated glyphs. A result is a candidate
    reference-font shape match, not a calibrated recognition probability.
    """
    import numpy as np

    mask = _source_mask(image)
    if mask is None or not templates:
        return OCRPayload(text=None)
    rows = np.flatnonzero(np.any(mask, axis=1))
    if len(rows) < 7:
        return OCRPayload(text=None)
    top = int(rows[0])
    bottom = int(rows[-1]) + 1
    spans = _column_spans(mask)
    if not spans or len(spans) > _MAX_GLYPHS:
        return OCRPayload(text=None)

    # This adapter recognizes a *single row* of isolated glyphs. Two
    # horizontally disjoint shapes at different vertical positions are not
    # one word, even if they each resemble a glyph when cropped alone.
    glyph_intervals: list[tuple[int, int]] = []
    for left, right in spans:
        if right - left < 3:
            return OCRPayload(text=None)
        filled_rows = np.flatnonzero(np.any(mask[:, left:right] > 0, axis=1))
        if not len(filled_rows):
            return OCRPayload(text=None)
        glyph_intervals.append((int(filled_rows[0]), int(filled_rows[-1]) + 1))
    for (first_top, first_bottom), (next_top, next_bottom) in zip(
        glyph_intervals, glyph_intervals[1:]
    ):
        shared_height = min(first_bottom, next_bottom) - max(first_top, next_top)
        shorter_glyph_height = min(first_bottom - first_top, next_bottom - next_top)
        if shared_height < max(2, int(shorter_glyph_height * 0.2)):
            return OCRPayload(text=None)

    glyphs: list[str] = []
    boxes: list[dict[str, Any]] = []
    distances: list[float] = []
    for (left, right), (glyph_top, glyph_bottom) in zip(spans, glyph_intervals):
        normalized = _normalise_glyph(mask[glyph_top:glyph_bottom, left:right])
        normalized_float = normalized.astype(np.float32)
        ranked = []
        for letter, samples in templates.items():
            # Existing synthetic fixtures may provide one ndarray; installed
            # fonts provide a size-dependent tuple of ndarray references.
            candidates = samples if isinstance(samples, (list, tuple)) else (samples,)
            if not candidates:
                continue
            distance = min(
                float(np.abs(normalized_float - sample.astype(np.float32)).mean() / 255.0)
                for sample in candidates
            )
            ranked.append((distance, letter))
        ranked.sort(key=lambda candidate: (candidate[0], candidate[1]))
        if len(ranked) < 2:
            return OCRPayload(text=None)
        distance, letter = ranked[0]
        margin = ranked[1][0] - distance
        if distance > _MAX_DISTANCE or margin < _MIN_MARGIN:
            return OCRPayload(text=None)
        glyphs.append(letter)
        distances.append(distance)
        boxes.append({
            "character": letter,
            "x": left,
            "y": glyph_top,
            "width": right - left,
            "height": glyph_bottom - glyph_top,
            "template_distance": round(distance, 6),
            "runner_up_margin": round(margin, 6),
        })

    text = "".join(glyphs)
    return OCRPayload(
        text=text,
        confidence=None,  # No calibration on actual recorded diffraction footage.
        word_boxes=[{
            "text": text, "confidence": None,
            "x": spans[0][0], "y": top,
            "width": spans[-1][1] - spans[0][0],
            "height": bottom - top,
            "method": "isolated_glyph_template_comparison",
            "reference_sizes_px": list(_REFERENCE_SIZES),
            "unvalidated_for_recorded_laser_footage": True,
            "mean_pixel_distance": round(float(sum(distances) / len(distances)), 6),
        }],
        character_boxes=boxes,
    )


class CodeOfRealityTemplateAdapter(BaseOCRAdapter):
    """Experimental OCR adapter backed by an opt-in, user-installed font."""

    def __init__(self, variant: str):
        if variant not in BRAND_FONT_VARIANTS:
            raise ValueError("Unknown CodeOfReality variant")
        self.variant = variant
        self.engine_id = f"codeofreality-template:{variant}"

    def run(self, request: OCRRequest) -> dict[str, Any]:
        # The shared request carries Tesseract's language/script defaults.
        # Template matching uses a fixed reference alphabet, not a language
        # model. Record the effective settings even for unavailable attempts.
        if not isinstance(request, OCRRequest):
            raise TypeError("request must be an OCRRequest")
        return super().run(replace(request, language=None, script=None))

    def engine_version(self) -> str:
        return TEMPLATE_VERSION

    def availability(self) -> tuple[bool, str | None]:
        path = brand_font_path(self.variant)
        if not path.is_file():
            return False, f"CodeOfReality font not installed for {self.variant}"
        try:
            size = path.stat().st_size
            if size < 1024 or size > 2 * 1024 * 1024:
                return False, "CodeOfReality reference font is outside allowed size limits"
            filename = BRAND_FONT_VARIANTS[self.variant][1]
            if _font_sha256(path) != KNOWN_FONT_SHA256[filename]:
                return False, "CodeOfReality reference font does not match the reviewed font fingerprint"
        except OSError:
            return False, "CodeOfReality font cannot be read"
        try:
            import PIL.ImageFont  # noqa: F401
            import cv2  # noqa: F401
        except ImportError:
            return False, "Pillow or OpenCV is unavailable"
        return True, None

    def recognize(self, request: OCRRequest) -> OCRPayload:
        path = brand_font_path(self.variant)
        templates = _reference_templates(self.variant, str(path), path.stat().st_mtime_ns)
        return _match_reference(request.image, templates)
