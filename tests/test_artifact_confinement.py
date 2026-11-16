"""Saved run and review-image pointers must not escape a LaserLab experiment."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from laserlab.bundle import export_review_bundle
from laserlab.blinding import UNBLIND_FILENAME, seal_manifest
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

    def test_missing_legacy_image_outside_run_is_skipped(self) -> None:
        self.report["top_candidates"][0]["review_image_path"] = "processed/missing-legacy.png"
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
        # The mocked manifest loader does not create this disk file.
        # Ensure the out-of-run filename actually exists when testing refusal.
        (self.experiment / "manifest.json").write_text("private metadata", encoding="utf-8")
        archive = self.base / "review.zip"
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
                archive.write_bytes(b"previous safe export")
                self.report["top_candidates"][0]["review_image_path"] = stored
                with self.assertRaises(ValueError):
                    self._export(archive)
                self.assertEqual(archive.read_bytes(), b"previous safe export")

    def test_failed_write_keeps_existing_export_and_cleans_staging(self) -> None:
        archive = self.base / "review.zip"
        archive.write_bytes(b"previous successful export")
        with patch("laserlab.bundle.zipfile.ZipFile.write", side_effect=OSError("simulated disk full")):
            with self.assertRaisesRegex(OSError, "simulated disk full"):
                self._export(archive)
        self.assertEqual(archive.read_bytes(), b"previous successful export")
        self.assertEqual(list(self.base.glob(".review.zip.*.tmp")), [])

    def test_failed_first_export_leaves_no_partial_zip(self) -> None:
        archive = self.base / "new-export.zip"
        with patch("laserlab.bundle.zipfile.ZipFile.write", side_effect=OSError("simulated disk full")):
            with self.assertRaisesRegex(OSError, "simulated disk full"):
                self._export(archive)
        self.assertFalse(archive.exists())
        self.assertEqual(list(self.base.glob(".new-export.zip.*.tmp")), [])

    def test_successful_export_replaces_archive_and_supports_experiment_exports_folder(self) -> None:
        archive = self.experiment / "exports" / "review.zip"
        archive.parent.mkdir()
        archive.write_bytes(b"older export")
        self._export(archive)
        with zipfile.ZipFile(archive) as result:
            self.assertEqual(result.read("top_originals/candidate.png"), b"test-image-content")
        self.assertEqual(list(archive.parent.glob(".review.zip.*.tmp")), [])

    def test_export_cannot_overwrite_manifest_or_run_artifacts(self) -> None:
        manifest_path = self.experiment / "manifest.json"
        results_path = self.run / "results.json"
        for protected in (manifest_path, results_path):
            with self.subTest(protected=protected):
                protected.write_bytes(b"essential experiment record")
                with self.assertRaisesRegex(ValueError, "destination"):
                    self._export(protected)
                self.assertEqual(protected.read_bytes(), b"essential experiment record")

    def test_export_cannot_overwrite_known_original_source(self) -> None:
        source = self.base / "laser-capture.zip"
        source.write_bytes(b"original raw media")
        self.manifest["sources"] = [{"path": str(source)}]
        with self.assertRaisesRegex(ValueError, "original capture source"):
            self._export(source)
        self.assertEqual(source.read_bytes(), b"original raw media")
        self.assertEqual(list(self.base.glob(".laser-capture.zip.*.tmp")), [])

    def test_export_cannot_overwrite_other_runs_or_imported_frames(self) -> None:
        protected_paths = (
            self.experiment / "runs" / "run-previous" / "results.json",
            self.experiment / "frames" / "cap-001" / "frame_000000.png",
        )
        for protected in protected_paths:
            with self.subTest(protected=protected):
                protected.parent.mkdir(parents=True)
                protected.write_bytes(b"saved research data")
                with self.assertRaisesRegex(ValueError, "destination"):
                    self._export(protected)
                self.assertEqual(protected.read_bytes(), b"saved research data")
                self.assertEqual(list(protected.parent.glob(f".{protected.name}.*.tmp")), [])

    def test_export_cannot_modify_original_image_set_directory(self) -> None:
        source = self.base / "original-images"
        source.mkdir()
        original = source / "frame.png"
        original.write_bytes(b"original image")
        self.manifest["sources"] = [{"path": str(source), "kind": "image-set"}]
        for destination in (original, source / "nested" / "review.zip"):
            with self.subTest(destination=destination):
                with self.assertRaisesRegex(ValueError, "original capture source"):
                    self._export(destination)
                self.assertEqual(original.read_bytes(), b"original image")
                self.assertFalse((source / "nested").exists())

    def test_failed_sync_or_replacement_keeps_previous_export_and_cleans_staging(self) -> None:
        archive = self.base / "review.zip"
        for operation in ("fsync", "replace"):
            with self.subTest(operation=operation):
                archive.write_bytes(b"previous successful export")
                with patch(f"laserlab.bundle.os.{operation}", side_effect=OSError("simulated finalization failure")):
                    with self.assertRaisesRegex(OSError, "simulated finalization failure"):
                        self._export(archive)
                self.assertEqual(archive.read_bytes(), b"previous successful export")
                self.assertEqual(list(self.base.glob(".review.zip.*.tmp")), [])

    def _seal_sources(self, sources: list[dict]) -> Path:
        self.manifest["sources"] = sources
        self.manifest = seal_manifest(self.manifest)
        payload = json.dumps({"manifest_sensitive": {"sources": sources}}).encode()
        seal = self.run / UNBLIND_FILENAME
        seal.write_bytes(payload)
        self.manifest["outputs"]["unblind_seal_sha256"] = hashlib.sha256(payload).hexdigest()
        return seal

    def test_sealed_source_destinations_are_protected_without_unblinding_export(self) -> None:
        source = self.base / "private-original.mp4"
        source.write_bytes(b"raw recording")
        image_set = self.base / "private-image-set"
        image_set.mkdir()
        image = image_set / "original.png"
        image.write_bytes(b"original image")
        seal = self._seal_sources([
            {"source_id": "src-1", "path": str(source), "kind": "video", "label": "private-role"},
            {"source_id": "src-2", "path": str(image_set), "kind": "image-set"},
        ])
        sealed_bytes = seal.read_bytes()
        manifest_snapshot = json.dumps(self.manifest, sort_keys=True)
        for destination in (source, image, image_set / "new" / "review.zip"):
            with self.subTest(destination=destination):
                with self.assertRaisesRegex(ValueError, "original capture source"):
                    self._export(destination)
                self.assertEqual(source.read_bytes(), b"raw recording")
                self.assertEqual(image.read_bytes(), b"original image")
                self.assertFalse((image_set / "new").exists())
        with zipfile.ZipFile(self._export()) as archive:
            self.assertNotIn(UNBLIND_FILENAME, " ".join(archive.namelist()))
            for name in archive.namelist():
                content = archive.read(name)
                self.assertNotIn(b"private-original", content)
                self.assertNotIn(b"private-image-set", content)
                self.assertNotIn(b"private-role", content)
        self.assertEqual(seal.read_bytes(), sealed_bytes)
        self.assertEqual(json.dumps(self.manifest, sort_keys=True), manifest_snapshot)

    def test_unavailable_or_inconsistent_sealed_sources_preserve_existing_export(self) -> None:
        source = {"source_id": "src-1", "path": str(self.base / "original.mp4"), "kind": "video"}
        archive = self.base / "review.zip"
        for failure in ("missing", "hash-mismatch", "invalid-json", "missing-sources", "missing-source", "missing-path"):
            with self.subTest(failure=failure):
                seal = self._seal_sources([source])
                if failure == "missing":
                    seal.unlink()
                elif failure == "hash-mismatch":
                    seal.write_bytes(b"changed")
                else:
                    payload = {
                        "invalid-json": b"{",
                        "missing-sources": b"{}",
                        "missing-source": b'{"manifest_sensitive": {"sources": []}}',
                        "missing-path": b'{"manifest_sensitive": {"sources": [{"source_id": "src-1"}]}}',
                    }[failure]
                    seal.write_bytes(payload)
                    self.manifest["outputs"]["unblind_seal_sha256"] = hashlib.sha256(payload).hexdigest()
                archive.write_bytes(b"previous complete export")
                with self.assertRaisesRegex(ValueError, "sealed source map"):
                    self._export(archive)
                self.assertEqual(archive.read_bytes(), b"previous complete export")
                self.assertEqual(list(self.base.glob(".review.zip.*.tmp")), [])

    def test_sealed_source_map_symlink_cannot_read_outside_selected_run(self) -> None:
        seal = self._seal_sources([
            {"source_id": "src-1", "path": str(self.base / "original.mp4"), "kind": "video"}
        ])
        outside = self.base / "private-map.json"
        outside.write_bytes(seal.read_bytes())
        seal.unlink()
        try:
            seal.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symlinks unavailable on this test runner: {exc}")
        with patch.object(Path, "read_bytes", side_effect=AssertionError("External map must not be read")):
            with self.assertRaisesRegex(ValueError, "sealed source map"):
                self._export()
        self.assertFalse((self.base / "review.zip").exists())

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
