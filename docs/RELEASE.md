# Release Guide

## Local Smoke

Use the workstation-preferred Python environment:

```powershell
.\.venv310\Scripts\python.exe -m unittest discover -s tests
.\scripts\run_fixture_demo.ps1 -Python .\.venv310\Scripts\python.exe -Experiment experiments\release-demo -MaxFrames 12 -Profile wide
.\.venv310\Scripts\python.exe scripts\capture_screenshots.py
```

The report is written under:

```text
experiments\release-demo\runs\<run-id>\report.html
```

The fixture demo also writes release screenshot inputs under `release_dumps\`.

## Build Windows Exe

```powershell
.\scripts\build_windows_exe.ps1 -Python .\.venv310\Scripts\python.exe -OutputDir dist
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
`init`, `run`, `report`, and `fixtures` commands.

## GitHub Actions

- `CI` runs on pushes and pull requests to `main`, using Python 3.10 and 3.11.
- `Windows Release` runs manually or when a `v*` tag is pushed.
- Tagged release builds upload `dist/LaserLab-windows.zip` to the GitHub release.

## Exhaustive Fixture Runs

To process every frame of a video, omit `--max-frames`:

```powershell
.\.venv310\Scripts\python.exe -m laserlab.cli init --source sample_media\commons-young-double-slit.ogv --kind video --label laser --experiment experiments\full-young --all-frames
.\.venv310\Scripts\python.exe -m laserlab.cli run --experiment experiments\full-young --profile wide --blind-seed 20260710
```

Full-frame `wide` runs generate many processed images and candidate crops. Keep
them under `experiments\`, which is intentionally ignored by Git.
