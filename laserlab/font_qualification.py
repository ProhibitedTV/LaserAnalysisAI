"""Deterministic, privacy-limited checks for optional CodeOfReality OCR resources.

A successful inspection establishes that the seven reviewed reference fonts
are present and renderable; it does not establish scientific OCR accuracy,
a redistribution license, or that laser captures contain encoded text.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .branding import BRAND_FONT_VARIANTS, KNOWN_FONT_SHA256, brand_font_path
from .font_ocr import TEMPLATE_VERSION, _reference_templates, reference_alphabet


MAX_FONT_BYTES = 2 * 1024 * 1024


def inspect_font_resources() -> dict[str, Any]:
    """Audit every named font without reading recording data or exposing paths.

    Statuses are intentionally distinct: missing, oversized, mismatched bytes,
    failed rasterization, and verified. The original source checksums are also
    required for the installed or packaged binary, preventing silent changes
    to the character-to-glyph reference map.
    """
    records = []
    for variant, (label, filename, family) in BRAND_FONT_VARIANTS.items():
        path = brand_font_path(variant)
        entry: dict[str, Any] = {
            "variant": variant,
            "label": label,
            "filename": filename,
            "family": family,
            "status": "missing",
            "reference_glyph_count": 0,
        }
        try:
            if not path.is_file():
                records.append(entry)
                continue
            stat = path.stat()
            if not 1024 <= stat.st_size <= MAX_FONT_BYTES:
                entry["status"] = "invalid_size"
            elif _sha256(path) != KNOWN_FONT_SHA256[filename]:
                entry["status"] = "unexpected_fingerprint"
            else:
                samples = _reference_templates(variant, str(path), stat.st_mtime_ns)
                expected = reference_alphabet(variant)
                # Keep this strict: missing glyphs are not treated as a
                # silent change to an already reviewed font vocabulary.
                if len(samples) != len(expected) or any(letter not in samples for letter in expected):
                    entry["status"] = "incomplete_reference_alphabet"
                else:
                    entry["status"] = "verified"
                    entry["reference_glyph_count"] = len(samples)
        except (OSError, RuntimeError, ValueError, ImportError, OverflowError):
            entry["status"] = "unreadable"
        records.append(entry)
    verified = sum(entry["status"] == "verified" for entry in records)
    return {
        "schema_version": "1.0",
        "purpose": "local-reference-font-resource-qualification",
        "ocr_model": TEMPLATE_VERSION,
        "total_variants": len(records),
        "verified_variants": verified,
        "all_verified": verified == len(records),
        "scientific_accuracy_validated": False,
        "fonts": records,
    }


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(64 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()
