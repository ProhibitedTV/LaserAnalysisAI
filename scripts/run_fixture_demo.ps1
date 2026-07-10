param(
    [string]$Python = ".\.venv310\Scripts\python.exe",
    [string]$Experiment = "experiments\release-demo",
    [int]$MaxFrames = 12,
    [string]$Profile = "wide"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Python)) {
    $pythonCommand = Get-Command $Python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python interpreter not found: $Python"
    }
    $Python = $pythonCommand.Source
}

& $Python scripts\run_fixture_demo.py --experiment $Experiment --max-frames $MaxFrames --profile $Profile --dump-dir release_dumps
