"""Durable, atomic experiment manifest persistence regression tests.

All data is synthetic and local; failed writes must preserve the complete
previous experiment record and remove temporary staging files.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from laserlab.manifest import load_manifest, load_or_create_manifest, write_manifest


class AtomicManifestPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.experiment = Path(temp.name) / "experiment"
        self.original = load_or_create_manifest(self.experiment)
        self.path = self.experiment / "manifest.json"
        self.before = self.path.read_bytes()

    def _staging_files(self) -> list[Path]:
        return list(self.experiment.glob(".manifest-*.json.tmp"))

    def test_successful_update_replaces_manifest_without_leftovers(self) -> None:
        amended = dict(self.original)
        amended["protocol"] = "diffraction"
        write_manifest(self.experiment, amended)
        self.assertEqual(load_manifest(self.experiment)["protocol"], "diffraction")
        self.assertNotEqual(self.path.read_bytes(), self.before)
        self.assertEqual(self._staging_files(), [])

    def test_partial_serialization_failure_keeps_previous_record(self) -> None:
        def fail_after_partial_write(path: Path, _document: dict) -> None:
            path.write_bytes(b'{ "truncated":')
            raise OSError("disk became full")

        with patch("laserlab.manifest.write_json", side_effect=fail_after_partial_write):
            with self.assertRaisesRegex(OSError, "disk became full"):
                write_manifest(self.experiment, {**self.original, "protocol": "ocr"})

        self.assertEqual(self.path.read_bytes(), self.before)
        self.assertEqual(self._staging_files(), [])

    def test_failed_atomic_replace_keeps_previous_record(self) -> None:
        with patch("laserlab.manifest.os.replace", side_effect=OSError("rename denied")):
            with self.assertRaisesRegex(OSError, "rename denied"):
                write_manifest(self.experiment, {**self.original, "protocol": "anomaly"})

        self.assertEqual(self.path.read_bytes(), self.before)
        self.assertEqual(self._staging_files(), [])

    def test_interrupted_serialization_removes_partial_staging_file(self) -> None:
        def interrupted(path: Path, _document: dict) -> None:
            path.write_bytes(b'{"interrupted":true')
            raise KeyboardInterrupt

        with patch("laserlab.manifest.write_json", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                write_manifest(self.experiment, self.original)

        self.assertEqual(self.path.read_bytes(), self.before)
        self.assertEqual(self._staging_files(), [])


if __name__ == "__main__":
    unittest.main()
