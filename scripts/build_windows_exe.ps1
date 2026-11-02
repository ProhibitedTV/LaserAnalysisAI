param(
    [string]$Python = "python",
    [string]$OutputDir = "dist"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Python)) {
    $pythonCommand = Get-Command $Python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python interpreter not found: $Python"
    }
    $Python = $pythonCommand.Source
}

& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Python package bootstrap failed; no native build was started." }
& $Python -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Build dependency installation failed; no native build was started." }
& $Python scripts\build_release.py --output-dir $OutputDir --target windows-x86_64
if ($LASTEXITCODE -ne 0) { throw "Native release qualification failed; no successful release is claimed." }
