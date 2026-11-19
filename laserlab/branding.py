"""Opt-in CodeOfReality wordmark support without redistributing third-party font data.

The font has a limited character set and is suitable only for the lowercase
"laserlab" wordmark, not labels, scientific measurements, or OCR output.
"""

from __future__ import annotations

import os
from pathlib import Path

from .diagnostics import get_state_dir


BRAND_FONT_FILENAME = "CodeOfRealityV1.otf"
BRAND_FONT_FAMILY = "CodeOfReality"
BRAND_WORDMARK = "laserlab"
BRAND_FONT_ENV = "LASERLAB_BRAND_FONT_PATH"


def brand_font_path() -> Path:
    """Where a user may install their own licensed copy of the font."""
    override = os.environ.get(BRAND_FONT_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return get_state_dir() / "fonts" / BRAND_FONT_FILENAME


def load_brand_font() -> str | None:
    """Register a local font after QApplication exists; fall back if unavailable.

    The font is intentionally not distributed in source or release archives
    until its author's redistribution terms have been verified.
    """
    path = brand_font_path()
    if not path.is_file():
        return None

    from PyQt5.QtGui import QFontDatabase

    font_id = QFontDatabase.addApplicationFont(str(path))
    if font_id < 0:
        return None
    return BRAND_FONT_FAMILY if BRAND_FONT_FAMILY in QFontDatabase.applicationFontFamilies(font_id) else None
