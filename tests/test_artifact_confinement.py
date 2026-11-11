"""Saved run and review-image pointers must not escape a LaserLab experiment."""
from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from laserlab.bundle import export_review_bundle
from laserlab.manifest import latest_run_dir


class ArtifactConfinementTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.experiment = self.base / "experiment"
        self.run = self.experiment / "runs" / "run-001"
        self.run.mkdir(parents=True)
        self.image = self.run / "review_originals" / "candidate.png"
        self.image.parent.mkdir()
        self.image.write_bytes(b"test-image-content")
        self.manifest = {"schema_version": 1, "outputs": {"latest_run": "runs/run-001"}}
        self.report = {
            "run_id": "run-001",
            "top_candidates": [
                {"review_image_path": self.image.relative_to(self.experiment).as_posix(), "candidate_rois": []}
            ],
        }

    def _export(self, output: Path | None = None) -> Path:
        target = output or self.base / "review.zip"
        with (
            patch("laserlab.bundle.load_manifest", return_value=self.manifest),
            patch("laserlab.bundle.load_json", return_value={}),
            patch("laserlab.bundle.current_statistics", return_value={}),
            patch("laserlab.bundle.build_report", return_value=self.report),
            patch("laserlab.bundle.is_unblinded", return_value=False),
            patch("laserlab.bundle.render_html_report", return_value="<html></html>"),
        ):
            return export_review_bundle(self.experiment, target)

    def test_valid_run_pointer_and_review_image_still_export(self) -> None:
        self.assertEqual(latest_run_dir(self.experiment, self.manifest), self.run)
        exported = self._export()
        with zipfile.ZipFile(exported) as archive:
            self.assertEqual(archive.read("top_originals/candidate.png"), b"test-image-content")
            self.assertIn("manifest.json", archive.namelist())
            self.assertFalse(any(name.startswith("media/") for name in archive.namelist()))

    def test_missing_optional_review_image_is_still_skipped(self) -> None:
        self.report["top_candidates"][0]["review_image_path"] = "runs/run-001/review_originals/missing.png"
        with zipfile.ZipFile(self._export()) as archive:
            self.assertFalse(any(name.startswith("top_originals/") for name in archive.namelist()))

    def test_invalid_latest_run_paths_are_rejected(self) -> None:
        invalid = [
            self.base.as_posix(),
            "../other",
            "runs/run-001/../../outside",
            "runs",
            "manifest.json",
            "runs/../runs/run-001",
            12,
            ["runs/run-001"],
        ]
        for stored in invalid:
            with self.subTest(stored=stored):
                with self.assertRaises(ValueError):
                    latest_run_dir(self.experiment, {"outputs": {"latest_run": stored}})
        with self.assertRaises(FileNotFoundError):
            latest_run_dir(self.experiment, {"outputs": {}})

    def test_invalid_image_paths_fail_before_overwriting_existing_archive(self) -> None:
        other_run = self.experiment / "runs" / "run-002"
        other_run.mkdir()
        (other_run / "candidate.png").write_bytes(b"other-run")
        outside = self.base / "private.png"
        outside.write_bytes(b"do not share")
        non_image = self.run / "notes.txt"
        non_image.write_text("private notes", encoding="utf-8")
        archive = self.base / "review.zip"
        archive.write_bytes(b"previous safe export")
        invalid = [
            str(outside),                            # absolute external path
            "../private.png",                       # parent traversal
            "runs/run-001/../../private.png",        # nested traversal
            "manifest.json",                        # inside experiment, outside run
            "runs/run-002/candidate.png",            # image from different run
            "runs/run-001/notes.txt",                # non-image artifact
            {"path": "runs/run-001/notes.txt"},      # invalid JSON type
        ]
        for stored in invalid:
            with self.subTest(stored=stored):
                self.report["top_candidates"][0]["review_image_path"] = stored
                with self.assertRaises(ValueError):
                    self._export(archive)
                self.assertEqual(archive.read_bytes(), b"previous safe export")

    def test_roi_paths_receive_the_same_confinement(self) -> None:
        self.report["top_candidates"][0]["candidate_rois"] = [
            {"crop_path": "../private.png", "processed_crop_path": None}
        ]
        with self.assertRaises(ValueError):
            self._export()
        self.assertFalse((self.base / "review.zip").exists())

    def test_symlinked_review_image_cannot_leave_selected_run(self) -> None:
        outside = self.base / "private.png"
        outside.write_bytes(b"do not share")
        link = self.image.parent / "linked.png"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symlinks unavailable on this test runner: {exc}")
        self.report["top_candidates"][0]["review_image_path"] = link.relative_to(self.experiment).as_posix()
        with self.assertRaises(ValueError):
            self._export()
        self.assertFalse((self.base / "review.zip").exists())

    def test_symlinked_run_directory_cannot_escape_experiment(self) -> None:
        outside = self.base / "outside-run"
        outside.mkdir()
        link = self.experiment / "runs" / "link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symlinks unavailable on this test runner: {exc}")
        with self.assertRaises(ValueError):
            latest_run_dir(self.experiment, {"outputs": {"latest_run": "runs/link"}})


if __name__ == "__main__":
    unittest.main()
