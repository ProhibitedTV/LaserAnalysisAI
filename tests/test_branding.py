"""Tests for optional, non-distributed LaserLab branding font support."""

from __future__ import annotations

import hashlib
import json
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
    KNOWN_FONT_SHA256,
    install_local_fonts,
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

    def test_reference_hashes_match_documented_uploaded_font_manifest(self):
        manifest_path = Path(__file__).resolve().parents[1] / "docs" / "codeofreality_font_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            {name: record["sha256"] for name, record in manifest["filenames"].items()},
            KNOWN_FONT_SHA256,
        )

    def test_local_install_checks_all_seven_hashes_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "uploads"
            target = Path(directory) / "local-fonts"
            source.mkdir()
            sample = b"font fixture bytes" * 128
            fake_hashes = {name: hashlib.sha256(sample).hexdigest() for name in KNOWN_FONT_SHA256}
            for name in fake_hashes:
                upload_name = "CodeOfRealityV1.otf_1" if name == "CodeOfRealityV1.otf" else name
                (source / upload_name).write_bytes(sample)
            with patch.dict(KNOWN_FONT_SHA256, fake_hashes, clear=True):
                first = install_local_fonts(source, destination_dir=target)
                self.assertEqual(first, {"installed": 7, "already_present": 0, "total": 7})
                second = install_local_fonts(source, destination_dir=target)
                self.assertEqual(second, {"installed": 0, "already_present": 7, "total": 7})
                self.assertEqual({path.name for path in target.iterdir()}, set(fake_hashes))

    def test_local_install_rejects_changes_before_writing_or_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "uploads"
            target = Path(directory) / "local-fonts"
            source.mkdir()
            sample = b"font fixture bytes" * 128
            fake_hashes = {name: hashlib.sha256(sample).hexdigest() for name in KNOWN_FONT_SHA256}
            for name in fake_hashes:
                (source / name).write_bytes(sample)
            with patch.dict(KNOWN_FONT_SHA256, fake_hashes, clear=True):
                (source / "CodeOfReality-Oracle.ttf").write_bytes(b"wrong font")
                with self.assertRaisesRegex(ValueError, "CodeOfReality-Oracle.ttf"):
                    install_local_fonts(source, destination_dir=target)
                self.assertFalse(target.exists())
                (source / "CodeOfReality-Oracle.ttf").write_bytes(sample)
                target.mkdir()
                (target / "CodeOfReality-Circuit.ttf").write_bytes(b"different font")
                with self.assertRaisesRegex(ValueError, "different installed font"):
                    install_local_fonts(source, destination_dir=target)
                self.assertEqual({path.name for path in target.iterdir()}, {"CodeOfReality-Circuit.ttf"})

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
