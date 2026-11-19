"""Resource qualification without distributing third-party font binaries."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from laserlab import branding
from laserlab import font_qualification
from laserlab.cli import main as cli_main


class FontQualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.files = {
            variant: self.root / filename
            for variant, (_, filename, _) in branding.BRAND_FONT_VARIANTS.items()
        }

    def _path(self, variant):
        return self.files[variant]

    def _samples(self, variant, *_args):
        return {ch: object() for ch in font_qualification.reference_alphabet(variant)}

    def test_missing_fonts_fail_closed_without_exposing_private_paths(self):
        with patch("laserlab.font_qualification.brand_font_path", side_effect=self._path):
            report = font_qualification.inspect_font_resources()
        self.assertEqual(report["verified_variants"], 0)
        self.assertFalse(report["all_verified"])
        self.assertEqual(report["total_variants"], 7)
        self.assertEqual({item["status"] for item in report["fonts"]}, {"missing"})
        self.assertFalse(report["scientific_accuracy_validated"])
        self.assertNotIn(str(self.root), json.dumps(report))

    def test_exactly_seven_verified_fonts_are_renderable_and_counted(self):
        for file in self.files.values():
            file.write_bytes(b"synthetic fixture" * 128)
        with patch("laserlab.font_qualification.brand_font_path", side_effect=self._path), \
             patch("laserlab.font_qualification._sha256", side_effect=lambda path: branding.KNOWN_FONT_SHA256[path.name]), \
             patch("laserlab.font_qualification._reference_templates", side_effect=self._samples):
            report = font_qualification.inspect_font_resources()
        self.assertTrue(report["all_verified"])
        self.assertEqual(report["verified_variants"], 7)
        self.assertEqual({x["status"] for x in report["fonts"]}, {"verified"})
        self.assertEqual(report["fonts"][0]["reference_glyph_count"], 30)
        self.assertEqual(report["fonts"][2]["reference_glyph_count"], 64)
        self.assertEqual(len(report["fonts"]), 7)

    def test_corrupted_oversized_and_broken_glyph_files_have_distinct_states(self):
        for file in self.files.values():
            file.write_bytes(b"synthetic fixture" * 128)
        self.files["classic"].unlink()
        self.files["oracle"].write_bytes(b"corrupted" * 400)
        self.files["symbols"].write_bytes(b"x" * (font_qualification.MAX_FONT_BYTES + 1))
        with patch("laserlab.font_qualification.brand_font_path", side_effect=self._path), \
             patch("laserlab.font_qualification._sha256", side_effect=lambda path: (
                 "bad" if path == self.files["oracle"] else branding.KNOWN_FONT_SHA256[path.name]
             )), patch("laserlab.font_qualification._reference_templates", side_effect=self._samples):
            report = font_qualification.inspect_font_resources()
        states = {x["variant"]: x["status"] for x in report["fonts"]}
        self.assertEqual(states["classic"], "missing")
        self.assertEqual(states["oracle"], "unexpected_fingerprint")
        self.assertEqual(states["symbols"], "invalid_size")
        self.assertEqual(states["circuit"], "verified")
        self.assertFalse(report["all_verified"])

    def test_incomplete_or_unreadable_template_prevents_qualification(self):
        for file in self.files.values():
            file.write_bytes(b"synthetic fixture" * 128)

        def render(variant, *_args):
            if variant == "circuit":
                return {"a": object()}
            if variant == "symbols":
                raise ValueError("Bad glyph table")
            return self._samples(variant)

        with patch("laserlab.font_qualification.brand_font_path", side_effect=self._path), \
             patch("laserlab.font_qualification._sha256", side_effect=lambda path: branding.KNOWN_FONT_SHA256[path.name]), \
             patch("laserlab.font_qualification._reference_templates", side_effect=render):
            report = font_qualification.inspect_font_resources()
        states = {x["variant"]: x["status"] for x in report["fonts"]}
        self.assertEqual(states["circuit"], "incomplete_reference_alphabet")
        self.assertEqual(states["symbols"], "unreadable")
        self.assertEqual(report["verified_variants"], 5)

    def test_cli_releases_can_require_all_without_leaking_local_paths(self):
        output = io.StringIO()
        fake_report = {
            "all_verified": False,
            "total_variants": 7,
            "verified_variants": 0,
            "fonts": [],
            "scientific_accuracy_validated": False,
        }
        with patch("laserlab.font_qualification.inspect_font_resources", return_value=fake_report), \
             contextlib.redirect_stdout(output):
            code = cli_main(["font-verify", "--require-all"])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(output.getvalue())["all_verified"])

        fake_report["all_verified"] = True
        with patch("laserlab.font_qualification.inspect_font_resources", return_value=fake_report), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli_main(["font-verify", "--require-all"]), 0)


if __name__ == "__main__":
    unittest.main()
