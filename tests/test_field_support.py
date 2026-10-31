from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from laserlab.cli import build_parser, main


class FieldSupportCliTests(unittest.TestCase):
    def test_parser_exposes_diagnostics_and_support_bundle(self) -> None:
        diagnostics = build_parser().parse_args(["diagnostics", "--format", "json"])
        support = build_parser().parse_args(["support-bundle", "--output", "support.zip"])

        self.assertEqual(diagnostics.command, "diagnostics")
        self.assertEqual(diagnostics.format, "json")
        self.assertEqual(support.command, "support-bundle")
        self.assertEqual(support.output, "support.zip")

    def test_diagnostics_json_is_printable_without_an_experiment(self) -> None:
        record = {
            "laserlab_version": "test",
            "runtime": {"python_version": "3.10", "frozen": False, "entrypoint": "source"},
            "dependencies": {},
            "ocr": {"tesseract": {"status": "unavailable"}},
            "fixtures": {"catalog_valid": True},
        }
        output = io.StringIO()
        with (
            patch("laserlab.cli.configure_logging"),
            patch("laserlab.cli.collect_diagnostics", return_value=record),
            redirect_stdout(output),
        ):
            result = main(["diagnostics", "--format", "json"])

        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue()), record)

    def test_support_bundle_command_reports_exported_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "support.zip"
            output = io.StringIO()
            with (
                patch("laserlab.cli.configure_logging"),
                patch("laserlab.cli.export_support_bundle", return_value=destination) as exporter,
                redirect_stdout(output),
            ):
                result = main(["support-bundle", "--output", str(destination)])

        self.assertEqual(result, 0)
        exporter.assert_called_once_with(destination, None)
        self.assertEqual(output.getvalue().strip(), str(destination))


if __name__ == "__main__":
    unittest.main()
