"""Real Qt lifecycle checks around Pair Quality and exploratory continuation."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMessageBox

from gui.lab_dashboard import LabDashboardWindow
from laserlab.stats import summarize_blinded_results


def assessment(*, exploratory=True):
    return {"version": "pair-quality-v1", "status": "unknown" if exploratory else "consistent",
            "summary": "Comparison details are missing." if exploratory else "Declared details agree.",
            "requires_exploratory": exploratory, "checks": [], "pairs": [], "limitations": []}


def choose_button(text):
    """Exercise the real button signal without starting a blocking modal loop."""
    def execute(box):
        button = next(button for button in box.buttons() if button.text() == text)
        button.click()
        return 0
    return execute


class PairQualityGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.window = LabDashboardWindow(preferences={"schema_version": 1,
            "recent_experiments": [], "last_source_directory": None})
        self.window.experiment_dir = self.root / "experiment"
        self.errors = patch.object(self.window, "_error")
        self.error = self.errors.start()
        self.addCleanup(self.errors.stop)

    def tearDown(self):
        worker = self.window.worker
        if worker is not None:
            worker.wait(5000)
            self.application.processEvents()
        self.window.close()
        self.application.processEvents()

    def wait_until(self, condition):
        deadline = time.monotonic() + 5
        while not condition():
            self.application.processEvents()
            if time.monotonic() > deadline:
                self.fail("Timed out waiting for the GUI worker transition.")
            time.sleep(.002)
        self.application.processEvents()

    def test_unknown_yes_and_no_capture_facts_remain_distinct(self):
        fields = (("camera_fixed", self.window.camera_fixed_check),
                  ("beam_path_fixed", self.window.beam_fixed_check),
                  ("non_reflective_surface", self.window.non_reflective_check),
                  ("projected_region_not_saturated", self.window.not_saturated_check))
        for key, widget in fields:
            with self.subTest(field=key):
                self.assertEqual(widget.checkState(), Qt.PartiallyChecked)
                self.assertIsNone(self.window._capture_metadata()[key])
                widget.setCheckState(Qt.Checked)
                self.assertIs(self.window._capture_metadata()[key], True)
                widget.setCheckState(Qt.Unchecked)
                self.assertIs(self.window._capture_metadata()[key], False)
                widget.setCheckState(Qt.PartiallyChecked)
        self.assertIsNone(self.window._capture_metadata()["camera"])
        self.window.camera_description.setText("  manually recorded camera  ")
        self.assertEqual(self.window._capture_metadata()["camera"], "manually recorded camera")

    def test_busy_controls_and_direct_context_switches_are_blocked(self):
        active = self.window.experiment_dir
        self.window._set_busy(True)
        for widget in (self.window.setup_steps, self.window.recent_menu,
                       self.window.home_analyze_button, self.window.home_open_button,
                       self.window.profile_combo, self.window.blind_seed,
                       self.window.pair_quality_button, self.window.run_button):
            self.assertFalse(widget.isEnabled())
        with patch("gui.lab_dashboard.app_api.create_experiment") as create:
            self.window.experiment_path.setText(str(self.root / "other"))
            self.window.open_experiment()
            self.window.run_fixture_demo()
            create.assert_not_called()
        self.assertEqual(self.window.experiment_dir, active)
        self.assertTrue(self.error.called)
        self.window._set_busy(False)
        self.assertTrue(self.window.setup_steps.isEnabled())
        self.assertTrue(self.window.pair_quality_button.isEnabled())

    def test_canceling_exploratory_choice_launches_no_analysis(self):
        with patch("gui.lab_dashboard.QMessageBox.exec_", new=choose_button("Cancel")), \
             patch.object(self.window, "_launch_analysis") as launch:
            self.window._pair_quality_ready(assessment(), self.window.experiment_dir, {"profile": "baseline"})
        launch.assert_not_called()
        self.assertIn("Comparison details are missing", self.window.pair_quality_details.toPlainText())
        self.assertIn("Proceed as exploratory", self.window.pair_quality_details.toPlainText())

    def test_explicit_proceed_uses_captured_options_and_stopped_threads(self):
        self.window.profile_combo.setCurrentText("baseline")
        self.window.blind_seed.setValue(73)
        expected_experiment = self.window.experiment_dir
        completed_running_states = []
        original_completed = self.window._worker_completed

        def observe_completed(worker, on_success):
            completed_running_states.append(worker.isRunning())
            original_completed(worker, on_success)

        with patch("gui.lab_dashboard.app_api.assess_pair_quality", return_value=assessment()), \
             patch("gui.lab_dashboard.app_api.run_analysis", return_value={"run_id": "accepted"}) as run, \
             patch.object(self.window, "_analysis_finished") as finished, \
             patch.object(self.window, "_worker_completed", side_effect=observe_completed), \
             patch("gui.lab_dashboard.QMessageBox.exec_", new=choose_button("Proceed as exploratory")):
            self.window.run_analysis()
            self.assertTrue(self.window._busy)
            # Programmatic changes still cannot change the options captured at Run.
            self.window.profile_combo.setCurrentText("wide")
            self.window.blind_seed.setValue(99)
            self.wait_until(lambda: finished.called and self.window.worker is None)
        self.assertEqual(run.call_args.kwargs["experiment_dir"], expected_experiment)
        self.assertEqual(run.call_args.kwargs["profile"], "baseline")
        self.assertEqual(run.call_args.kwargs["blind_seed"], 73)
        self.assertEqual(completed_running_states, [False, False])
        self.assertFalse(self.window._busy)
        self.assertIn("sealed", self.window.pair_quality_details.toPlainText())
        self.error.assert_not_called()

    def test_failed_preflight_recovers_controls_and_can_retry(self):
        with self.assertLogs("laserlab.gui", level="ERROR") as logs, \
             patch("gui.lab_dashboard.app_api.assess_pair_quality", side_effect=RuntimeError("inspection failed")), \
             patch("gui.lab_dashboard.app_api.run_analysis") as run:
            self.window.run_analysis()
            self.wait_until(lambda: self.window.worker is None)
        run.assert_not_called()
        self.assertFalse(self.window._busy)
        self.assertTrue(self.window.run_button.isEnabled())
        self.assertTrue(self.window.pair_quality_button.isEnabled())
        self.assertTrue(self.window.setup_steps.isEnabled())
        self.assertIn("inspection failed", self.window.run_log.toPlainText())
        self.error.assert_called_once_with("inspection failed")
        self.assertIn("inspection failed", "\n".join(logs.output))
        with patch("gui.lab_dashboard.app_api.assess_pair_quality", return_value=assessment(exploratory=False)), \
             patch("gui.lab_dashboard.app_api.run_analysis", return_value={"run_id": "retry"}) as run, \
             patch.object(self.window, "_analysis_finished") as finished:
            self.window.run_analysis()
            self.wait_until(lambda: finished.called and self.window.worker is None)
        run.assert_called_once()

    def test_stale_preflight_context_cannot_launch_or_show_old_pair_details(self):
        old = self.window.experiment_dir
        self.window.experiment_dir = self.root / "different"
        self.window.pair_quality_details.setPlainText("New experiment instructions")
        with patch.object(self.window, "_launch_analysis") as launch:
            self.window._pair_quality_ready(assessment(), old, {"profile": "baseline"})
        launch.assert_not_called()
        self.assertEqual(self.window.pair_quality_details.toPlainText(), "New experiment instructions")
        self.error.assert_called_once()

    def test_blinded_report_clears_role_specific_quality_widgets(self):
        self.window.pair_quality_details.setPlainText("PRIVATE control geometry and laser mismatch")
        self.window.quality_checklist.setPlainText("PRIVATE proposed control quality")
        report = {"review_state": {"unblinded": False}, "review_session": {"complete": False},
                  "aggregate_statistics": summarize_blinded_results([]), "summary": {},
                  "top_candidates": [], "interpretation": {}}
        self.window._populate_report(report)
        self.assertNotIn("PRIVATE", self.window.pair_quality_details.toPlainText())
        self.assertNotIn("PRIVATE", self.window.quality_checklist.toPlainText())
        self.assertIn("sealed", self.window.pair_quality_details.toPlainText())
        self.assertFalse(self.window.tabs.isTabVisible(0))
        self.assertFalse(self.window.tabs.isTabVisible(1))

    def test_task_completion_preserves_explicit_review_completion_gate(self):
        self.window.latest_report = {"review_state": {"unblinded": False}, "review_session": {"complete": False}}
        self.window._set_busy(True)
        self.assertFalse(self.window.unblind_button.isEnabled())
        self.assertFalse(self.window.complete_review_button.isEnabled())
        self.window._set_busy(False)
        self.assertFalse(self.window.unblind_button.isEnabled())
        self.assertTrue(self.window.complete_review_button.isEnabled())
        self.window.latest_report["review_session"]["complete"] = True
        self.window._set_busy(True)
        self.window._set_busy(False)
        self.assertTrue(self.window.unblind_button.isEnabled())
        self.assertFalse(self.window.complete_review_button.isEnabled())
        self.window.latest_report["review_state"]["unblinded"] = True
        self.window._set_busy(True)
        self.window._set_busy(False)
        self.assertFalse(self.window.unblind_button.isEnabled())

    def test_unknown_physical_settings_are_not_filled_with_presets(self):
        metadata = self.window._capture_metadata()
        self.assertIsNone(metadata["wavelength_nm"])
        self.assertEqual(metadata["projection_surface_type"], "unknown")
        self.assertEqual(metadata["laser_pattern_type"], "unknown")
        self.assertEqual(metadata["mount_type"], "unknown")


if __name__ == "__main__":
    unittest.main()
