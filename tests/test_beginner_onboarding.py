"""GUI smoke tests for beginner-friendly LaserLab onboarding (offline)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QFileDialog, QLabel, QMessageBox

from gui.lab_dashboard import LabDashboardWindow
from laserlab import app_api
from laserlab.manifest import load_manifest, write_manifest


class BeginnerOnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        defaults = patch("gui.lab_dashboard.default_experiments_dir", return_value=self.root)
        defaults.start()
        self.addCleanup(defaults.stop)
        preferences = patch("laserlab.preferences.preferences_path", return_value=self.root / "preferences.json")
        preferences.start()
        self.addCleanup(preferences.stop)
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
        with patch.object(self.window, "browse_source") as browse:
            self.window.analyze_my_footage()
            browse.assert_called_once()
            self.assertEqual(self.window.setup_steps.currentIndex(), 1)
            self.assertTrue((self.window.experiment_dir / "manifest.json").exists())
            self.assertFalse(self.window.is_demo_experiment)

    def test_failed_experiment_does_not_launch_file_picker(self) -> None:
        with patch.object(self.window, "open_experiment", return_value=False) as open_project, patch.object(
            self.window, "browse_source"
        ) as browse:
            self.window.analyze_my_footage()
            open_project.assert_called_once()
            browse.assert_not_called()
            self.assertEqual(self.window.setup_steps.currentIndex(), 0)

    def test_cancel_open_existing_does_not_create_experiment(self) -> None:
        self.window.tabs.setCurrentIndex(4)
        with patch.object(QFileDialog, "getExistingDirectory", return_value=""), patch.object(
            self.window, "open_experiment"
        ) as open_project:
            self.window.open_existing_experiment()
            open_project.assert_not_called()
        self.assertEqual(self.window.tabs.currentIndex(), 4)

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

    def test_implicit_open_during_add_capture_keeps_selected_file_and_role(self) -> None:
        """Selecting a recording before opening an experiment must not erase it."""
        video = self.root / "my-video.mp4"
        self.window.source_path.setText(str(video))
        self.window.label_combo.setCurrentIndex(self.window.label_combo.findData("matched_control"))
        with patch("gui.lab_dashboard.app_api.add_capture", return_value={"captures": []}) as add, patch.object(
            self.window, "_run_worker", side_effect=lambda _title, task, _done: task()
        ) as worker, patch.object(self.window, "_error") as error:
            self.window.add_capture()
        error.assert_not_called()
        worker.assert_called_once()
        self.assertTrue((self.window.experiment_dir / "manifest.json").exists())
        self.assertEqual(add.call_args.kwargs["source"], video)
        self.assertEqual(add.call_args.kwargs["label"], "matched_control")
        self.assertEqual(self.window.source_path.text(), str(video))
        self.assertEqual(self.window.label_combo.currentData(), "matched_control")

    def test_empty_source_does_not_implicitly_create_experiment(self) -> None:
        self.assertFalse((self.root / "my-first-experiment").exists())
        with patch.object(self.window, "_error") as error, patch.object(
            self.window, "_run_worker"
        ) as worker:
            self.window.add_capture()
        error.assert_called_once()
        worker.assert_not_called()
        self.assertIsNone(self.window.experiment_dir)
        self.assertFalse((self.root / "my-first-experiment").exists())

    def test_explicit_switch_resets_pending_capture_selection(self) -> None:
        self.window.source_path.setText("old-capture.mp4")
        self.window.label_combo.setCurrentIndex(self.window.label_combo.findData("control"))
        self.window.experiment_path.setText(str(self.root / "fresh-project"))
        self.assertTrue(self.window.open_experiment())
        self.assertEqual(self.window.source_path.text(), "")
        self.assertEqual(self.window.label_combo.currentData(), "laser")

    def test_implicit_capture_cannot_write_to_practice_demo(self) -> None:
        demo = self.root / "existing-demo"
        manifest = app_api.create_experiment(demo)
        manifest["experiment_purpose"] = "demo"
        write_manifest(demo, manifest)
        before = (demo / "manifest.json").read_bytes()
        self.window.experiment_path.setText(str(demo))
        self.window.source_path.setText("private-video.mp4")
        self.window.label_combo.setCurrentIndex(self.window.label_combo.findData("matched_control"))
        with patch.object(self.window, "_error") as error, patch.object(
            self.window, "_run_worker"
        ) as worker:
            self.window.add_capture()
        error.assert_called_once()
        self.assertIn("practice demo", error.call_args.args[0].lower())
        worker.assert_not_called()
        self.assertIsNone(self.window.experiment_dir)
        self.assertEqual(self.window.source_path.text(), "private-video.mp4")
        self.assertEqual(self.window.label_combo.currentData(), "matched_control")
        self.assertEqual((demo / "manifest.json").read_bytes(), before)

    def test_active_practice_demo_rejects_new_personal_capture(self) -> None:
        self._open_demo()
        self.window.source_path.setText("private-video.mp4")
        with patch.object(self.window, "_error") as error, patch.object(
            self.window, "_run_worker"
        ) as worker:
            self.window.add_capture()
        error.assert_called_once()
        self.assertIn("practice demo", error.call_args.args[0].lower())
        worker.assert_not_called()

    def _open_demo(self) -> Path:
        demo = self.root / "saved-demo"
        manifest = app_api.create_experiment(demo)
        manifest["experiment_purpose"] = "demo"
        write_manifest(demo, manifest)
        self.window.experiment_path.setText(str(demo))
        self.assertTrue(self.window.open_experiment())
        return demo

    def test_demo_to_personal_experiment_preserves_demo_and_clears_review(self) -> None:
        demo = self._open_demo()
        before = (demo / "manifest.json").read_bytes()
        self.window.latest_report = {"run_id": "old-demo"}
        personal = self.root / "my-recording"
        with patch.object(QFileDialog, "getExistingDirectory", return_value=str(personal)), patch.object(
            self.window, "browse_source"
        ) as browse:
            self.window.analyze_my_footage()
        self.assertEqual(self.window.experiment_dir, personal)
        self.assertFalse(self.window.is_demo_experiment)
        self.assertIsNone(self.window.latest_report)
        self.assertTrue(self.window.demo_banner.isHidden())
        self.assertEqual((demo / "manifest.json").read_bytes(), before)
        self.assertEqual(load_manifest(personal)["captures"], [])
        browse.assert_called_once()

    def test_cancel_demo_to_personal_preserves_all_context(self) -> None:
        demo = self._open_demo()
        with patch.object(QFileDialog, "getExistingDirectory", return_value=""), patch.object(
            self.window, "browse_source"
        ) as browse:
            self.window.analyze_my_footage()
        self.assertEqual(self.window.experiment_dir, demo)
        self.assertEqual(self.window.experiment_path.text(), str(demo))
        self.assertTrue(self.window.is_demo_experiment)
        browse.assert_not_called()
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["preferences.json", "saved-demo"])

    def test_selecting_demo_for_personal_footage_is_rejected(self) -> None:
        demo = self._open_demo()
        before = (demo / "manifest.json").read_bytes()
        with patch.object(QFileDialog, "getExistingDirectory", return_value=str(demo)), patch.object(
            self.window, "browse_source"
        ) as browse, patch.object(QMessageBox, "warning") as warning:
            self.window.analyze_my_footage()
        warning.assert_called_once()
        browse.assert_not_called()
        self.assertEqual((demo / "manifest.json").read_bytes(), before)
        self.assertEqual(self.window.experiment_dir, demo)

    def test_failed_personal_open_keeps_demo_and_does_not_select_media(self) -> None:
        demo = self._open_demo()
        with patch.object(QFileDialog, "getExistingDirectory", return_value=str(self.root / "personal")), patch(
            "gui.lab_dashboard.app_api.create_experiment", side_effect=OSError("Folder is read-only")
        ), patch.object(self.window, "browse_source") as browse, patch.object(QMessageBox, "warning"):
            self.window.analyze_my_footage()
        self.assertEqual(self.window.experiment_dir, demo)
        self.assertEqual(self.window.experiment_path.text(), str(demo))
        self.assertTrue(self.window.is_demo_experiment)
        browse.assert_not_called()

    def test_returning_user_opens_persisted_demo_as_practice(self) -> None:
        demo = self._open_demo()
        self.window.is_demo_experiment = False
        self.window._open_recent_experiment(demo)
        self.assertTrue(self.window.is_demo_experiment)
        self.assertFalse(self.window.demo_banner.isHidden())

    def test_cancel_source_picker_does_not_change_existing_selection(self) -> None:
        self.window.source_path.setText("original.mp4")
        with patch.object(QFileDialog, "getOpenFileName", return_value=("", "")):
            self.window.browse_source()
        self.assertEqual(self.window.source_path.text(), "original.mp4")

    def test_capture_passes_canonical_role_to_api(self) -> None:
        self.window.experiment_path.setText(str(self.root / "personal"))
        self.assertTrue(self.window.open_experiment())
        self.window.source_path.setText("recording.mp4")
        for role in ("laser", "matched_control", "control", "sensor_noise", "synthetic_positive", "synthetic_negative"):
            self.window.label_combo.setCurrentIndex(self.window.label_combo.findData(role))
            with patch("gui.lab_dashboard.app_api.add_capture", return_value={}) as add, patch.object(
                self.window, "_run_worker", side_effect=lambda _label, task, _done: task()
            ):
                self.window.add_capture()
            self.assertEqual(add.call_args.kwargs["label"], role)

    def test_running_demo_does_not_switch_active_experiment_early(self) -> None:
        personal = self.root / "personal"
        self.window.experiment_dir = personal
        self.window.experiment_path.setText(str(personal))
        with patch.object(self.window, "_run_worker") as worker:
            self.window.run_fixture_demo()
        worker.assert_called_once()
        self.assertEqual(self.window.experiment_dir, personal)
        self.assertEqual(self.window.experiment_path.text(), str(personal))

    def test_walkthrough_is_optional_and_revisitable(self) -> None:
        with patch.object(QMessageBox, "information") as information:
            self.window.home_walkthrough_button.click()
        information.assert_called_once()
        self.assertIn("NOT matched scientific controls", information.call_args.args[2])

    def test_support_link_opens_only_fixed_url_without_experiment_data(self) -> None:
        from gui.lab_dashboard import ISSUE_FORMS_PAGE
        with patch("gui.lab_dashboard.QDesktopServices.openUrl", return_value=True) as open_url:
            self.window.open_support_page(ISSUE_FORMS_PAGE)
            self.window.open_support_page("https://example.com/private")
        open_url.assert_called_once()
        self.assertEqual(open_url.call_args.args[0].toString(), ISSUE_FORMS_PAGE)


if __name__ == "__main__":
    unittest.main()
