# Release Guide

## Local Smoke

Use the workstation-preferred Python environment:

```powershell
$PY = "C:\Users\RhythmicCarnage\AppData\Local\Programs\Python\Python310\python.exe"
& $PY -m unittest discover -s tests
.\scripts\run_fixture_demo.ps1 -Experiment experiments\release-demo -MaxFrames 12 -Profile wide -Protocol anomaly
& $PY -m laserlab.cli protocols list
& $PY -m laserlab.cli bundle --experiment experiments\release-demo --output release_dumps\release-demo-bundle.zip
& $PY scripts\capture_screenshots.py
```

The report is written under:

```text
experiments\release-demo\runs\<run-id>\report.html
```

The fixture demo also writes release screenshot inputs under `release_dumps\`.

## Build Windows Exe

```powershell
.\scripts\build_windows_exe.ps1 -OutputDir dist
```

Output:

```text
dist\LaserLab-windows.zip
```

The zip includes:

- `LaserLab.exe`
- `LaserLabCLI.exe`
- `README.md`
- `LICENSE`
- `sample_media\`

`LaserLab.exe` is the GUI dashboard. `LaserLabCLI.exe` keeps the scripted
`init`, `run`, `report`, `fixtures`, `protocols`, and `bundle` commands.

## GitHub Actions

- `CI` runs on pushes and pull requests to `main`, using Python 3.10 and 3.11.
- `Windows Release` runs manually or when a `v*` tag is pushed.
- Tagged release builds upload `dist/LaserLab-windows.zip` to the GitHub release.

## Exhaustive Fixture Runs

To process every frame of a video, omit `--max-frames`:

```powershell
& $PY -m laserlab.cli init --source sample_media\commons-young-double-slit.ogv --kind video --label laser --experiment experiments\full-young --all-frames
& $PY -m laserlab.cli run --experiment experiments\full-young --profile wide --protocol diffraction --blind-seed 20260710
```

Full-frame `wide` runs generate many processed images and candidate crops. Keep
them under `experiments\`, which is intentionally ignored by Git.

## v0.3 Release Checklist

- Run the bundled demo for `diffraction`, `speckle`, `ocr`, and `anomaly` with `-MaxFrames 2`.
- Confirm JSON/HTML reports include badges, q-values, protocol, detector-family summaries, and conservative interpretation text.
- Export a review bundle and inspect `manifest.json`, `report.json`, `results.json`, `environment.json`, `hashes.json`, top crops, and `README.txt`.
- Build `dist\LaserLab-windows.zip`.
- Verify `dist\LaserLab.exe --smoke` and `dist\LaserLabCLI.exe --help`.
- Push a `v0.3.0` tag only after tests, executable smoke, and bundled fixture smoke pass.
