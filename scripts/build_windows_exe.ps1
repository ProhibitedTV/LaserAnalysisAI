param(
    [string]$Python = ".\.venv310\Scripts\python.exe",
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

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name LaserLab `
    --collect-all cv2 `
    --collect-all pytesseract `
    --add-data "sample_media;sample_media" `
    laserlab_launcher.py

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Copy-Item -Force -LiteralPath "README.md" -Destination $OutputDir
Copy-Item -Force -LiteralPath "LICENSE" -Destination $OutputDir
Copy-Item -Recurse -Force -LiteralPath "sample_media" -Destination $OutputDir

$zipPath = Join-Path $OutputDir "LaserLab-windows.zip"
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

Compress-Archive -Path `
    (Join-Path $OutputDir "LaserLab.exe"), `
    (Join-Path $OutputDir "README.md"), `
    (Join-Path $OutputDir "LICENSE"), `
    (Join-Path $OutputDir "sample_media") `
    -DestinationPath $zipPath

Write-Host "Built $zipPath"
