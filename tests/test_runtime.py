from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from laserlab import runtime


class RuntimePathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def _write_resource(self, root: Path, *parts: str) -> Path:
        resource = root.joinpath(*parts)
        resource.parent.mkdir(parents=True, exist_ok=True)
        resource.write_text("fixture", encoding="utf-8")
        return resource

    def _runtime_file(self, repository_root: Path) -> Path:
        runtime_file = repository_root / "laserlab" / "runtime.py"
        runtime_file.parent.mkdir(parents=True, exist_ok=True)
        runtime_file.touch()
        return runtime_file

    def test_resource_override_has_highest_precedence(self) -> None:
        override_root = self.root / "override"
        meipass_root = self.root / "meipass"
        executable_root = self.root / "application"
        repository_root = self.root / "repository"
        expected = self._write_resource(override_root, "sample_media", "demo.png").resolve()
        self._write_resource(meipass_root, "sample_media", "demo.png")
        self._write_resource(executable_root, "sample_media", "demo.png")
        self._write_resource(repository_root, "sample_media", "demo.png")

        with (
            mock.patch.dict(os.environ, {"LASERLAB_RESOURCE_ROOT": str(override_root)}),
            mock.patch.object(sys, "_MEIPASS", str(meipass_root), create=True),
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch.object(sys, "executable", str(executable_root / "LaserLab.exe")),
            mock.patch.object(runtime, "__file__", str(self._runtime_file(repository_root))),
        ):
            self.assertEqual(runtime.resource_path("sample_media", "demo.png"), expected)

    def test_meipass_precedes_frozen_executable_and_repository(self) -> None:
        meipass_root = self.root / "meipass"
        executable_root = self.root / "application"
        repository_root = self.root / "repository"
        expected = self._write_resource(meipass_root, "fixtures", "blank.png").resolve()
        self._write_resource(executable_root, "fixtures", "blank.png")
        self._write_resource(repository_root, "fixtures", "blank.png")

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(sys, "_MEIPASS", str(meipass_root), create=True),
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch.object(sys, "executable", str(executable_root / "LaserLab.exe")),
            mock.patch.object(runtime, "__file__", str(self._runtime_file(repository_root))),
        ):
            self.assertEqual(runtime.resource_path("fixtures", "blank.png"), expected)

    def test_missing_override_falls_through_to_existing_meipass_resource(self) -> None:
        override_root = self.root / "missing-override"
        meipass_root = self.root / "meipass"
        repository_root = self.root / "repository"
        expected = self._write_resource(meipass_root, "fixtures", "noise.png").resolve()

        with (
            mock.patch.dict(
                os.environ,
                {"LASERLAB_RESOURCE_ROOT": str(override_root)},
                clear=True,
            ),
            mock.patch.object(sys, "_MEIPASS", str(meipass_root), create=True),
            mock.patch.object(sys, "frozen", False, create=True),
            mock.patch.object(runtime, "__file__", str(self._runtime_file(repository_root))),
        ):
            self.assertEqual(runtime.resource_path("fixtures", "noise.png"), expected)

    def test_frozen_executable_directory_precedes_repository(self) -> None:
        executable_root = self.root / "application"
        repository_root = self.root / "repository"
        expected = self._write_resource(executable_root, "fixtures", "grating.png").resolve()
        self._write_resource(repository_root, "fixtures", "grating.png")

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(sys, "_MEIPASS", None, create=True),
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch.object(sys, "executable", str(executable_root / "LaserLab.exe")),
            mock.patch.object(runtime, "__file__", str(self._runtime_file(repository_root))),
        ):
            self.assertEqual(runtime.resource_path("fixtures", "grating.png"), expected)

    def test_source_resource_resolution_is_independent_of_current_directory(self) -> None:
        repository_root = self.root / "repository"
        unrelated = self.root / "unrelated-working-directory"
        unrelated.mkdir()
        expected = self._write_resource(repository_root, "sample_media", "laser.png").resolve()

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(sys, "_MEIPASS", None, create=True),
            mock.patch.object(sys, "frozen", False, create=True),
            mock.patch.object(runtime, "__file__", str(self._runtime_file(repository_root))),
            mock.patch("pathlib.Path.cwd", return_value=unrelated),
        ):
            self.assertEqual(runtime.resource_path("sample_media", "laser.png"), expected)

    def test_missing_resource_uses_highest_precedence_fallback(self) -> None:
        override_root = self.root / "missing-override"
        repository_root = self.root / "repository"

        with (
            mock.patch.dict(os.environ, {"LASERLAB_RESOURCE_ROOT": str(override_root)}, clear=True),
            mock.patch.object(sys, "_MEIPASS", None, create=True),
            mock.patch.object(sys, "frozen", False, create=True),
            mock.patch.object(runtime, "__file__", str(self._runtime_file(repository_root))),
        ):
            result = runtime.resource_path("not-present", "fixture.png")

        self.assertEqual(
            result,
            override_root.resolve() / "not-present" / "fixture.png",
        )
        self.assertFalse(result.exists())

    def test_experiments_override_is_honored_without_creating_it(self) -> None:
        override = self.root / "custom" / "experiments"

        with mock.patch.dict(
            os.environ,
            {"LASERLAB_EXPERIMENTS_DIR": str(override)},
            clear=True,
        ):
            result = runtime.default_experiments_dir()

        self.assertEqual(result, override.resolve())
        self.assertFalse(override.exists())

    def test_frozen_experiments_default_uses_user_documents(self) -> None:
        home = self.root / "user-home"
        expected = home / "Documents" / "LaserLab" / "experiments"

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch.object(Path, "home", return_value=home),
        ):
            result = runtime.default_experiments_dir()

        self.assertEqual(result, expected)
        self.assertFalse(expected.exists())

    def test_source_experiments_default_uses_repository_root(self) -> None:
        repository_root = self.root / "repository"
        unrelated = self.root / "unrelated-working-directory"
        unrelated.mkdir()
        expected = repository_root.resolve() / "experiments"

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(sys, "frozen", False, create=True),
            mock.patch.object(runtime, "__file__", str(self._runtime_file(repository_root))),
            mock.patch("pathlib.Path.cwd", return_value=unrelated),
        ):
            result = runtime.default_experiments_dir()

        self.assertEqual(result, expected)
        self.assertFalse(expected.exists())


if __name__ == "__main__":
    unittest.main()
