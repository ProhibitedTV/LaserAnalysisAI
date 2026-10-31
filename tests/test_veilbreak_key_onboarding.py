"""Optional Veilbreak API-key sign-up shortcut.

Tests are offline: no network traffic, key generation, or browser launch.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gui.lab_dashboard import LabDashboardWindow, VEILBREAK_API_KEY_PAGE


class VeilbreakKeyOnboardingTests(unittest.TestCase):
    def test_official_provider_page_is_opened_without_handling_secrets(self):
        dummy = SimpleNamespace(status=SimpleNamespace(showMessage=Mock()))
        with patch("gui.lab_dashboard.QDesktopServices") as browser, patch(
            "gui.lab_dashboard.QMessageBox"
        ) as dialog:
            browser.openUrl.return_value = True
            LabDashboardWindow.open_veilbreak_api_key_page(dummy)
            browser.openUrl.assert_called_once()
            url = browser.openUrl.call_args.args[0]
            self.assertEqual(url.toString(), "https://veilbreak.ai/api-access")
            self.assertEqual(url.toString(), VEILBREAK_API_KEY_PAGE)
            dialog.information.assert_not_called()
            dummy.status.showMessage.assert_called_once()

    def test_browser_failure_displays_manual_provider_url(self):
        dummy = SimpleNamespace(status=SimpleNamespace(showMessage=Mock()))
        with patch("gui.lab_dashboard.QDesktopServices") as browser, patch(
            "gui.lab_dashboard.QMessageBox"
        ) as dialog:
            browser.openUrl.return_value = False
            LabDashboardWindow.open_veilbreak_api_key_page(dummy)
            dialog.information.assert_called_once()
            args = dialog.information.call_args.args
            self.assertIn(VEILBREAK_API_KEY_PAGE, args[-1])
            dummy.status.showMessage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
