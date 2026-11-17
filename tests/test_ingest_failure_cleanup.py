"""Regression coverage for interrupted and failed media imports.

These tests use synthetic files only and never access real volunteer footage.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from laserlab.ingest import init_experiment
from laserlab.manifest import load_manifest, load_or_create_manifest


class FailedCaptureCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "private-source"
        self.source.mkdir()
        (self.source / "picture.png").write_bytes(b"synthetic-fixture")
        self.experiment = self.root / "experiment"
        load_or_create_manifest(self.experiment)
        self.frames = self.experiment / "frames"
        self.original_manifest = (self.experiment / "manifest.json").read_bytes()

    def _add(self, kind: str = "image-set") -> dict:
        return init_experiment(self.source, kind, "laser", self.experiment)

    def _unchanged(self) -> None:
        self.assertEqual(
            (self.experiment / "manifest.json").read_bytes(),
            self.original_manifest,
        )
        self.assertEqual((self.source / "picture.png").read_bytes(), b"synthetic-fixture")

    def test_partial_image_import_raises_and_removes_only_new_capture(self) -> None:
        older_capture = self.frames / "cap-existing"
        older_capture.mkdir(parents=True)
        (older_capture / "keep.png").write_bytes(b"previous research")

        def fail_after_one_frame(*, capture_dir: Path, **_kwargs: object) -> None:
            (capture_dir / "frame_000000.png").write_bytes(b"partial-frame")
            raise OSError("simulated storage failure")

        with (
            patch("laserlab.ingest.inspect_source", return_value={}),
            patch("laserlab.ingest._ingest_image_set", side_effect=fail_after_one_frame),
        ):
            with self.assertRaisesRegex(OSError, "storage failure"):
                self._add()

        self._unchanged()
        self.assertEqual(sorted(path.name for path in self.frames.iterdir()), ["cap-existing"])
        self.assertEqual((older_capture / "keep.png").read_bytes(), b"previous research")

    def test_no_decodable_frames_leave_no_empty_capture(self) -> None:
        with (
            patch("laserlab.ingest.inspect_source", return_value={}),
            patch("laserlab.ingest._ingest_image_set", return_value=([], "hash", {})),
        ):
            with self.assertRaisesRegex(ValueError, "No frames"):
                self._add()

        self._unchanged()
        self.assertEqual(list(self.frames.iterdir()), [])

    def test_failed_video_decoder_does_not_leave_partial_frames(self) -> None:
        def fail_decoder(*, capture_dir: Path, **_kwargs: object) -> None:
            (capture_dir / "frame_000000.png").write_bytes(b"partial-video-frame")
            raise RuntimeError("unsupported codec")

        with (
            patch("laserlab.ingest.inspect_source", return_value={}),
            patch("laserlab.ingest._ingest_video", side_effect=fail_decoder),
        ):
            with self.assertRaisesRegex(RuntimeError, "unsupported codec"):
                self._add("video")

        self._unchanged()
        self.assertEqual(list(self.frames.iterdir()), [])

    def test_failed_metadata_probe_cleans_empty_capture(self) -> None:
        with patch("laserlab.ingest.inspect_source", side_effect=OSError("could not inspect")):
            with self.assertRaisesRegex(OSError, "could not inspect"):
                self._add()

        self._unchanged()
        self.assertEqual(list(self.frames.iterdir()), [])

    def test_manifest_save_error_cleans_new_frames(self) -> None:
        def ingest_one(*, capture_dir: Path, capture_id: str, **_kwargs: object) -> tuple:
            (capture_dir / "frame_000000.png").write_bytes(b"synthetic-frame")
            return (
                [{"frame_id": capture_id + "-frame-000000",
                  "path": "frames/" + capture_id + "/frame_000000.png"}],
                "hash",
                {"selected_frames": 1},
            )

        with (
            patch("laserlab.ingest.inspect_source", return_value={}),
            patch("laserlab.ingest._ingest_image_set", side_effect=ingest_one),
            patch("laserlab.ingest.write_manifest", side_effect=OSError("manifest save failed")),
        ):
            with self.assertRaisesRegex(OSError, "manifest save failed"):
                self._add()

        self._unchanged()
        self.assertEqual(list(self.frames.iterdir()), [])

    def test_successful_image_import_keeps_registered_frames(self) -> None:
        def ingest_one(*, capture_dir: Path, capture_id: str, **_kwargs: object) -> tuple:
            frame = capture_dir / "frame_000000.png"
            frame.write_bytes(b"synthetic-frame")
            return (
                [{"frame_id": capture_id + "-frame-000000",
                  "path": "frames/" + capture_id + "/frame_000000.png"}],
                "hash",
                {"selected_frames": 1},
            )

        with (
            patch("laserlab.ingest.inspect_source", return_value={}),
            patch("laserlab.ingest._ingest_image_set", side_effect=ingest_one),
        ):
            manifest = self._add()

        self.assertEqual(len(manifest["captures"]), 1)
        saved = manifest["captures"][0]["frames"][0]["path"]
        self.assertEqual((self.experiment / saved).read_bytes(), b"synthetic-frame")
        self.assertEqual(load_manifest(self.experiment)["captures"][0]["frames"][0]["path"], saved)

    def test_symlinked_frames_folder_cannot_escape_experiment(self) -> None:
        outside = self.root / "external-footage"
        outside.mkdir()
        (outside / "keep.png").write_bytes(b"external source")
        try:
            self.frames.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symlinks unavailable: {exc}")

        with self.assertRaisesRegex(ValueError, "inside the experiment"):
            self._add()

        self._unchanged()
        self.assertEqual((outside / "keep.png").read_bytes(), b"external source")
        self.assertEqual(list(outside.iterdir()), [outside / "keep.png"])

    def test_existing_directory_collision_is_never_deleted(self) -> None:
        class FixedUUID:
            hex = "abcd012345" + "0" * 22

        existing = self.frames / "cap-abcd012345"
        existing.mkdir(parents=True)
        (existing / "keep.png").write_bytes(b"saved footage")
        with patch("laserlab.ingest.uuid.uuid4", return_value=FixedUUID()):
            with self.assertRaises(FileExistsError):
                self._add()

        self._unchanged()
        self.assertEqual((existing / "keep.png").read_bytes(), b"saved footage")
        self.assertEqual(load_manifest(self.experiment)["captures"], [])


if __name__ == "__main__":
    unittest.main()
