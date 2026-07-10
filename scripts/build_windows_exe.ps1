param(
    [string]$Python = "C:\Users\RhythmicCarnage\AppData\Local\Programs\Python\Python310\python.exe",
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
& $Python -m pip install -r requirements.txt pyinstaller
& $Python scripts\build_release.py --output-dir $OutputDir --target windows-x86_64
