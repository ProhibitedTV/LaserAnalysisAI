"""Saved review previews must not open unrelated images or reveal sealed source frames."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication

from gui.lab_dashboard import LabDashboardWindow
from laserlab.artifacts import write_json


class ReviewPreviewConfinementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.experiment = self.root / "experiment"
        self.run = self.experiment / "runs" / "run-001"
        self.run.mkdir(parents=True)
        write_json(self.experiment / "manifest.json", {"outputs": {"latest_run": "runs/run-001"}})
        self.image = self.run / "review_originals" / "candidate.png"
        self.outside = self.root / "private.png"
        self.other_run = self.experiment / "runs" / "run-002" / "candidate.png"
        self.frame = self.experiment / "frames" / "cap-001" / "frame.png"
        for path in (self.image, self.outside, self.other_run, self.frame):
            path.parent.mkdir(parents=True, exist_ok=True)
            image = QImage(16, 16, QImage.Format_RGB32)
            image.fill(0x336699)
            self.assertTrue(image.save(str(path)))
        self.window = LabDashboardWindow(preferences={})
        self.addCleanup(self.window.close)
        self.window.experiment_dir = self.experiment
        self.window.latest_report = {"run_id": "run-001", "review_state": {"unblinded": False}}

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.experiment).as_posix()

    def _assert_empty(self) -> None:
        for label in (self.window.original_preview, self.window.processed_preview, self.window.crop_preview):
            self.assertTrue(label.pixmap() is None or label.pixmap().isNull())

    def test_preview_paths_cannot_escape_selected_run(self) -> None:
        invalid = [str(self.outside), "../private.png", self._relative(self.other_run),
                   self._relative(self.frame), "manifest.json"]
        for stored in invalid:
            for field in ("review_image_path", "processed_path", "roi_overlay_path", "crop_path", "processed_crop_path"):
                with self.subTest(stored=stored, field=field):
                    candidate = {field: stored} if "crop" not in field else {"candidate_rois": [{field: stored}]}
                    self.window.show_processed_overlay.setChecked(field != "processed_path")
                    with patch("gui.lab_dashboard.QPixmap", side_effect=AssertionError("Unsafe image must not be opened")):
                        self.window._load_candidate_images(candidate)
                    self._assert_empty()

    def test_valid_run_images_render_and_unsafe_selection_clears_previous_previews(self) -> None:
        stored = self._relative(self.image)
        self.window._load_candidate_images({"review_image_path": stored, "roi_overlay_path": stored,
                                            "candidate_rois": [{"processed_crop_path": stored}]})
        for label in (self.window.original_preview, self.window.processed_preview, self.window.crop_preview):
            self.assertIsNotNone(label.pixmap())
            self.assertFalse(label.pixmap().isNull())
        with patch("gui.lab_dashboard.QPixmap", side_effect=AssertionError("Unsafe image must not be opened")):
            self.window._load_candidate_images({"review_image_path": str(self.outside)})
        self._assert_empty()

    def test_legacy_source_frame_fallback_requires_unblinding(self) -> None:
        candidate = {"source_path": self._relative(self.frame)}
        with patch("gui.lab_dashboard.QPixmap", side_effect=AssertionError("Raw frame must remain sealed")):
            self.window._load_candidate_images(candidate)
        self._assert_empty()
        self.window.latest_report["review_state"]["unblinded"] = True
        self.window._load_candidate_images(candidate)
        self.assertFalse(self.window.original_preview.pixmap().isNull())
        with patch("gui.lab_dashboard.QPixmap", side_effect=AssertionError("External legacy image must not be opened")):
            self.window._load_candidate_images({"source_path": str(self.outside)})
        self._assert_empty()
        write_json(self.experiment / "manifest.json", {
            "outputs": {"latest_run": "runs/run-001", "review_state": "blinded"}
        })
        with patch("gui.lab_dashboard.QPixmap", side_effect=AssertionError("Manifest still seals the raw frame")):
            self.window._load_candidate_images(candidate)
        self._assert_empty()

    def test_changed_or_missing_run_selection_does_not_open_images(self) -> None:
        for manifest in ({"outputs": {"latest_run": "runs/run-002"}}, {"outputs": {}}):
            with self.subTest(manifest=manifest):
                write_json(self.experiment / "manifest.json", manifest)
                with patch("gui.lab_dashboard.QPixmap", side_effect=AssertionError("Stale review must not open images")):
                    self.window._load_candidate_images({"review_image_path": self._relative(self.image)})
                self._assert_empty()

    def test_symlinked_preview_and_imported_frame_cannot_escape_experiment(self) -> None:
        linked = self.run / "linked.png"
        try:
            linked.symlink_to(self.outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symlinks unavailable on this runner: {exc}")
        with patch("gui.lab_dashboard.QPixmap", side_effect=AssertionError("External symlink must not be read")):
            self.window._load_candidate_images({"review_image_path": self._relative(linked)})
        self._assert_empty()
        frame_link = self.experiment / "frames" / "private.png"
        frame_link.symlink_to(self.outside)
        self.window.latest_report["review_state"]["unblinded"] = True
        with patch("gui.lab_dashboard.QPixmap", side_effect=AssertionError("External frame symlink must not be read")):
            self.window._load_candidate_images({"source_path": self._relative(frame_link)})
        self._assert_empty()

    def test_missing_or_malformed_manifest_disables_previews_without_changing_files(self) -> None:
        manifest = self.experiment / "manifest.json"
        for content in (None, b"{", b"[]", b'{"outputs": []}'):
            with self.subTest(content=content):
                if content is None:
                    manifest.unlink()
                else:
                    manifest.write_bytes(content)
                with patch("gui.lab_dashboard.QPixmap", side_effect=AssertionError("No valid run selection")):
                    self.window._load_candidate_images({"review_image_path": self._relative(self.image)})
                self._assert_empty()
                if content is None:
                    self.assertFalse(manifest.exists())
                else:
                    self.assertEqual(manifest.read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
