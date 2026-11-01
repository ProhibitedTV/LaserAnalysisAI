"""Offline review/consent and cancellation tests for local results exchange."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import copy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt5.QtWidgets import QApplication

from gui.lab_dashboard import LabDashboardWindow
from gui.research_exchange import ResearchExchangeDialog


class ExchangeGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def preview(self):
        return {"document": {"findings": {"evidence_level": "not tested"}}, "_snapshot_sha256": "a" * 64,
                "_reference_choices": [{"source": "veilbreak", "record_type": "protocol", "record_id": 7}]}

    def test_default_options_and_changed_options_require_fresh_acknowledgement(self):
        builder = Mock(return_value={**self.preview(), "_snapshot_sha256": "b" * 64})
        dialog = ResearchExchangeDialog(self.preview(), builder)
        self.addCleanup(dialog.close)
        self.assertFalse(dialog.hashes.isChecked())
        self.assertIsNone(dialog.reference.currentData())
        self.assertFalse(dialog.save_button.isEnabled())
        self.assertNotIn("snapshot", dialog.document.toPlainText())
        self.assertIn("Source hashes: excluded", dialog.summary.text())
        dialog.privacy.setChecked(True)
        self.assertTrue(dialog.save_button.isEnabled())
        dialog.hashes.setChecked(True)
        builder.assert_called_with(include_source_hashes=True, reference=None)
        self.assertFalse(dialog.privacy.isChecked())
        self.assertFalse(dialog.save_button.isEnabled())
        dialog.privacy.setChecked(True)
        dialog.reference.setCurrentIndex(1)
        builder.assert_called_with(include_source_hashes=True, reference=self.preview()["_reference_choices"][0])
        self.assertFalse(dialog.privacy.isChecked())
        self.assertEqual(dialog.preview["_snapshot_sha256"], "b" * 64)

    def test_refresh_failure_clears_old_document_and_prevents_save(self):
        dialog = ResearchExchangeDialog(self.preview(), Mock(side_effect=ValueError("review became sealed")))
        self.addCleanup(dialog.close)
        dialog.privacy.setChecked(True)
        dialog.hashes.setChecked(True)
        self.assertIsNone(dialog.preview)
        self.assertEqual(dialog.document.toPlainText(), "")
        self.assertEqual(dialog.summary.text(), "")
        self.assertFalse(dialog.save_button.isEnabled())
        dialog.privacy.setChecked(True)
        self.assertFalse(dialog.save_button.isEnabled())

    def test_preparing_without_active_experiment_never_creates_one(self):
        dummy = SimpleNamespace(experiment_dir=None, _error=Mock(), _run_worker=Mock())
        LabDashboardWindow.prepare_research_exchange(dummy)
        dummy._error.assert_called_once()
        dummy._run_worker.assert_not_called()

    def test_cancellation_and_unacknowledged_preview_never_open_save_picker(self):
        experiment = Path("local-experiment")
        dummy = SimpleNamespace(experiment_dir=experiment, _error=Mock(), _run_worker=Mock())
        with patch("gui.lab_dashboard.ResearchExchangeDialog") as factory, \
             patch("gui.lab_dashboard.QFileDialog.getSaveFileName") as picker:
            dialog = factory.return_value
            dialog.exec_.return_value = 0
            LabDashboardWindow._review_research_exchange(dummy, experiment, self.preview())
            dialog.exec_.return_value = 1
            dialog.privacy.isChecked.return_value = False
            LabDashboardWindow._review_research_exchange(dummy, experiment, self.preview())
            picker.assert_not_called()
        dummy._run_worker.assert_not_called()

    def test_save_uses_reviewed_snapshot_and_options_not_an_unreviewed_refresh(self):
        experiment = Path("local-experiment")
        dummy = SimpleNamespace(experiment_dir=experiment, _error=Mock(), _run_worker=Mock(), status=Mock())
        with patch("gui.lab_dashboard.ResearchExchangeDialog") as factory, \
             patch("gui.lab_dashboard.QFileDialog.getSaveFileName", return_value=("exchange.json", "JSON")), \
             patch("gui.lab_dashboard.app_api.export_research_exchange") as export:
            dialog = factory.return_value
            dialog.exec_.return_value = 1
            dialog.preview = self.preview()
            dialog.privacy.isChecked.return_value = True
            dialog.options.return_value = {"include_source_hashes": False, "reference": None}
            LabDashboardWindow._review_research_exchange(dummy, experiment, self.preview())
            task = dummy._run_worker.call_args.args[1]
            task()
            export.assert_called_once_with(experiment, Path("exchange.json"), expected_snapshot="a" * 64,
                                           privacy_acknowledged=True, include_source_hashes=False, reference=None)

    def test_canceled_destination_and_changed_experiment_never_start_export(self):
        experiment = Path("local-experiment")
        dummy = SimpleNamespace(experiment_dir=experiment, _error=Mock(), _run_worker=Mock())
        with patch("gui.lab_dashboard.ResearchExchangeDialog") as factory, \
             patch("gui.lab_dashboard.QFileDialog.getSaveFileName", return_value=("", "JSON")):
            factory.return_value.exec_.return_value = 1
            factory.return_value.preview = self.preview()
            factory.return_value.privacy.isChecked.return_value = True
            LabDashboardWindow._review_research_exchange(dummy, experiment, self.preview())
            dummy.experiment_dir = Path("different-experiment")
            LabDashboardWindow._review_research_exchange(dummy, experiment, self.preview())
        dummy._run_worker.assert_not_called()
        dummy._error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
