"""GUI smoke tests for beginner-friendly LaserLab onboarding (offline)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QFileDialog, QLabel

from gui.lab_dashboard import LabDashboardWindow


class BeginnerOnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = LabDashboardWindow(
            preferences={
                "schema_version": 1,
                "recent_experiments": [],
                "last_source_directory": None,
            }
        )

    def tearDown(self) -> None:
        self.window.close()

    def test_first_run_explains_controls_and_demo_limits(self) -> None:
        texts = " ".join(label.text() for label in self.window.findChildren(QLabel))
        self.assertIn("First time?", texts)
        self.assertIn("matched comparison", texts.lower())
        self.assertIn("not a matched", texts.lower())
        self.assertEqual(self.window.home_demo_button.text(), "Run bundled demo")
        self.assertEqual(self.window.home_walkthrough_button.text(), "How it works")

    def test_starting_with_own_footage_opens_experiment_then_picker(self) -> None:
        with patch.object(self.window, "open_experiment") as open_project, patch.object(
            self.window, "browse_source"
        ) as browse:
            open_project.side_effect = lambda: setattr(self.window, "experiment_dir", Path("test"))
            self.window.analyze_my_footage()
            open_project.assert_called_once()
            browse.assert_called_once()
            self.assertEqual(self.window.setup_steps.currentIndex(), 1)

    def test_failed_experiment_does_not_launch_file_picker(self) -> None:
        with patch.object(self.window, "open_experiment") as open_project, patch.object(
            self.window, "browse_source"
        ) as browse:
            self.window.analyze_my_footage()
            open_project.assert_called_once()
            browse.assert_not_called()
            self.assertEqual(self.window.setup_steps.currentIndex(), 0)

    def test_cancel_open_existing_does_not_create_experiment(self) -> None:
        with patch.object(QFileDialog, "getExistingDirectory", return_value=""), patch.object(
            self.window, "open_experiment"
        ) as open_project:
            self.window.open_existing_experiment()
            open_project.assert_not_called()

    def test_recording_roles_are_friendly_but_api_codes_stay_unchanged(self) -> None:
        roles = {
            self.window.label_combo.itemText(i): self.window.label_combo.itemData(i)
            for i in range(self.window.label_combo.count())
        }
        self.assertEqual(roles["Laser recording"], "laser")
        self.assertEqual(roles["Matched comparison (same setup)"], "matched_control")

    def test_laser_capture_prompts_for_matched_control(self) -> None:
        self.window.label_combo.setCurrentIndex(self.window.label_combo.findData("laser"))
        with patch.object(self.window, "update_estimate"):
            self.window._capture_added({"captures": [{"label": "laser"}]})
        self.assertEqual(self.window.label_combo.currentData(), "matched_control")
        self.assertIn("matched comparison", self.window.status.currentMessage().lower())

    def test_demo_and_own_experiment_use_distinct_folders(self) -> None:
        own = Path(self.window.experiment_path.text())
        demo = Path(self.window.demo_experiment_path.text())
        self.assertEqual(own.name, "my-first-experiment")
        self.assertEqual(demo.name, "bundled-demo")
        self.assertNotEqual(own, demo)


if __name__ == "__main__":
    unittest.main()
