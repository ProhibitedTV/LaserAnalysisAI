"""Release identity/preservation checks with real Git history and fake compilers."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import build_release as release


class ReleaseBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name).resolve()
        self.root = self.parent / "checkout"
        self.root.mkdir()
        self.output = self.parent / "output"
        self.target = release.default_target()
        (self.root / ".gitignore").write_text("build/\ndist/\nsample_media/private-*\n")
        (self.root / "README.md").write_text("Public usage notes")
        (self.root / "LICENSE").write_text("Public license")
        media = self.root / "sample_media"
        media.mkdir()
        for name in release.BUNDLED_METADATA:
            (media / name).write_text("{}" if name.endswith(".json") else "Public attribution")
        (media / "public.mp4").write_bytes(b"public fixture")
        self.git("init", "-q")
        self.git("add", ".")
        self.git("commit", "-qm", "Public test source")
        self.revision = self.git("rev-parse", "HEAD").strip()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(release, "ROOT", self.root))
        self.stack.enter_context(patch.dict(os.environ, {"GITHUB_REF": ""}))
        self.stack.enter_context(patch.object(release, "FIXTURE_CATALOG", [{"filename": "public.mp4", "redistributable": True}]))
        self.validate = self.stack.enter_context(patch.object(release, "validate_fixture_catalog", return_value=[]))
        self.commands = []
        self.compiler = self.stack.enter_context(patch.object(release, "_run", side_effect=self.fake_compile))
        self.smoke = self.stack.enter_context(patch.object(release, "_smoke"))

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=Release Test", "-c", "user.email=release-test@example.invalid",
                               *args], cwd=self.root, check=True, capture_output=True, text=True).stdout

    def fake_compile(self, command):
        self.commands.append(command)
        destination = Path(command[command.index("--distpath") + 1])
        name = command[command.index("--name") + 1]
        (destination / release.executable_name(name)).write_bytes((name + " native fixture").encode())

    def build(self, **kwargs):
        return release.build_release(self.output, self.target, **kwargs)

    def test_candidate_identity_checksums_and_allow_listed_resources(self):
        # Ignored personal files must not enter embedded or external resources.
        (self.root / "sample_media/private-person.mp4").write_bytes(b"PRIVATE MEDIA")
        archive = self.build()
        self.assertIn(f"-candidate-{self.revision[:12]}-", archive.name)
        bundle = archive.with_suffix("")
        info = json.loads((bundle / "BUILD-INFO.json").read_text())
        self.assertEqual(info["source_revision"], self.revision)
        self.assertEqual(info["source_tree"], self.git("rev-parse", "HEAD^{tree}").strip())
        self.assertEqual(info["build_channel"], "candidate")
        self.assertFalse(info["source_dirty"])
        self.assertIsNone(info["release_tag"])
        self.assertNotIn(str(self.root), json.dumps(info))
        self.assertEqual(archive.with_name(archive.name + ".sha256").read_bytes(),
                         f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n".encode())
        checksums = dict(line.split("  ", 1)[::-1] for line in (bundle / "SHA256SUMS").read_text().splitlines())
        self.assertIn("BUILD-INFO.json", checksums)
        with zipfile.ZipFile(archive) as zipped:
            self.assertFalse(any("private-person" in name for name in zipped.namelist()))
            names = {str(Path(name).relative_to(bundle.name)).replace("\\", "/") for name in zipped.namelist()}
            self.assertEqual(names, set(checksums) | {"SHA256SUMS"})
            for name, digest in checksums.items():
                self.assertEqual(hashlib.sha256(zipped.read(bundle.name + "/" + name)).hexdigest(), digest)
        for command in self.commands:
            embedded = Path(command[command.index("--add-data") + 1].rsplit(os.pathsep, 1)[0])
            self.assertNotEqual(embedded, self.root / "sample_media")
            self.assertEqual({path.name for path in embedded.iterdir()}, set(release.BUNDLED_METADATA) | {"public.mp4"})

    def test_matching_tag_at_exact_commit_builds_a_release(self):
        tag = "v0.9.0"
        self.git("tag", tag)
        with patch.object(release, "__version__", "0.9.0"):
            archive = self.build(release_tag=tag)
        self.assertNotIn("candidate", archive.name)
        info = json.loads((archive.with_suffix("") / "BUILD-INFO.json").read_text())
        self.assertEqual(info["build_channel"], "release")
        self.assertEqual(info["release_tag"], tag)

    def test_nonfinal_tag_is_classified_as_prerelease(self):
        self.git("tag", "v0.9.0rc1")
        with patch.object(release, "__version__", "0.9.0rc1"):
            context = release._release_context("v0.9.0rc1")
        self.assertEqual(context["build_channel"], "prerelease")

    def test_tag_version_and_workflow_mismatches_stop_before_build(self):
        with self.assertRaisesRegex(ValueError, "application version"):
            self.build(release_tag="v999.0.0")
        with patch.dict(os.environ, {"GITHUB_REF": "refs/tags/v999.0.0"}), \
             self.assertRaisesRegex(ValueError, "workflow tag"):
            self.build(release_tag="v" + release.__version__)
        self.compiler.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_matching_version_tag_at_another_commit_is_rejected(self):
        tag = "v" + release.__version__
        self.git("tag", tag)
        (self.root / "README.md").write_text("New source")
        self.git("add", "README.md")
        self.git("commit", "-qm", "Later source")
        with self.assertRaisesRegex(ValueError, "source revision"):
            self.build(release_tag=tag)
        self.compiler.assert_not_called()

    def test_workflow_tag_cannot_relabel_a_development_checkout(self):
        with patch.dict(os.environ, {"GITHUB_REF": "refs/tags/v999.0.0"}), \
             self.assertRaisesRegex(ValueError, "application version"):
            self.build()
        self.compiler.assert_not_called()

    def test_dirty_source_is_rejected_before_output_creation(self):
        (self.root / "README.md").write_text("Uncommitted work")
        with self.assertRaisesRegex(RuntimeError, "clean checkout"):
            self.build()
        self.compiler.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_foreign_git_environment_cannot_supply_release_provenance(self):
        other = self.parent / "other-checkout"
        other.mkdir()
        subprocess.run(["git", "init", "-q", str(other)], check=True, capture_output=True)
        with patch.dict(os.environ, {"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)}), \
             self.assertRaisesRegex(RuntimeError, "checkout root"):
            self.build()
        self.compiler.assert_not_called()

    def test_existing_outputs_and_old_work_are_preserved(self):
        old = self.root / "build" / ("release-" + self.target)
        old.mkdir(parents=True)
        (old / "checkpoint.txt").write_text("Preserve this candidate")
        archive = self.build()
        before = archive.read_bytes()
        with self.assertRaisesRegex(FileExistsError, "fresh output"):
            self.build()
        self.assertEqual(archive.read_bytes(), before)
        self.assertEqual((old / "checkpoint.txt").read_text(), "Preserve this candidate")
        self.assertEqual(self.compiler.call_count, 2)

    def test_zip_or_checksum_collision_is_refused_without_a_compile(self):
        stem = f"LaserLab-v{release.__version__}-candidate-{self.revision[:12]}-{self.target}"
        self.output.mkdir()
        for suffix in (".zip", ".zip.sha256"):
            with self.subTest(suffix=suffix):
                path = self.output / (stem + suffix)
                path.write_bytes(b"Existing artifact")
                with self.assertRaises(FileExistsError):
                    self.build()
                self.assertEqual(path.read_bytes(), b"Existing artifact")
                path.unlink()
        self.compiler.assert_not_called()

    def test_archive_helper_never_truncates_existing_files(self):
        bundle = self.parent / "bundle"
        bundle.mkdir()
        (bundle / "public.txt").write_text("Public")
        archive = self.parent / "old.zip"
        archive.write_bytes(b"Existing artifact")
        with self.assertRaises(FileExistsError):
            release._write_archive(bundle, archive)
        self.assertEqual(archive.read_bytes(), b"Existing artifact")

    def test_failed_fixture_validation_cannot_produce_an_archive(self):
        self.validate.return_value = ["PRIVATE malformed input"]
        with self.assertRaisesRegex(ValueError, "fixture validation") as error:
            self.build()
        self.assertNotIn("PRIVATE", str(error.exception))
        self.compiler.assert_not_called()
        self.assertEqual(list(self.output.glob("*.zip")), [])

    def test_resource_paths_cannot_escape_the_fixture_directory(self):
        with patch.object(release, "FIXTURE_CATALOG", [{"filename": "../private.mp4", "redistributable": True}]), \
             self.assertRaisesRegex(ValueError, "managed fixture"):
            self.build()
        self.compiler.assert_not_called()

    def test_wrong_host_target_is_not_mislabeled(self):
        other = next(target for target in release.VALID_TARGETS if target != self.target)
        with self.assertRaisesRegex(ValueError, "build host"):
            release.build_release(self.output, other)
        self.compiler.assert_not_called()

    def test_source_edit_during_packaging_is_detected(self):
        def compile_and_edit(command):
            self.fake_compile(command)
            (self.root / "README.md").write_text("Concurrent work")
        self.compiler.side_effect = compile_and_edit
        with self.assertRaisesRegex(RuntimeError, "clean checkout"):
            self.build()
        self.assertEqual(list(self.output.glob("*.zip")), [])
        self.assertEqual((self.root / "README.md").read_text(), "Concurrent work")

    def test_source_commit_during_packaging_is_detected(self):
        def compile_and_commit(command):
            self.fake_compile(command)
            if len(self.commands) == 1:
                (self.root / "README.md").write_text("Concurrent commit")
                self.git("add", "README.md")
                self.git("commit", "-qm", "Concurrent source")
        self.compiler.side_effect = compile_and_commit
        with self.assertRaisesRegex(RuntimeError, "Source changed"):
            self.build()
        self.assertEqual(list(self.output.glob("*.zip")), [])

    def test_main_emits_candidate_channel_for_actions(self):
        output = self.parent / "actions-output.txt"
        with patch.object(sys, "argv", ["build_release.py", "--output-dir", str(self.output), "--target", self.target]), \
             patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
            self.assertEqual(release.main(), 0)
        self.assertEqual(output.read_bytes(), b"prerelease=true\n")

    def test_main_emits_stable_channel_only_for_a_matching_final_tag(self):
        output = self.parent / "actions-output.txt"
        self.git("tag", "v0.9.0")
        with patch.object(release, "__version__", "0.9.0"), \
             patch.object(sys, "argv", ["build_release.py", "--output-dir", str(self.output),
                                       "--target", self.target, "--release-tag", "v0.9.0"]), \
             patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
            self.assertEqual(release.main(), 0)
        self.assertEqual(output.read_bytes(), b"prerelease=false\n")

    @unittest.skipUnless(sys.platform == "win32" and shutil.which("pwsh"), "Windows PowerShell wrapper check")
    def test_windows_wrapper_stops_on_native_bootstrap_failure(self):
        fake_python = self.parent / "failing-python.cmd"
        fake_python.write_bytes(b"@exit /b 23\r\n")
        wrapper = Path(__file__).resolve().parents[1] / "scripts/build_windows_exe.ps1"
        result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-File", str(wrapper),
                                 "-Python", str(fake_python), "-OutputDir", str(self.output)],
                                capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python package bootstrap failed", result.stderr)
        self.assertFalse(self.output.exists())


class ReleaseVersionConsistencyTests(unittest.TestCase):
    def test_native_and_project_versions_match(self):
        root = Path(__file__).resolve().parents[1]
        project = (root / "pyproject.toml").read_text(encoding="utf-8").split("[project]", 1)[1].split("\n[", 1)[0]
        version = re.search(r'(?m)^version\s*=\s*"([^"\n]+)"\s*$', project)
        self.assertIsNotNone(version)
        self.assertEqual(version[1], release.__version__)


if __name__ == "__main__":
    unittest.main()
