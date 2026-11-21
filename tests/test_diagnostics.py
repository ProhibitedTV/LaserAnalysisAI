from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
import unittest
import zipfile
from importlib import metadata
from pathlib import Path
from unittest.mock import patch

from laserlab import diagnostics


class DiagnosticsTests(unittest.TestCase):
    def tearDown(self) -> None:
        logger = logging.getLogger("laserlab")
        for handler in list(logger.handlers):
            if getattr(handler, "_laserlab_managed", False):
                logger.removeHandler(handler)
                handler.close()

    def test_record_is_json_safe_private_and_does_not_read_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            experiment = Path(temporary) / "private-experiment"
            experiment.mkdir()
            (experiment / "manifest.json").write_text(
                json.dumps({"sources": [{"path": str(Path.home() / "secret.mov"), "label": "laser"}]}),
                encoding="utf-8",
            )
            sensitive_platform = " ".join(
                (
                    str(Path.home()),
                    tempfile.gettempdir(),
                    str(Path(diagnostics.__file__).resolve().parents[1]),
                )
            )
            with patch("laserlab.diagnostics.platform.platform", return_value=sensitive_platform):
                record = diagnostics.collect_diagnostics(experiment)

        serialized = json.dumps(record, allow_nan=False)
        self.assertEqual(record["schema"], "laserlab.diagnostics")
        self.assertEqual(record["schema_version"], 1)
        self.assertRegex(record["timestamp_utc"], r"^\d{4}-\d{2}-\d{2}T")
        self.assertIn("python_version", record["runtime"])
        self.assertIn("frozen", record["runtime"])
        self.assertEqual(record["runtime"]["entrypoint"], "source")
        self.assertIn("opencv", record["dependencies"])
        self.assertTrue(record["ocr"]["optional"])
        self.assertIn("codeofreality", record["ocr"])
        self.assertGreaterEqual(record["fixtures"]["catalog_count"], record["fixtures"]["redistributable_count"])
        self.assertIsInstance(record["fixtures"]["catalog_valid"], bool)
        self.assertTrue(record["experiment"]["exists"])
        self.assertTrue(record["experiment"]["manifest_present"])
        self.assertFalse(record["privacy"]["manifest_read"])
        self.assertNotIn(str(Path.home()), serialized)
        self.assertNotIn(tempfile.gettempdir(), serialized)
        self.assertNotIn(str(Path(diagnostics.__file__).resolve().parents[1]), serialized)
        self.assertNotIn("secret.mov", serialized)
        self.assertNotIn('"label"', serialized)

    def test_unavailable_dependencies_and_tesseract_are_contained(self) -> None:
        with (
            patch("laserlab.diagnostics.metadata.version", side_effect=metadata.PackageNotFoundError),
            patch("laserlab.diagnostics.shutil.which", return_value=None),
        ):
            record = diagnostics.collect_diagnostics()

        for dependency in record["dependencies"].values():
            self.assertFalse(dependency["available"])
            self.assertEqual(dependency["status"], "unavailable")
        self.assertEqual(
            record["ocr"]["tesseract"],
            {
                "available": False,
                "version": None,
                "status": "unavailable",
                "failure": "executable not found",
            },
        )

    def test_codeofreality_diagnostics_separate_selection_from_font_readiness(self) -> None:
        font_check = {
            "verified_variants": 2,
            "fonts": [
                {"variant": "classic", "status": "verified"},
                {"variant": "oracle", "status": "verified"},
                {"variant": "circuit", "status": "missing"},
            ],
        }
        with (
            patch.dict("laserlab.diagnostics.os.environ", {"LASERLAB_FONT_OCR_VARIANTS": "classic,oracle"}),
            patch("laserlab.font_qualification.inspect_font_resources", return_value=font_check),
        ):
            record = diagnostics._codeofreality_record()
        self.assertEqual(record["selection"], "enabled")
        self.assertEqual(record["selected_variants"], ["classic", "oracle"])
        self.assertEqual(record["reference_check"], "completed")
        self.assertEqual(record["verified_variants"], 2)
        self.assertEqual(record["variant_statuses"]["circuit"], "missing")
        self.assertFalse(record["tesseract_language_model"])
        self.assertFalse(record["scientific_accuracy_validated"])

    def test_codeofreality_invalid_selection_and_loader_failure_are_safe(self) -> None:
        with (
            patch.dict("laserlab.diagnostics.os.environ", {"LASERLAB_FONT_OCR_VARIANTS": "eng"}),
            patch("laserlab.font_qualification.inspect_font_resources", side_effect=RuntimeError("/home/private/fonts")),
        ):
            record = diagnostics._codeofreality_record()
        self.assertEqual(record["selection"], "invalid_selection")
        self.assertEqual(record["selected_variants"], [])
        self.assertEqual(record["reference_check"], "failed")
        self.assertNotIn("/home/private", json.dumps(record))

    def test_codeofreality_disabled_is_distinct_from_missing_fonts(self) -> None:
        with (
            patch.dict("laserlab.diagnostics.os.environ", {"LASERLAB_FONT_OCR_VARIANTS": ""}),
            patch("laserlab.font_qualification.inspect_font_resources", return_value={
                "verified_variants": 7,
                "fonts": [{"variant": "classic", "status": "verified"}],
            }),
        ):
            record = diagnostics._codeofreality_record()
        self.assertEqual(record["selection"], "disabled")
        self.assertEqual(record["selected_variants"], [])
        self.assertEqual(record["verified_variants"], 7)

    def test_linux_native_import_probe_succeeds_without_exposing_output(self) -> None:
        completed = subprocess.CompletedProcess(["python", "-c", "import cv2"], 0, b"", b"")
        with (
            patch("laserlab.diagnostics.sys.platform", "linux"),
            patch.object(sys, "frozen", False, create=True),
            patch("laserlab.diagnostics.subprocess.run", return_value=completed) as run,
        ):
            record = diagnostics._opencv_import_record()
        self.assertEqual(record, {"status": "available"})
        self.assertEqual(run.call_args.kwargs["timeout"], 10)
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.PIPE)

    def test_linux_native_import_probe_classifies_missing_shared_library_without_leaking_paths(self) -> None:
        error = b"ImportError: libGL.so.1: cannot open shared object file: /home/private/video.png"
        completed = subprocess.CompletedProcess(["python", "-c", "import cv2"], 1, b"", error)
        with (
            patch("laserlab.diagnostics.sys.platform", "linux"),
            patch.object(sys, "frozen", False, create=True),
            patch("laserlab.diagnostics.subprocess.run", return_value=completed),
        ):
            record = diagnostics._opencv_import_record()
        self.assertEqual(record, {"status": "failed", "failure": "shared_library_load_failed", "exit_code": 1})
        self.assertNotIn("private", json.dumps(record))
        self.assertNotIn("libGL", json.dumps(record))

    def test_linux_native_import_probe_contains_a_native_crash_and_timeout(self) -> None:
        crashed = subprocess.CompletedProcess(["python"], -11, b"", b"Segmentation fault")
        with (
            patch("laserlab.diagnostics.sys.platform", "linux"),
            patch.object(sys, "frozen", False, create=True),
            patch("laserlab.diagnostics.subprocess.run", return_value=crashed),
        ):
            self.assertEqual(
                diagnostics._opencv_import_record(),
                {"status": "failed", "failure": "native_process_terminated", "exit_code": -11},
            )
        with (
            patch("laserlab.diagnostics.sys.platform", "linux"),
            patch.object(sys, "frozen", False, create=True),
            patch("laserlab.diagnostics.subprocess.run", side_effect=subprocess.TimeoutExpired("python", 10)),
        ):
            self.assertEqual(diagnostics._opencv_import_record(), {"status": "timeout"})

    def test_packaged_opencv_probe_never_executes_the_app_as_python(self) -> None:
        with (
            patch("laserlab.diagnostics.sys.platform", "linux"),
            patch.object(sys, "frozen", True, create=True),
            patch("laserlab.diagnostics.subprocess.run") as run,
        ):
            self.assertEqual(
                diagnostics._opencv_import_record(),
                {"status": "not_checked", "reason": "packaged_executable"},
            )
        run.assert_not_called()

    def test_state_paths_follow_platform_conventions(self) -> None:
        with (
            patch("laserlab.diagnostics.sys.platform", "win32"),
            patch.dict("laserlab.diagnostics.os.environ", {"LOCALAPPDATA": "C:/Users/test/AppData/Local"}, clear=True),
        ):
            self.assertEqual(diagnostics.get_state_dir(), Path("C:/Users/test/AppData/Local/LaserLab"))
        with (
            patch("laserlab.diagnostics.sys.platform", "darwin"),
            patch("laserlab.diagnostics.Path.home", return_value=Path("/Users/test")),
        ):
            self.assertEqual(diagnostics.get_state_dir(), Path("/Users/test/Library/Application Support/LaserLab"))
        with (
            patch("laserlab.diagnostics.sys.platform", "linux"),
            patch.dict("laserlab.diagnostics.os.environ", {"XDG_STATE_HOME": "/var/state/test"}, clear=True),
        ):
            self.assertEqual(diagnostics.get_state_dir(), Path("/var/state/test/laserlab"))

    def test_rotating_log_redacts_sensitive_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "laserlab.log"
            logger = diagnostics.configure_logging(log_path, install_hook=False)
            try:
                logger.warning(
                "home=%s\ntemp=%s\ninstall=%s\nexternal=%s\nmounted=%s",
                    Path.home(),
                    Path(tempfile.gettempdir()),
                    Path(diagnostics.__file__).resolve().parents[1],
                r"D:\private-captures\laser.mov",
                "/mnt/private-captures/laser.mov",
                )
                for handler in logger.handlers:
                    handler.flush()
                content = log_path.read_text(encoding="utf-8")
            finally:
                for handler in list(logger.handlers):
                    if getattr(handler, "_laserlab_managed", False):
                        logger.removeHandler(handler)
                        handler.close()

        self.assertIn("<HOME>", content)
        self.assertIn("<TEMP>", content)
        self.assertIn("<INSTALL>", content)
        self.assertIn("<PATH>", content)
        self.assertNotIn(str(Path.home()), content)
        self.assertNotIn("private-captures", content)

    def test_exception_hook_logs_then_calls_previous_hook(self) -> None:
        calls: list[tuple[type[BaseException], BaseException]] = []

        def previous(exc_type: type[BaseException], exc: BaseException, traceback: object) -> None:
            calls.append((exc_type, exc))

        logger = logging.getLogger("laserlab-hook-test")
        quiet = logging.NullHandler()
        logger.addHandler(quiet)
        try:
            with patch.object(sys, "excepthook", previous):
                hook = diagnostics.install_exception_hook(logger)
                error = RuntimeError("contained")
                hook(RuntimeError, error, None)
                self.assertEqual(calls, [(RuntimeError, error)])
        finally:
            logger.removeHandler(quiet)

    def test_support_bundle_has_only_diagnostics_and_sanitized_recent_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            experiment = root / "experiment"
            experiment.mkdir()
            (experiment / "manifest.json").write_text("{}", encoding="utf-8")
            (experiment / "source-video.mp4").write_bytes(b"source media must not be exported")
            log_path = root / "laserlab.log"
            log_path.write_text(f"failure near {Path.home()} and {tempfile.gettempdir()}\n", encoding="utf-8")
            first = root / "support-a.zip"
            second = root / "support-b.zip"
            with (
                patch("laserlab.diagnostics.get_log_path", return_value=log_path),
                patch("laserlab.diagnostics._utc_now", return_value="2026-10-31T12:00:00Z"),
                patch("laserlab.diagnostics.shutil.which", return_value=None),
            ):
                diagnostics.export_support_bundle(first, experiment)
                diagnostics.export_support_bundle(second, experiment)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as bundle:
                self.assertEqual(bundle.namelist(), ["diagnostics.json", "laserlab.log"])
                record = json.loads(bundle.read("diagnostics.json"))
                log = bundle.read("laserlab.log").decode("utf-8")
                self.assertTrue(record["experiment"]["manifest_present"])
                self.assertNotIn(str(Path.home()), log)
                # Ambiguous unquoted paths consume the rest of their line.
                self.assertIn("<PATH>", log)
                self.assertNotIn("source-video.mp4", "\n".join(bundle.namelist()))
                self.assertTrue(all(member.date_time == (1980, 1, 1, 0, 0, 0) for member in bundle.infolist()))


if __name__ == "__main__":
    unittest.main()
