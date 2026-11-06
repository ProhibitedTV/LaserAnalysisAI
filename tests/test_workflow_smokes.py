"""Fault-inject the actual Windows smoke scripts under the Actions wrapper."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")


def run_block(workflow: str, name: str) -> str:
    """Read a named literal run block without evaluating workflow expressions."""
    text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
    step = text.split(f"      - name: {name}\n", 1)[1].split("\n      - ", 1)[0]
    block = step.split("        run: |\n", 1)[1]
    lines = []
    for line in block.splitlines():
        if line.strip() and not line.startswith("          "):
            break
        lines.append(line)
    return textwrap.dedent("\n".join(lines)).strip()


@unittest.skipUnless(PWSH, "PowerShell is required for Windows workflow fault injection")
class WorkflowSmokeTests(unittest.TestCase):
    def test_each_native_failure_stops_its_step(self):
        groups = (
            ("ci.yml", "GUI smoke", 2),
            ("ci.yml", "CLI smoke", 5),
            ("ci.yml", "Fixture smoke", 4),
            ("ci.yml", "Offline synthetic benchmark", 2),
            ("ci.yml", "Protocol smoke", 4),
            ("release.yml", "Record OpenCV build configuration", 1),
            ("release.yml", "Verify source demo decoding", 1),
        )
        # Substitute only the Python payload. Each call still executes a native
        # process, so PowerShell sets LASTEXITCODE just as on a real runner.
        python = str(Path(sys.executable)).replace("'", "''")
        prefix = f"""$ErrorActionPreference = 'Stop'
$global:SmokeCalls = 0
function python {{
    $global:SmokeCalls += 1
    Write-Output "SMOKE_CALL=$global:SmokeCalls"
    $exitCode = if ($global:SmokeCalls -eq [int]$env:LASERLAB_FAIL_CALL) {{ 23 }} else {{ 0 }}
    & '{python}' -c 'import sys; sys.exit(int(sys.argv[1]))' $exitCode
}}
"""
        suffix = "\nif (Test-Path -LiteralPath variable:LASTEXITCODE) { exit $LASTEXITCODE }\n"
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "smoke.ps1"
            for workflow, name, count in groups:
                script.write_text(prefix + run_block(workflow, name) + suffix, encoding="utf-8")
                for failure in range(count + 1):
                    with self.subTest(workflow=workflow, step=name, failure=failure):
                        result = subprocess.run(
                            [PWSH, "-NoProfile", "-NonInteractive", "-File", str(script)],
                            env={**os.environ, "LASERLAB_FAIL_CALL": str(failure)},
                            capture_output=True, text=True, timeout=30,
                        )
                        self.assertEqual(result.returncode, 23 if failure else 0, result.stdout + result.stderr)
                        calls = re.findall(r"^SMOKE_CALL=(\d+)$", result.stdout, flags=re.MULTILINE)
                        self.assertEqual(len(calls), failure or count, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
