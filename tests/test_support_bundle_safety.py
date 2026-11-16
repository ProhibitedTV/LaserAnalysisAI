"""Support exports must preserve existing files and remove failed new exports."""
from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from laserlab.diagnostics import export_support_bundle


class SupportBundleSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.record = {"schema": "laserlab.diagnostics", "schema_version": 1}
        for target, value in (("collect_diagnostics", self.record), ("get_log_path", self.root / "absent.log")):
            mock = patch("laserlab.diagnostics." + target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def test_existing_exports_and_research_files_are_never_overwritten(self) -> None:
        for name in ("previous-support.zip", "manifest.json", "capture.mp4", "laserlab.log"):
            with self.subTest(name=name):
                destination = self.root / name
                destination.write_bytes(b"original file must survive")
                with self.assertRaisesRegex(FileExistsError, "new filename"):
                    export_support_bundle(destination)
                self.assertEqual(destination.read_bytes(), b"original file must survive")

    def test_archive_generation_failure_does_not_leave_a_partial_export(self) -> None:
        destination = self.root / "support.zip"
        with patch("laserlab.diagnostics.zipfile.ZipFile.writestr", side_effect=OSError("simulated archive failure")):
            with self.assertRaisesRegex(OSError, "simulated archive failure"):
                export_support_bundle(destination)
        self.assertFalse(destination.exists())

    def test_failed_disk_sync_removes_only_the_new_export(self) -> None:
        destination = self.root / "support.zip"
        original = self.root / "research.json"
        original.write_bytes(b"saved research")
        with patch("laserlab.diagnostics.os.fsync", side_effect=OSError("simulated sync failure")):
            with self.assertRaisesRegex(OSError, "simulated sync failure"):
                export_support_bundle(destination)
        self.assertFalse(destination.exists())
        self.assertEqual(original.read_bytes(), b"saved research")

    def test_failed_disk_write_removes_new_partial_export(self) -> None:
        destination = self.root / "support.zip"
        real_open = Path.open
        class FailingWriter:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def write(self, data):
                self.stream.write(data[:12])
                raise OSError("simulated disk full")
        def open_with_failure(path, *args, **kwargs):
            stream = real_open(path, *args, **kwargs)
            return FailingWriter(stream) if path == destination and args[0] == "xb" else stream
        with patch.object(Path, "open", open_with_failure):
            with self.assertRaisesRegex(OSError, "simulated disk full"):
                export_support_bundle(destination)
        self.assertFalse(destination.exists())

    def test_destination_created_while_diagnostics_runs_is_preserved(self) -> None:
        destination = self.root / "support.zip"
        def competing_export(*args):
            destination.write_bytes(b"another completed export")
            return self.record
        with patch("laserlab.diagnostics.collect_diagnostics", side_effect=competing_export):
            with self.assertRaisesRegex(FileExistsError, "new filename"):
                export_support_bundle(destination)
        self.assertEqual(destination.read_bytes(), b"another completed export")

    def test_successful_export_still_contains_only_support_members(self) -> None:
        destination = self.root / "support.zip"
        exported = export_support_bundle(destination)
        self.assertEqual(exported, destination)
        with zipfile.ZipFile(exported) as archive:
            self.assertEqual(archive.namelist(), ["diagnostics.json"])
            self.assertIsNone(archive.testzip())
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["support.zip"])

    def test_existing_and_dangling_symlink_destinations_are_preserved(self) -> None:
        original = self.root / "original.json"
        original.write_bytes(b"saved original")
        for target in (original, self.root / "missing.json"):
            link = self.root / (target.stem + "-link.zip")
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Symlinks unavailable on this runner: {exc}")
            with self.assertRaisesRegex(FileExistsError, "new filename"):
                export_support_bundle(link)
            self.assertTrue(link.is_symlink())
            self.assertEqual(original.read_bytes(), b"saved original")
        self.assertFalse((self.root / "missing.json").exists())


if __name__ == "__main__":
    unittest.main()
