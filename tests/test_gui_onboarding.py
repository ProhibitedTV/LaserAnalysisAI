"""First-run dashboard behavior, tested without a visible display."""
from __future__ import annotations

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QLabel

from gui.lab_dashboard import LabDashboardWindow


class DashboardOnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = LabDashboardWindow()

    def tearDown(self) -> None:
        self.window.close()

    def test_first_run_starts_at_experiment_step(self) -> None:
        self.assertIsNone(self.window.experiment_dir)
        self.window.analyze_my_footage()
        self.assertEqual(self.window.tabs.currentIndex(), 0)
        self.assertEqual(self.window.setup_steps.currentIndex(), 0)
        self.assertIn("create or open", self.window.status.currentMessage().lower())

    def test_capture_labels_are_friendly_but_api_roles_stay_stable(self) -> None:
        roles = {
            self.window.label_combo.itemText(index): self.window.label_combo.itemData(index)
            for index in range(self.window.label_combo.count())
        }
        self.assertEqual(roles["Laser recording"], "laser")
        self.assertEqual(roles["Matched control (same setup)"], "matched_control")
        self.window.label_combo.setCurrentIndex(self.window.label_combo.findData("laser"))
        self.window._capture_added({"captures": []})
        self.assertEqual(self.window.label_combo.currentData(), "matched_control")

    def test_demo_does_not_share_default_real_experiment_path(self) -> None:
        user_path = Path(self.window.experiment_path.text())
        demo_path = Path(self.window.demo_experiment_path.text())
        self.assertNotEqual(user_path, demo_path)
        self.assertEqual(demo_path.name, "bundled-demo")

    def test_start_page_and_help_menu_offer_clear_guidance(self) -> None:
        text = " ".join(label.text() for label in self.window.findChildren(QLabel))
        self.assertIn("New here?", text)
        self.assertIn("matched control", text)
        menu_names = [action.text() for action in self.window.menuBar().actions()]
        self.assertIn("Help", menu_names)
        self.assertEqual(self.window.home_help_button.text(), "How it works")


if __name__ == "__main__":
    unittest.main()
