"""Offscreen UI tests for local CodeOfReality font onboarding.

These tests do not open native dialogs, access private fonts, or upload files.
They confirm installation remains a deliberate, local action and does not
silently enable experimental OCR.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QLabel
from gui.lab_dashboard import LabDashboardWindow, _ocr_readiness_lines, _saved_ocr_mode_lines
from laserlab.font_ocr import FONT_OCR_ENV


class CodeOfRealityFontGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = LabDashboardWindow(preferences={
            "schema_version": 1, "recent_experiments": [],
            "last_source_directory": None, "brand_font_variant": "classic",
        })
        self.addCleanup(self.window.close)

    def test_menu_has_local_installer_and_separate_opt_in_toggle(self):
        appearances = [
            action.menu() for action in self.window.menuBar().actions()
            if action.text() == "Appearance"
        ]
        self.assertEqual(len(appearances), 1)
        actions = appearances[0].actions()
        installer = [action for action in actions if "Install all seven CodeOfReality" in action.text()]
        self.assertEqual(len(installer), 1)
        self.assertFalse(installer[0].isCheckable())
        toggle = [action for action in actions if "experimental" in action.text().lower()]
        self.assertEqual(len(toggle), 1)
        self.assertTrue(toggle[0].isCheckable())

    def test_system_check_separates_english_tesseract_from_font_templates(self):
        record = {
            "laserlab_version": "test",
            "runtime": {"python_version": "3.11", "frozen": True},
            "dependencies": {},
            "native_runtime": {},
            "fixtures": {"catalog_valid": True, "bundled_file_count": 1, "redistributable_count": 1},
            "ocr": {
                "tesseract": {"status": "available"},
                "codeofreality": {
                    "selection": "disabled",
                    "reference_check": "completed",
                    "verified_variants": 6,
                    "total_variants": 7,
                    "selected_variants": [],
                    "variant_statuses": {"oracle": "missing", "classic": "verified"},
                },
            },
        }
        with (
            patch("gui.lab_dashboard.collect_diagnostics", return_value=record),
            patch("gui.lab_dashboard.QMessageBox.information") as notice,
        ):
            self.window.show_system_check()
        message = notice.call_args.args[2]
        self.assertIn("Tesseract OCR: available", message)
        self.assertIn("English / eng", message)
        self.assertIn("CodeOfReality template OCR: disabled", message)
        self.assertIn("6/7", message)
        self.assertIn("oracle: missing", message)
        self.assertIn(".ttf glyph references do not replace or train Tesseract", message)

    def test_enabling_font_ocr_with_missing_references_warns_not_falls_back(self):
        with (
            patch.dict(os.environ, {FONT_OCR_ENV: ""}),
            patch("gui.lab_dashboard.inspect_font_resources", return_value={"verified_variants": 4}),
            patch("gui.lab_dashboard.QMessageBox.warning") as warning,
        ):
            self.window.toggle_experimental_font_ocr(True)
            self.assertEqual(os.environ[FONT_OCR_ENV], "all")
        self.assertIn("4/7", warning.call_args.args[2])
        self.assertIn("not silently fall back to English OCR", warning.call_args.args[2])
        self.assertIn("4/7", self.window.status.currentMessage())

    def test_review_displays_recorded_ocr_engines_not_current_preferences(self):
        lines = _saved_ocr_mode_lines([
            {"engine_id": "tesseract", "settings": {"language": "eng"}, "text": "AB"},
            {"engine_id": "codeofreality-template:classic", "available": False, "text": None},
        ])
        self.assertIn("requested language(s): eng", "\\n".join(lines))
        self.assertIn("CodeOfReality templates: 1 attempts recorded", "\\n".join(lines))
        missing = _saved_ocr_mode_lines([{"engine_id": "tesseract", "settings": {"language": "eng"}}])
        self.assertIn("no attempts recorded", "\\n".join(missing))
        self.assertNotIn("enabled", "\\n".join(missing))
        disabled = _ocr_readiness_lines({
            "codeofreality": {"selection": "invalid_selection", "selected_variants": []},
            "tesseract": {"status": "available"},
        })
        self.assertIn("Invalid CodeOfReality selection", "\\n".join(disabled))

    def test_three_dimensional_and_outline_wordmarks_use_distinct_qt_style_names(self):
        wordmarks = self.window.findChildren(QLabel, "brandWordmark")
        self.assertTrue(wordmarks)
        for variant, expected_style in (("symbols-3d", "3D"), ("symbols-outline", "Outline")):
            with self.subTest(variant=variant):
                self.window.brand_font_variant = variant
                self.window.brand_font_family = "Code of Reality Symbols"
                self.window._apply_style()
                self.assertTrue(
                    all(label.font().styleName() == expected_style for label in wordmarks)
                )
        self.window.brand_font_variant = "system"
        self.window.brand_font_family = None
        self.window._apply_style()
        self.assertTrue(all(label.font().styleName() != "Outline" for label in wordmarks))

    def test_cancelled_install_does_not_modify_files_or_ocr_selection(self):
        with patch("gui.lab_dashboard.QFileDialog.getExistingDirectory", return_value=""), \
             patch("gui.lab_dashboard.install_local_fonts") as installer:
            self.window.install_codeofreality_fonts()
        installer.assert_not_called()

    def test_successful_install_verifies_all_seven_and_refreshes_wordmark(self):
        with patch("gui.lab_dashboard.QFileDialog.getExistingDirectory", return_value="/local/codeofreality"), \
             patch("gui.lab_dashboard.install_local_fonts", return_value={
                 "installed": 7, "already_present": 0, "total": 7,
             }) as installer, \
             patch("gui.lab_dashboard.inspect_font_resources", return_value={
                 "verified_variants": 7, "all_verified": True,
             }) as verifier, \
             patch("gui.lab_dashboard.load_brand_font", return_value="CodeOfReality") as loader, \
             patch("gui.lab_dashboard.QMessageBox.information") as notice, \
             patch.dict(os.environ, {FONT_OCR_ENV: ""}):
            self.window.install_codeofreality_fonts()
            self.assertFalse(self.window.experimental_font_ocr.isChecked())
            self.assertEqual(os.environ[FONT_OCR_ENV], "")
        installer.assert_called_once_with("/local/codeofreality")
        verifier.assert_called_once_with()
        loader.assert_called_once_with("classic")
        self.assertEqual(self.window.brand_font_family, "CodeOfReality")
        self.assertIn("7/7", self.window.status.currentMessage())
        self.assertIn("experimental", notice.call_args.args[2].lower())

    def test_incomplete_verification_warns_even_when_copy_succeeded(self):
        with patch("gui.lab_dashboard.QFileDialog.getExistingDirectory", return_value="/local/fonts"), \
             patch("gui.lab_dashboard.install_local_fonts", return_value={
                 "installed": 7, "already_present": 0, "total": 7,
             }), \
             patch("gui.lab_dashboard.inspect_font_resources", return_value={
                 "verified_variants": 6, "all_verified": False,
             }), \
             patch("gui.lab_dashboard.QMessageBox.warning") as warning, \
             patch("gui.lab_dashboard.QMessageBox.information") as notice:
            self.window.install_codeofreality_fonts()
        self.assertIn("6/7", warning.call_args.args[2])
        self.assertIn("verification incomplete", warning.call_args.args[1].lower())
        self.assertIn("6/7", self.window.status.currentMessage())
        notice.assert_not_called()

    def test_failed_install_does_not_claim_fonts_are_installed(self):
        with patch("gui.lab_dashboard.QFileDialog.getExistingDirectory", return_value="/incorrect"), \
             patch("gui.lab_dashboard.install_local_fonts", side_effect=ValueError("Unrecognized font")), \
             patch("gui.lab_dashboard.inspect_font_resources") as verifier, \
             patch("gui.lab_dashboard.QMessageBox.warning") as warning, \
             patch("gui.lab_dashboard.QMessageBox.information") as notice:
            self.window.install_codeofreality_fonts()
        verifier.assert_not_called()
        self.assertIn("Unrecognized font", warning.call_args.args[2])
        notice.assert_not_called()


if __name__ == "__main__":
    unittest.main()
