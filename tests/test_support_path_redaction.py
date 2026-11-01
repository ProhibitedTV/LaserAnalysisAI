"""Support diagnostics must not retain private suffixes after path spaces."""
from __future__ import annotations

import json
import logging
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from laserlab import diagnostics


class SupportPathRedactionTests(unittest.TestCase):
    def test_quoted_paths_keep_surrounding_error_context_without_private_suffixes(self):
        paths = [r"D:\private study\participant-alias\capture.mov",
                 r"\\lab-server\private study\participant-alias\capture.mov",
                 "/mnt/private study/participant-alias/capture.mov",
                 r"D:\private study\observer's capture.mov",
                 r"\\?\D:\private study\participant-alias\capture.mov"]
        for path in paths:
            with self.subTest(path=path):
                original = f'File "{path}", line 4\nPermissionError: access denied'
                self.assertEqual(diagnostics._redact_text(original),
                                 'File "<PATH>", line 4\nPermissionError: access denied')

    def test_unquoted_paths_consume_the_line_but_retain_prior_context_and_next_lines(self):
        for path in (r"D:\private study\participant-alias\capture.mov",
                     r"\\lab-server\private study\participant-alias\capture.mov",
                     "/mnt/private study/participant-alias/capture.mov"):
            with self.subTest(path=path):
                self.assertEqual(diagnostics._redact_text(f"read failed code=EACCES path={path}\nretry available"),
                                 "read failed code=EACCES path=<PATH>\nretry available")

    def test_unquoted_names_with_apostrophes_or_equals_are_not_mistaken_for_boundaries(self):
        for path in (r"D:\private study\observer's private capture.mov",
                     r"D:\private study code=private\participant-alias\capture.mov"):
            self.assertEqual(diagnostics._redact_text(f"OSError: {path}\nretry available"),
                             "OSError: <PATH>\nretry available")

    def test_known_roots_retain_only_the_category_including_legacy_masked_paths(self):
        roots = [(r"C:\Users\test", "<HOME>"), (r"D:\app install", "<INSTALL>"),
                 (r"D:\scratch space", "<TEMP>")]
        with patch("laserlab.diagnostics._redaction_roots", return_value=roots):
            for root, marker in roots:
                for value in (f'"{root}\\private study\\participant-alias\\capture.mov"',
                              f"{root}\\private study\\participant-alias\\capture.mov code=FAIL",
                              f"'{marker}\\private study\\participant-alias\\capture.mov'"):
                    with self.subTest(value=value):
                        result = diagnostics._redact_text(value)
                        self.assertIn(marker, result)
                        self.assertNotIn("private study", result)
                        self.assertNotIn("participant-alias", result)
                        self.assertNotIn("capture.mov", result)

    def test_previously_partial_generic_masks_are_resanitized(self):
        for value in ("error '<PATH> study\\participant-alias\\capture.mov' done",
                      "error <PATH> study/participant-alias/capture.mov code=FAIL"):
            result = diagnostics._redact_text(value)
            self.assertNotIn("participant-alias", result)
            self.assertNotIn("capture.mov", result)
            self.assertIn("<PATH>", result)

    def test_similar_root_names_cannot_turn_absolute_paths_into_leaking_suffixes(self):
        with patch("laserlab.diagnostics._redaction_roots", return_value=[(r"C:\Users\test", "<HOME>")]):
            for path in (r"C:\Users\test-private\participant-alias\capture.mov",
                         r"C:\Users\test private\participant-alias\capture.mov"):
                self.assertEqual(diagnostics._redact_text(f"read failed: {path}"), "read failed: <PATH>")

    def test_json_escaped_paths_and_multiple_traceback_lines(self):
        original = json.dumps({"path": r"D:\private study\participant-alias\capture.mov"})
        self.assertEqual(json.loads(diagnostics._redact_text(original)), {"path": "<PATH>"})
        trace = 'File "/mnt/private study/private_module.py", line 7\nFile "D:\\other study\\private_module.py", line 4\nOSError: decode failed'
        result = diagnostics._redact_text(trace)
        self.assertNotIn("private_module", result)
        self.assertIn("line 7", result)
        self.assertIn("line 4", result)
        self.assertIn("OSError: decode failed", result)

    def test_exception_repr_with_both_quote_types_does_not_leave_a_private_suffix(self):
        path = '/mnt/private study/observer\'s "PRIVATE_ALIAS".mov'
        result = diagnostics._redact_text(str(OSError(13, "read denied", path)))
        self.assertEqual(result, "[Errno 13] read denied: '<PATH>'")
        encoded = json.dumps({"path": path})
        self.assertEqual(json.loads(diagnostics._redact_text(encoded)), {"path": "<PATH>"})

    def test_bare_roots_are_preserved_and_masking_is_idempotent(self):
        root = str(Path.home())
        for original in (root, f'"{root}"', r"path=D:\private study\capture.mov code=FAIL",
                         "File '/mnt/private study/capture.mov', line 7"):
            result = diagnostics._redact_text(original)
            self.assertEqual(diagnostics._redact_text(result), result)
        self.assertEqual(diagnostics._redact_text(root), "<HOME>")

    def test_rotating_logger_and_bundle_both_redact_private_suffixes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log_path = root / "laserlab.log"
            logger = diagnostics.configure_logging(log_path, install_hook=False)
            try:
                try:
                    raise PermissionError(13, "read denied", r"D:\private study\participant-alias\capture.mov")
                except PermissionError:
                    logger.exception("Could not read recording")
                for handler in logger.handlers:
                    handler.flush()
                written = log_path.read_text(encoding="utf-8")
                self.assertNotIn("participant-alias", written)
                self.assertNotIn("capture.mov", written)
                self.assertIn("PermissionError", written)
            finally:
                for handler in list(logger.handlers):
                    if getattr(handler, "_laserlab_managed", False):
                        logger.removeHandler(handler)
                        handler.close()

            # Re-sanitize a log written by an older release as well as new logs.
            log_path.write_text(written + "\nlegacy '<HOME>\\private study\\participant-alias\\capture.mov'\n")
            with patch("laserlab.diagnostics.get_log_path", return_value=log_path), \
                 patch("laserlab.diagnostics.shutil.which", return_value=None):
                destination = diagnostics.export_support_bundle(root / "support.zip")
            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(set(archive.namelist()), {"diagnostics.json", "laserlab.log"})
                record = json.loads(archive.read("diagnostics.json"))
                self.assertEqual(record["privacy"]["path_redaction_version"], "filesystem-paths-v2")
                content = archive.read("laserlab.log").decode("utf-8")
                self.assertNotIn("participant-alias", content)
                self.assertNotIn("capture.mov", content)
                self.assertIn("PermissionError", content)


if __name__ == "__main__":
    unittest.main()
