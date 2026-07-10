param(
    [string]$Python = ".\.venv310\Scripts\python.exe",
    [string]$Experiment = "experiments\release-demo",
    [int]$MaxFrames = 12,
    [string]$Profile = "wide"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python interpreter not found: $Python"
}

& $Python -m laserlab.cli init --source sample_media\commons-young-double-slit.ogv --kind video --label laser --experiment $Experiment --all-frames --max-frames $MaxFrames
& $Python -m laserlab.cli init --source sample_media\commons-double-slit-experiment.webm --kind video --label control --experiment $Experiment --all-frames --max-frames $MaxFrames
& $Python -m laserlab.cli run --experiment $Experiment --profile $Profile --blind-seed 20260710
& $Python -m laserlab.cli report --experiment $Experiment --format both
