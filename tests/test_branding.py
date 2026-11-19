"""Tests for optional, non-distributed LaserLab branding font support."""

from __future__ import annotations

import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from laserlab.branding import (
    BRAND_FONT_ENV,
    BRAND_FONT_FILENAME,
    BRAND_FONT_FAMILY,
    BRAND_FONT_VARIANTS,
    ALLOWED_BRAND_FAMILIES,
    BRAND_WORDMARK,
    brand_font_path,
    load_brand_font,
)
from laserlab.theme import dashboard_stylesheet


class BrandingTests(unittest.TestCase):
    def test_install_location_and_explicit_override(self):
        with patch.dict(os.environ, {BRAND_FONT_ENV: ""}), patch(
            "laserlab.branding.get_state_dir", return_value=Path("/example/laserlab")
        ):
            self.assertEqual(brand_font_path(), Path("/example/laserlab/fonts") / BRAND_FONT_FILENAME)
        with patch.dict(os.environ, {BRAND_FONT_ENV: "/example/custom.otf"}):
            self.assertEqual(brand_font_path(), Path("/example/custom.otf"))

    def test_missing_font_uses_regular_type_without_qt(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch("laserlab.branding.brand_font_path", return_value=Path(temporary) / "missing.otf"):
                self.assertIsNone(load_brand_font())
        self.assertIn('QLabel#brandWordmark', dashboard_stylesheet())
        self.assertIn('font-family: "Segoe UI"', dashboard_stylesheet())

    def test_successful_font_registration_is_limited_to_expected_family(self):
        with tempfile.TemporaryDirectory() as temporary:
            font_path = Path(temporary) / BRAND_FONT_FILENAME
            font_path.write_bytes(b"test placeholder")
            class FakeDatabase:
                @staticmethod
                def addApplicationFont(path):
                    self.assertEqual(path, str(font_path))
                    return 7

                @staticmethod
                def applicationFontFamilies(font_id):
                    self.assertEqual(font_id, 7)
                    return [BRAND_FONT_FAMILY]

            fake_qt_gui = types.ModuleType("PyQt5.QtGui")
            fake_qt_gui.QFontDatabase = FakeDatabase
            with patch("laserlab.branding.brand_font_path", return_value=font_path), patch.dict(
                "sys.modules", {"PyQt5.QtGui": fake_qt_gui}
            ):
                self.assertEqual(load_brand_font(), BRAND_FONT_FAMILY)
            self.assertIn('font-family: "CodeOfReality"', dashboard_stylesheet(BRAND_FONT_FAMILY))
            self.assertEqual(BRAND_WORDMARK, "laserlab")

    def test_font_catalog_covers_the_seven_uploaded_variants(self):
        self.assertEqual(set(BRAND_FONT_VARIANTS), {
            "classic", "classic-ttf", "circuit", "oracle",
            "symbols", "symbols-3d", "symbols-outline",
        })
        self.assertEqual(len(ALLOWED_BRAND_FAMILIES), 6)
        with patch.dict(os.environ, {BRAND_FONT_ENV: "/example/classic.otf"}), patch(
            "laserlab.branding.get_state_dir", return_value=Path("/example/state")
        ):
            self.assertEqual(brand_font_path("classic"), Path("/example/classic.otf"))
            self.assertEqual(brand_font_path("oracle"), Path("/example/state/fonts/CodeOfReality-Oracle.ttf"))
            self.assertEqual(brand_font_path("symbols-3d"), Path("/example/state/fonts/CodeOfRealitySymbols-3D.ttf"))

    def test_selected_alternate_family_registers_and_updates_stylesheet(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "CodeOfReality-Circuit.ttf"
            path.write_bytes(b"test placeholder")
            class FakeDatabase:
                @staticmethod
                def addApplicationFont(_path):
                    self.assertEqual(_path, str(path))
                    return 7

                @staticmethod
                def applicationFontFamilies(_font_id):
                    return ["Code of Reality Circuit"]

            fake_qt_gui = types.ModuleType("PyQt5.QtGui")
            fake_qt_gui.QFontDatabase = FakeDatabase
            with patch("laserlab.branding.brand_font_path", return_value=path), patch.dict(
                "sys.modules", {"PyQt5.QtGui": fake_qt_gui}
            ):
                self.assertEqual(load_brand_font("circuit"), "Code of Reality Circuit")
            self.assertIn('font-family: "Code of Reality Circuit"', dashboard_stylesheet("Code of Reality Circuit"))

    def test_system_and_unknown_variant_fall_back_without_touching_qt(self):
        self.assertIsNone(load_brand_font("system"))
        self.assertIsNone(load_brand_font("not-a-style"))
        with self.assertRaises(ValueError):
            brand_font_path("not-a-style")

    def test_unexpected_family_falls_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            font_path = Path(temporary) / BRAND_FONT_FILENAME
            font_path.write_bytes(b"test placeholder")
            class FakeDatabase:
                @staticmethod
                def addApplicationFont(_path):
                    return 4

                @staticmethod
                def applicationFontFamilies(_font_id):
                    return ["SomeOtherFont"]

            fake_qt_gui = types.ModuleType("PyQt5.QtGui")
            fake_qt_gui.QFontDatabase = FakeDatabase
            with patch("laserlab.branding.brand_font_path", return_value=font_path), patch.dict(
                "sys.modules", {"PyQt5.QtGui": fake_qt_gui}
            ):
                self.assertIsNone(load_brand_font())
            self.assertIn('font-family: "Segoe UI"', dashboard_stylesheet("UnexpectedFamily"))


if __name__ == "__main__":
    unittest.main()
