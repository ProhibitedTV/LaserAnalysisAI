"""Optional local CodeOfReality typefaces for the LaserLab wordmark.

These third-party font binaries are never shipped in this repository or
packaged releases. Fonts are decorative only; measurements and OCR are not
rendered using these character-to-symbol maps.
"""

from __future__ import annotations

import os
from pathlib import Path

from .diagnostics import get_state_dir
from .runtime import resource_path


BRAND_WORDMARK = "laserlab"
BRAND_FONT_ENV = "LASERLAB_BRAND_FONT_PATH"

# (Display label, local filename, Qt family as reported by the font's name table)
# Family names were checked against the uploaded OTF and TTF files.
BRAND_FONT_VARIANTS: dict[str, tuple[str, str, str]] = {
    "classic": ("Classic OTF", "CodeOfRealityV1.otf", "CodeOfReality"),
    "classic-ttf": ("Classic TTF", "CodeOfReality.ttf", "CodeOfReality"),
    "circuit": ("Circuit", "CodeOfReality-Circuit.ttf", "Code of Reality Circuit"),
    "oracle": ("Oracle", "CodeOfReality-Oracle.ttf", "Code of Reality Oracle"),
    "symbols": ("Symbols", "CodeOfRealitySymbols 2.ttf", "Code of Reality Symbols"),
    "symbols-3d": ("Symbols 3D", "CodeOfRealitySymbols-3D.ttf", "Code of Reality Symbols 3D"),
    "symbols-outline": ("Symbols Outline", "CodeOfRealitySymbols-Outline.ttf", "Code of Reality Symbols Outline"),
}

BRAND_FONT_FILENAME = BRAND_FONT_VARIANTS["classic"][1]
BRAND_FONT_FAMILY = BRAND_FONT_VARIANTS["classic"][2]
ALLOWED_BRAND_FAMILIES = frozenset(item[2] for item in BRAND_FONT_VARIANTS.values())


def brand_font_path(variant: str = "classic") -> Path:
    """Return the installation path for a known, optional branding font.

    LASERLAB_BRAND_FONT_PATH remains an override for the classic OTF choice
    for backward compatibility; all other variants use named local files.
    """
    if variant not in BRAND_FONT_VARIANTS:
        raise ValueError("Unknown CodeOfReality font variant")
    override = os.environ.get(BRAND_FONT_ENV, "").strip() if variant == "classic" else ""
    if override:
        return Path(override).expanduser()
    # A release builder may explicitly package fonts after confirming permission.
    # Preserve local per-user font support for ordinary source/CI installations.
    bundled = resource_path("fonts", BRAND_FONT_VARIANTS[variant][1])
    if bundled.is_file():
        return bundled
    return get_state_dir() / "fonts" / BRAND_FONT_VARIANTS[variant][1]


def load_brand_font(variant: str = "classic") -> str | None:
    """Register an installed font after QApplication exists, or return None.

    None means use the legible system fallback. Reject family mismatch or a
    failed Qt registration instead of accidentally styling the wordmark with
    an unrelated installed font.
    """
    if variant == "system" or variant not in BRAND_FONT_VARIANTS:
        return None
    path = brand_font_path(variant)
    if not path.is_file():
        return None

    from PyQt5.QtGui import QFontDatabase

    font_id = QFontDatabase.addApplicationFont(str(path))
    if font_id < 0:
        return None
    family = BRAND_FONT_VARIANTS[variant][2]
    return family if family in QFontDatabase.applicationFontFamilies(font_id) else None
