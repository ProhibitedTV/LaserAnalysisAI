"""Release identity/preservation checks with real Git history and fake compilers."""
from __future__ import annotations

import contextlib
import hashlib
import io
import tarfile
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

    def test_explicitly_authorized_fonts_are_embedded_in_both_products_and_archive(self):
        from laserlab.branding import BRAND_FONT_VARIANTS
        font_root = self.parent / "approved-fonts"
        font_root.mkdir()
        sample = b"sample-font-test-data" * 128
        expected = {}
        for _, filename, _ in BRAND_FONT_VARIANTS.values():
            (font_root / filename).write_bytes(sample)
            expected[filename] = hashlib.sha256(sample).hexdigest()
        permission = "CodeOfReality fonts: copyright holders authorize this specific LaserLab binary distribution.\\n"
        (font_root / release.FONT_RIGHTS_NOTICE).write_text(permission, encoding="utf-8")
        with patch.dict(os.environ, {
            "LASERLAB_RELEASE_FONTS_DIR": str(font_root),
            "LASERLAB_FONT_REDISTRIBUTION_CONFIRMED": "yes",
        }), patch.object(release, "_expected_font_hashes", return_value=expected):
            archive = self.build()
        bundle = archive.with_suffix("")
        info = json.loads((bundle / "BUILD-INFO.json").read_text())
        self.assertEqual(info["bundled_codeofreality_font_count"], 7)
        self.assertTrue(info["font_redistribution_attested_by_release_builder"])
        self.assertEqual({path.name for path in (bundle / "fonts").iterdir()}, set(expected) | {release.FONT_RIGHTS_NOTICE})
        self.assertEqual((bundle / "fonts" / release.FONT_RIGHTS_NOTICE).read_text(), permission)
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256((bundle / "fonts" / name).read_bytes()).hexdigest(), digest)
        for command in self.commands:
            entries = [command[index + 1] for index, arg in enumerate(command) if arg == "--add-data"]
            self.assertEqual(len(entries), 2)
            staged_fonts, target = entries[1].rsplit(os.pathsep, 1)
            self.assertEqual(target, "fonts")
            self.assertEqual(
                {p.name for p in Path(staged_fonts).iterdir()},
                set(expected) | {release.FONT_RIGHTS_NOTICE},
            )
        self.smoke.assert_called_once()
        self.assertTrue(self.smoke.call_args.kwargs["fonts_included"])
        with zipfile.ZipFile(archive) as zipped:
            for name in expected:
                self.assertEqual(
                    zipped.read(f"{bundle.name}/fonts/{name}"),
                    sample,
                )
            self.assertEqual(
                zipped.read(f"{bundle.name}/fonts/{release.FONT_RIGHTS_NOTICE}").decode("utf-8"),
                permission,
            )

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



class VendoredCodeOfRealityReleaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.build_root = self.root / "work"
        self.build_root.mkdir()
        self.archive_path = self.root / release.VENDORED_FONT_ARCHIVE
        self.archive_path.parent.mkdir(parents=True)
        self.notice = self.root / release.VENDORED_FONT_ATTESTATION
        self.notice.parent.mkdir(parents=True)
        self.notice.write_text(
            "The maintainer reports direct permission from the creator on Discord for these seven fonts.",
            encoding="utf-8",
        )
        from laserlab.branding import BRAND_FONT_VARIANTS
        # Incompressible deterministic fixtures keep the tar.xz above the
        # release builder's minimum archive-size threshold.
        self.data = {filename: hashlib.shake_256(filename.encode()).digest(2048)
                     for _, filename, _ in BRAND_FONT_VARIANTS.values()}
        self.hashes = {name: hashlib.sha256(payload).hexdigest()
                       for name, payload in self.data.items()}

    def write_archive(self, *, entries=None):
        with tarfile.open(self.archive_path, "w:xz") as bundle:
            for name, payload in (entries if entries is not None else self.data.items()):
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                bundle.addfile(info, io.BytesIO(payload))

    def stage(self):
        with patch.object(release, "ROOT", self.root), \
             patch.object(release, "VENDORED_FONT_ARCHIVE_SHA256", release._sha256(self.archive_path)), \
             patch.object(release, "_expected_font_hashes", return_value=self.hashes), \
             patch.dict(os.environ, {
                 "LASERLAB_RELEASE_FONTS_DIR": "",
                 "LASERLAB_FONT_REDISTRIBUTION_CONFIRMED": "",
             }):
            return release._stage_authorized_fonts(self.build_root)

    def test_vendored_archive_verifies_all_original_filenames_and_packages_permission(self):
        self.write_archive()
        destination = self.stage()
        self.assertEqual({f.name for f in destination.iterdir()}, set(self.data) | {release.FONT_RIGHTS_NOTICE})
        for name, payload in self.data.items():
            self.assertEqual((destination / name).read_bytes(), payload)
        self.assertIn("Discord", (destination / release.FONT_RIGHTS_NOTICE).read_text())

    def test_archive_rejects_unexpected_file_before_any_extraction(self):
        self.write_archive(entries=list(self.data.items()) + [("../escape.ttf", b"unexpected")])
        with self.assertRaisesRegex(ValueError, "exactly the seven reviewed"):
            self.stage()
        self.assertFalse((self.build_root / "resources" / "fonts").exists())

    def test_archive_rejects_bad_font_hash(self):
        self.write_archive(entries=[
            (name, b"not the reviewed font " * 128 if name == "CodeOfReality-Oracle.ttf" else payload)
            for name, payload in self.data.items()
        ])
        with self.assertRaisesRegex(ValueError, "font fingerprint mismatch"):
            self.stage()

    def test_vendored_archive_fingerprint_is_pinned_to_the_exact_source_bytes(self):
        self.write_archive()
        with patch.object(release, "ROOT", self.root), \
             patch.object(release, "_expected_font_hashes", return_value=self.hashes), \
             patch.dict(os.environ, {"LASERLAB_RELEASE_FONTS_DIR": ""}):
            with self.assertRaisesRegex(ValueError, "archive fingerprint mismatch"):
                release._stage_authorized_fonts(self.build_root)

    def test_archive_requires_a_true_record_of_maintainer_reported_permission(self):
        self.write_archive()
        self.notice.write_text("Some unrelated placeholder", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "attestation is incomplete"):
            self.stage()


class OptionalCodeOfRealityReleaseTests(unittest.TestCase):
    def test_checkout_without_vendored_archive_remains_a_valid_unbundled_development_build(self):
        with patch.dict(os.environ, {"LASERLAB_RELEASE_FONTS_DIR": "", "LASERLAB_FONT_REDISTRIBUTION_CONFIRMED": ""}):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with patch.object(release, "ROOT", root):
                    self.assertIsNone(release._stage_authorized_fonts(root))

    def test_authorized_font_build_requires_a_real_rights_notice_file(self):
        from laserlab.branding import BRAND_FONT_VARIANTS

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "approved"
            source.mkdir()
            fixture = b"synthetic-font" * 200
            expected = {}
            for _, filename, _ in BRAND_FONT_VARIANTS.values():
                (source / filename).write_bytes(fixture)
                expected[filename] = hashlib.sha256(fixture).hexdigest()
            with patch.dict(os.environ, {
                "LASERLAB_RELEASE_FONTS_DIR": str(source),
                "LASERLAB_FONT_REDISTRIBUTION_CONFIRMED": "yes",
            }), patch.object(release, "_expected_font_hashes", return_value=expected):
                with self.assertRaisesRegex(ValueError, "CODEOFREALITY-PERMISSION.txt"):
                    release._stage_authorized_fonts(root)
                notice = source / release.FONT_RIGHTS_NOTICE
                notice.write_text("placeholder", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "notice"):
                    release._stage_authorized_fonts(root)
                self.assertFalse((root / "resources" / "fonts").exists())
                notice.write_text(
                    "This is a synthetic test permission notice; no real font distribution is authorized.",
                    encoding="utf-8",
                )
                destination = release._stage_authorized_fonts(root)
            self.assertTrue((destination / release.FONT_RIGHTS_NOTICE).is_file())

    def test_release_font_staging_requires_explicit_authorization_and_all_seven_files(self):
        from laserlab.branding import BRAND_FONT_VARIANTS

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "author-fonts"
            source.mkdir()
            for _, filename, _ in BRAND_FONT_VARIANTS.values():
                (source / filename).write_bytes(b"x" * 2048)
            (source / release.FONT_RIGHTS_NOTICE).write_text(
                "Verified author permission for distribution of all CodeOfReality styles in LaserLab.",
                encoding="utf-8",
            )
            build_root = root / "build"
            build_root.mkdir()
            with patch.dict(os.environ, {
                "LASERLAB_RELEASE_FONTS_DIR": str(source),
                "LASERLAB_FONT_REDISTRIBUTION_CONFIRMED": "",
            }):
                with self.assertRaisesRegex(ValueError, "permission to redistribute"):
                    release._stage_authorized_fonts(build_root)
            with patch.dict(os.environ, {
                "LASERLAB_RELEASE_FONTS_DIR": str(source),
                "LASERLAB_FONT_REDISTRIBUTION_CONFIRMED": "yes",
            }), patch.object(
                release, "_expected_font_hashes",
                return_value={spec[1]: hashlib.sha256(b"x" * 2048).hexdigest()
                              for spec in BRAND_FONT_VARIANTS.values()},
            ):
                (source / "CodeOfReality-Oracle.ttf").unlink()
                with self.assertRaisesRegex(ValueError, "CodeOfReality-Oracle"):
                    release._stage_authorized_fonts(build_root)
                (source / "CodeOfReality-Oracle.ttf").write_bytes(b"x" * 2048)
                destination = release._stage_authorized_fonts(build_root)
            self.assertIsNotNone(destination)
            self.assertEqual({p.name for p in destination.iterdir()}, {
                item[1] for item in BRAND_FONT_VARIANTS.values()
            } | {release.FONT_RIGHTS_NOTICE})
            command = release._pyinstaller_command(
                "laserlab_launcher.py", "LaserLab", root / "dist", root / "work",
                root / "spec", True, media_dir=root / "public-media", fonts_dir=destination,
            )
            data_args = [command[index + 1] for index, value in enumerate(command) if value == "--add-data"]
            self.assertEqual(len(data_args), 2)
            self.assertTrue(data_args[0].endswith(os.pathsep + "sample_media"))
            self.assertEqual(data_args[1], f"{destination}{os.pathsep}fonts")


if __name__ == "__main__":
    unittest.main()
