# Release Guide

## Local Smoke

For the next scientific-method build, validate [paired-capture-v2](statistical_inference.md): generated-only inputs must remain not tested; one recorded pair must remain insufficient; five declared independent exchangeable pairs use whole-pair permutations. Verify sealed pair IDs/hashes, null candidate q-values, diagnostic source classes, and versioned legacy views/exports. The older statistical checklist items below are historical and are superseded by this boundary; do not carry forward their frame-level FDR or control-pooling expectations.

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

## v0.8.2 Release Checklist

- Launch the packaged GUI from a directory unrelated to the extracted archive and confirm the bundled demo still finds its fixtures.
- Confirm a frozen build defaults experiments to a writable per-user LaserLab directory rather than the install directory.
- Confirm **Open Recent** remembers at most five existing experiment directories and stores no experiment content or labels.
- Run **System Check** with and without Tesseract; missing OCR must remain an explicit supported state.
- Export a support bundle before opening an experiment and confirm it contains only redacted diagnostics and a sanitized local log.
- Confirm diagnostics, preferences, logs, and support bundles perform no uploads or telemetry.
- Run the v0.8.1, v0.8.0, v0.7, and earlier leak/package checks unchanged.

## v0.8.1 Release Checklist

- Confirm `laserlab.theme` is the single source for dashboard and report colors, evidence tones, badges, and checklist status styling.
- Confirm normal text and every evidence status color meet the tested contrast threshold on the dark canvas.
- Confirm Setup still presents the three first-run actions and the five top-level steps remain Setup, Run, Review, Compare, Export.
- Confirm blinded/unblinded state, null results, artifacts, anomalies, candidates, warnings, and passed checks remain text-labeled as well as color-coded.
- Regenerate and visually inspect native Setup, Analysis Plan, Review, and Export screenshots on Windows.
- Run the v0.8.0 ROI/OCR, v0.7, and earlier leak/package checks unchanged.

## v0.8.0 Release Checklist

- Confirm synthetic text and grid fixtures produce ranked ROI proposals while blank, smooth-gradient, and noise fixtures fall back explicitly to `full_frame`.
- Confirm every OCR attempt names a retained ROI or `full_frame` and records engine/version, runtime, settings, boxes, text state, and failure reason.
- Confirm missing Tesseract produces an unavailable attempt without stopping non-OCR detectors.
- Confirm blinded JSON, HTML, CSV, and bundles contain ROI artifacts but no source labels, paths, or attribution.
- Confirm each top candidate exposes original, processed, ROI overlay, crop, and bounding-mask artifacts.
- Confirm the dashboard's existing Review panel toggles ROI boxes without adding a new top-level workflow step.
- Run the v0.7, v0.6, v0.5, and v0.4 leak/package checks unchanged.

## v0.7.0 Release Checklist

- Confirm normal setup still exposes only Experiment, Add Capture, Analysis Plan, and Demo, with psychophysics and community-data tools collapsed.
- Import pre-declared signal-present and signal-absent trials and verify d-prime, criterion, false-alarm rates, Wilson intervals, and extreme-rate correction.
- Confirm psychophysics trials, external references, and symbol transcriptions remain absent from every blinded artifact.
- Explicitly unblind and confirm reports keep detector, subjective, psychophysics, and external community evidence in separate sections.
- Confirm the falsification matrix includes tested and `not tested` rows for major confounds.
- Import local JSON/CSV references and symbol transcriptions; verify source hashes, attribution/license, privacy state, and context-only labels.
- Confirm URL imports are rejected and substance/dose fields do not survive as operational guidance.
- Confirm symbol and unblinded review-bundle exports require an explicit privacy acknowledgement when participant or community context is attached.
- Run the v0.6, v0.5, and v0.4 leak/package checks unchanged.

## v0.6.0 Release Checklist

- Confirm Setup presents only Experiment, Add Capture, Analysis Plan, and Demo subtasks, with advanced fields hidden by default.
- Confirm wall-projection metadata and cross-laser wavelength/pattern fields persist through manifest and unblinded reports.
- Confirm subjective context stays sealed during review and remains `context_only` after unblind.
- Confirm synthetic cross fixtures register center/arms and produce center, horizontal-arm, and vertical-arm ROIs.
- Confirm fixture/demo inputs are labeled separately from primary wall-projection footage.
- Confirm safety, reflectivity, fixed-geometry, matched-control, and saturation warnings remain visible and conservative.
- Run the v0.5 and v0.4 leak/package checks unchanged.

## v0.5.0 Release Checklist

- Confirm `quick`, `baseline`, `wide`, and `exhaustive` sampling profiles produce deterministic frame selections.
- Confirm exact/near duplicates are logged and suppressed without collapsing materially different brightness levels.
- Confirm ingestion records raw source hashes, output hashes, frame index/timestamp, media metadata, extraction settings, and provenance warnings.
- Confirm blinded notes/flags contain only blind IDs and appear in JSON, HTML, CSV, and review bundles.
- Confirm the dashboard keeps unblinding disabled until **Mark review complete** is selected.
- Confirm `matched_control`, `sensor_noise`, and `synthetic_negative` roles contribute only to the control group.
- Run the v0.4 blinded source-leak checks below unchanged.
- Push the `v0.5.0` tag only after tests, executable smoke, blinded leak audit, and bundled fixture smoke pass.

## v0.4.0 Release Checklist

- Run the bundled demo for `diffraction`, `speckle`, `ocr`, and `anomaly` with `-MaxFrames 2`.
- Confirm JSON/HTML reports include badges, q-values, protocol, detector-family summaries, and conservative interpretation text.
- Export a review bundle and inspect `manifest.json`, `report.json`, `results.json`, `environment.json`, `hashes.json`, top crops, and `README.txt`.
- Confirm blinded manifest/report/results/CSV/bundle contain no labels, source paths, provenance, or raw media.
- Explicitly unblind and confirm roles, provenance, q-values, effect sizes, and permutation statistics appear afterward.
- Build all four native archives through the `Cross-platform Release` workflow.
- Verify each platform's GUI `--smoke` and CLI `--help` checks pass.
- Push the `v0.4.0` tag only after tests, executable smoke, blinded leak audit, and bundled fixture smoke pass.
