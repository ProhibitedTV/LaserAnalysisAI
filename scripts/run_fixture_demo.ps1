param(
    [string]$Python = "python",
    [string]$Experiment = "experiments\release-demo",
    [int]$MaxFrames = 12,
    [string]$Profile = "wide",
    [string]$Protocol = "anomaly"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Python)) {
    $pythonCommand = Get-Command $Python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python interpreter not found: $Python"
    }
    $Python = $pythonCommand.Source
}

& $Python scripts\run_fixture_demo.py --experiment $Experiment --max-frames $MaxFrames --profile $Profile --protocol $Protocol --dump-dir release_dumps
exit $LASTEXITCODE
