"""Offline UI consent, explicit-action and provenance presentation tests."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import Mock, patch

from PyQt5.QtWidgets import QApplication
from gui.lab_dashboard import LabDashboardWindow


class CacheGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.preferences = {"schema_version": 1, "recent_experiments": [], "last_source_directory": None}
        self.window = LabDashboardWindow(preferences=dict(self.preferences))
        self.addCleanup(self.window.close)

    def test_cache_defaults_off_and_startup_or_disabled_saved_button_do_no_io(self):
        with patch("gui.lab_dashboard.CatalogCache") as cache, patch("gui.lab_dashboard.refresh_catalog") as refresh, \
             patch("gui.lab_dashboard.open_saved_catalog") as saved:
            window = LabDashboardWindow(preferences=dict(self.preferences))
            self.addCleanup(window.close)
            self.assertFalse(window.veilbreak_cache_optin.isChecked())
            self.assertFalse(window.saved_protocols_button.isEnabled())
            self.assertFalse(window.saved_experiments_button.isEnabled())
            window.saved_protocols_button.click()
            cache.assert_not_called()
            refresh.assert_not_called()
            saved.assert_not_called()

    def test_explicit_opt_in_persists_but_never_fetches_and_busy_blocks_controls(self):
        with patch("gui.lab_dashboard.set_veilbreak_cache_enabled", return_value={**self.preferences, "veilbreak_cache_enabled": True}) as setter, \
             patch("gui.lab_dashboard.refresh_catalog") as refresh, patch("gui.lab_dashboard.CatalogCache") as cache:
            self.window.veilbreak_cache_optin.setChecked(True)
            setter.assert_called_once_with(True)
            self.assertTrue(self.window.saved_protocols_button.isEnabled())
            self.window._set_busy(True)
            self.assertFalse(self.window.saved_protocols_button.isEnabled())
            self.assertFalse(self.window.veilbreak_cache_optin.isEnabled())
            self.window._set_busy(False)
            self.assertTrue(self.window.saved_protocols_button.isEnabled())
            refresh.assert_not_called()
            cache.assert_not_called()

    def test_disabling_keeps_clear_available_and_failed_preference_write_restores_choice(self):
        self.window.preferences["veilbreak_cache_enabled"] = True
        self.window.veilbreak_cache_optin.blockSignals(True)
        self.window.veilbreak_cache_optin.setChecked(True)
        self.window.veilbreak_cache_optin.blockSignals(False)
        with patch("gui.lab_dashboard.set_veilbreak_cache_enabled", side_effect=OSError("private path")), \
             patch.object(self.window, "_error") as error:
            self.window.veilbreak_cache_optin.setChecked(False)
        self.assertTrue(self.window.veilbreak_cache_optin.isChecked())
        self.assertTrue(self.window.preferences["veilbreak_cache_enabled"])
        error.assert_called_once()
        with patch("gui.lab_dashboard.set_veilbreak_cache_enabled", return_value={**self.preferences, "veilbreak_cache_enabled": False}):
            self.window.veilbreak_cache_optin.setChecked(False)
        self.assertFalse(self.window.saved_protocols_button.isEnabled())
        self.assertTrue(self.window.clear_catalog_cache_button.isEnabled())

    def test_refresh_and_saved_open_dispatch_distinct_explicit_operations(self):
        with patch.object(self.window, "_run_worker") as worker, \
             patch("gui.lab_dashboard.refresh_catalog") as refresh, patch("gui.lab_dashboard.open_saved_catalog") as saved:
            self.window.browse_veilbreak("protocols")
            worker.call_args.args[1]()
            refresh.assert_called_once_with("protocols", cache_enabled=False)
            saved.assert_not_called()
            self.window.browse_saved_veilbreak("experiments")
            worker.call_args.args[1]()
            saved.assert_called_once_with("experiments", cache_enabled=False)
            self.assertEqual(refresh.call_count, 1)

    def test_view_discloses_saved_time_expiration_and_failed_persistence(self):
        view = {"records": [{"record_id": 7}], "cache_status": "saved", "provenance": {
            "origin": "saved", "retrieved_at": "2026-11-01T01:00:00+00:00", "expires_at": "2026-11-02T01:00:00+00:00"}}
        with patch.object(self.window, "_choose_veilbreak_record") as chooser:
            self.window._catalog_ready("protocols", view)
            note = chooser.call_args.kwargs["source_note"]
            self.assertIn("Saved copy", note)
            self.assertIn(view["provenance"]["retrieved_at"], note)
            self.assertIn("license/attribution remains unverified", note)
            view["provenance"]["origin"] = "live"
            view["cache_status"] = "save_failed"
            self.window._catalog_ready("protocols", view)
            self.assertIn("Saving the offline copy failed", chooser.call_args.kwargs["source_note"])

    def test_clear_is_explicit_and_does_not_refresh_or_touch_experiments(self):
        with patch.object(self.window, "_run_worker") as worker, patch("gui.lab_dashboard.CatalogCache") as cache, \
             patch("gui.lab_dashboard.refresh_catalog") as refresh:
            self.window.clear_public_catalog_cache()
            cache.assert_not_called()
            worker.call_args.args[1]()
            cache.return_value.clear.assert_called_once()
            refresh.assert_not_called()
        self.assertIsNone(self.window.experiment_dir)


if __name__ == "__main__":
    unittest.main()
