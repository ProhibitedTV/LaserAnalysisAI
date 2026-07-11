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

## Build Native Bundles

The platform-neutral builder packages the GUI, CLI, fixtures, attribution, license, and build metadata. Run it on the target operating system because PyInstaller does not cross-compile:

```text
python scripts/build_release.py --output-dir dist
```

On Windows, the existing wrapper installs build dependencies and delegates to the shared builder:

```powershell
.\scripts\build_windows_exe.ps1 -OutputDir dist
```

Outputs are target-specific:

```text
dist/LaserLab-v<version>-windows-x86_64.zip
dist/LaserLab-v<version>-linux-x86_64.zip
dist/LaserLab-v<version>-macos-x86_64.zip
dist/LaserLab-v<version>-macos-arm64.zip
```

The zip includes:

- `LaserLab`, `LaserLab.exe`, or `LaserLab.app`, depending on the platform
- `LaserLabCLI` or `LaserLabCLI.exe`
- `README.md`
- `LICENSE`
- `sample_media/`
- `BUILD-INFO.json`

`LaserLab.exe` is the GUI dashboard. `LaserLabCLI.exe` keeps the scripted
`init`, `run`, `report`, `fixtures`, `protocols`, and `bundle` commands.

## GitHub Actions

- `CI` runs on pushes and pull requests to `main`, using Python 3.10 and 3.11.
- `Cross-platform Release` runs manually or when a `v*` tag is pushed.
- The build matrix covers Windows x64, Linux x64, macOS Intel, and macOS Apple Silicon.
- Each native executable is smoke-tested before its archive is uploaded.
- Tagged builds publish all four archives to one GitHub release only after every platform succeeds.

## Exhaustive Fixture Runs

To process every frame of a video, omit `--max-frames`:

```powershell
& $PY -m laserlab.cli init --source sample_media\commons-young-double-slit.ogv --kind video --label laser --experiment experiments\full-young --all-frames
& $PY -m laserlab.cli run --experiment experiments\full-young --profile wide --protocol diffraction --blind-seed 20260710
```

Full-frame `wide` runs generate many processed images and candidate crops. Keep
them under `experiments\`, which is intentionally ignored by Git.

## v0.4.0 Release Checklist

- Run the bundled demo for `diffraction`, `speckle`, `ocr`, and `anomaly` with `-MaxFrames 2`.
- Confirm JSON/HTML reports include badges, q-values, protocol, detector-family summaries, and conservative interpretation text.
- Export a review bundle and inspect `manifest.json`, `report.json`, `results.json`, `environment.json`, `hashes.json`, top crops, and `README.txt`.
- Confirm blinded manifest/report/results/CSV/bundle contain no labels, source paths, provenance, or raw media.
- Explicitly unblind and confirm roles, provenance, q-values, effect sizes, and permutation statistics appear afterward.
- Build all four native archives through the `Cross-platform Release` workflow.
- Verify each platform's GUI `--smoke` and CLI `--help` checks pass.
- Push the `v0.4.0` tag only after tests, executable smoke, blinded leak audit, and bundled fixture smoke pass.
