"""Qt privacy, cancellation and pre-run plan contracts for session comparison."""
from __future__ import annotations
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication
from gui.lab_dashboard import LabDashboardWindow
from laserlab.replication import _compare_records
from laserlab.stats import summarize_blinded_results

try:
    from test_replication import synthetic_run
except ModuleNotFoundError:
    from tests.test_replication import synthetic_run


class ReplicationGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.window = LabDashboardWindow(preferences={"schema_version": 1, "recent_experiments": [], "last_source_directory": None})
        self.window.experiment_dir = self.root / "active"
        self.summary = _compare_records([synthetic_run(1), synthetic_run(2)], ["first", "second"])
        self.directories = [self.root / "one", self.root / "two"]
        self.addCleanup(self.window.close)

    def test_count_or_directory_cancellation_preserves_previous_context(self):
        self.window._session_comparison_ready(self.summary, self.directories)
        with patch("gui.lab_dashboard.QInputDialog.getInt", return_value=(2, False)), patch.object(self.window, "_run_worker") as worker:
            self.window.compare_local_sessions()
            worker.assert_not_called()
        with patch("gui.lab_dashboard.QInputDialog.getInt", return_value=(2, True)), \
             patch("gui.lab_dashboard.QFileDialog.getExistingDirectory", side_effect=[str(self.root / "new"), ""]), \
             patch.object(self.window, "_run_worker") as worker:
            self.window.compare_local_sessions()
            worker.assert_not_called()
        self.assertEqual(self.window.comparison_directories, self.directories)
        self.assertEqual(self.window.experiment_dir, self.root / "active")

    def test_new_summary_requires_fresh_privacy_review_before_export(self):
        self.window._session_comparison_ready(self.summary, self.directories)
        self.assertFalse(self.window.session_privacy.isChecked())
        self.assertFalse(self.window.session_export_button.isEnabled())
        with patch.object(self.window, "_error") as error, patch("gui.lab_dashboard.QFileDialog.getSaveFileName") as picker:
            self.window.export_session_summary()
            error.assert_called_once()
            picker.assert_not_called()
        self.window.session_privacy.setChecked(True)
        self.assertTrue(self.window.session_export_button.isEnabled())
        self.window._session_comparison_ready(self.summary, self.directories)
        self.assertFalse(self.window.session_privacy.isChecked())
        self.assertFalse(self.window.session_export_button.isEnabled())

    def test_export_cancellation_and_worker_use_reviewed_snapshot(self):
        self.window._session_comparison_ready(self.summary, self.directories)
        self.window.session_privacy.setChecked(True)
        with patch("gui.lab_dashboard.QFileDialog.getSaveFileName", return_value=("", "")), patch.object(self.window, "_run_worker") as worker:
            self.window.export_session_summary()
            worker.assert_not_called()
        output = self.root / "summary.json"
        with patch("gui.lab_dashboard.QFileDialog.getSaveFileName", return_value=(str(output), "JSON")), \
             patch.object(self.window, "_run_worker") as worker, patch("gui.lab_dashboard.app_api.export_session_comparison", return_value=output) as export:
            self.window.export_session_summary()
            task = worker.call_args.args[1]
            self.window.comparison_directories = [self.root / "different"]
            task()
            self.assertEqual(export.call_args.args[0], self.directories)
            self.assertEqual(export.call_args.kwargs["expected_snapshot"], self.summary["_snapshot_sha256"])
            self.assertIs(export.call_args.kwargs["privacy_acknowledged"], True)

    def test_active_blind_review_blocks_selection_and_clears_previous_summary(self):
        self.window._session_comparison_ready(self.summary, self.directories)
        report = {"review_state": {"unblinded": False}, "review_session": {"complete": False},
                  "aggregate_statistics": summarize_blinded_results([]), "summary": {}, "top_candidates": [], "interpretation": {}}
        self.window.latest_report = report
        self.window._populate_report(report)
        self.assertIsNone(self.window.session_comparison)
        self.assertFalse(self.window.session_compare_button.isEnabled())
        self.assertNotIn("S01", self.window.session_comparison_details.toPlainText())
        with patch.object(self.window, "_error") as error, patch("gui.lab_dashboard.QInputDialog.getInt") as picker:
            self.window.compare_local_sessions()
            error.assert_called_once()
            picker.assert_not_called()

    def test_pre_run_plan_records_selected_metric_without_echoing_token(self):
        self.window.replication_hypothesis.setText("non-identifying-plan")
        self.window.replication_independent.setChecked(True)
        self.window.primary_metric_combo.setCurrentText("fft_peak_prominence")
        with patch("gui.lab_dashboard.app_api.record_replication_plan") as record:
            self.window.record_session_plan()
            self.assertEqual(record.call_args.args[1], "non-identifying-plan")
            self.assertEqual(record.call_args.args[-1], "fft_peak_prominence")
        self.assertEqual(self.window.replication_hypothesis.text(), "")
        self.assertNotIn("non-identifying-plan", self.window.status.currentMessage())
        self.assertIsNone(self.window._capture_metadata()["acquisition_source_sha256"])

    def test_opening_another_experiment_discards_previous_summary_and_privacy_choice(self):
        self.window._session_comparison_ready(self.summary, self.directories)
        self.window.session_privacy.setChecked(True)
        other = self.root / "new-experiment"
        self.window.experiment_path.setText(str(other))
        with patch("laserlab.preferences.preferences_path", return_value=self.root / "preferences.json"):
            self.window.open_experiment()
        self.assertEqual(self.window.experiment_dir, other)
        self.assertIsNone(self.window.session_comparison)
        self.assertFalse(self.window.session_privacy.isChecked())
        self.assertFalse(self.window.session_export_button.isEnabled())
        self.assertNotIn("S01", self.window.session_comparison_details.toPlainText())


if __name__ == "__main__":
    unittest.main()
