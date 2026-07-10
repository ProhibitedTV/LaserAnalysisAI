# LaserAnalysisAI

LaserAnalysisAI is now a LaserLab blinded validation lab for laser capture
analysis. It does not claim what a signal "means"; it tests whether existing
image or video captures contain repeatable structured detections above matched
controls.

The main user-facing app is a PyQt5 desktop dashboard. The `laserlab` package
also remains available as a CLI/API path for reproducible experiments, reports,
and statistical comparison.

## LaserLab v0.3 Dashboard

Native release bundles contain:

- `LaserLab` (`LaserLab.exe` on Windows, `LaserLab.app` on macOS): desktop dashboard for experiment setup, runs, review, and export.
- `LaserLabCLI` (`LaserLabCLI.exe` on Windows): command-line interface for scripted workflows.
- `sample_media/`: redistributable public optical/interference fixture clips.
- `BUILD-INFO.json`: exact version, target, Python, operating system, and CPU architecture used for the build.

Dashboard tabs:

- `Home`: first-run actions for a bundled demo, your own footage, or an existing experiment.
- `Experiment Setup`: create/open experiments and ingest laser/control captures.
- `Protocol`: choose diffraction, speckle, OCR/symbol recovery, or general anomaly presets.
- `Run`: check protocol quality, estimate runtime, set the blind seed, and run analysis.
- `Review`: inspect evidence stats, top candidates, side-by-side images, crops, and OCR text.
- `Compare`: compare detector-family summaries across optics, texture, speckle, and symbol scores.
- `Fixtures`: review bundled known-outcome media and run a capped fixture demo.
- `Export`: create CSVs and local-first community review bundles.
- `Settings`: inspect local runtime and output paths.

![LaserLab dashboard](screenshots/release_gui_dashboard.png)
![LaserLab report summary](screenshots/release_report_summary.png)

## Quick Start

See the [Researcher Workflow](docs/researcher_workflow.md) for the complete dashboard flow, capture guidance, interpretation rules, sharing steps, and platform troubleshooting.

Use Python 3.10 or 3.11. On this workstation, the preferred interpreter is:

```powershell
$PY = "C:\Users\RhythmicCarnage\AppData\Local\Programs\Python\Python310\python.exe"
& $PY -m pip install -r requirements.txt
```

Run the dashboard from source:

```powershell
& $PY main.py
```

Run tests:

```powershell
& $PY -m unittest discover -s tests
```

Run the bundled demo through the same API layer used by the dashboard:

```powershell
.\scripts\run_fixture_demo.ps1 -Experiment experiments\release-demo -MaxFrames 2 -Profile wide -Protocol anomaly
```

## Protocol Presets

- `Diffraction / interference`: 2D FFT spectrum, fringe spacing proxy, peak/ring stability.
- `Laser speckle / scatter`: spatial speckle contrast, local variance, temporal stability proxy.
- `OCR / symbol recovery`: OCR plus connected components and synthetic known-text calibration.
- `General anomaly scan`: broad texture, edge, OCR, and persistence sweep with strict false-positive language.

Each preset keeps labels blinded during detector scoring and unblinds only for matched-control statistics.

## CLI Workflow

Create or append captures to an experiment:

```powershell
& $PY -m laserlab.cli init --source C:\captures\laser --kind image-set --label laser --experiment experiments\trial-001
& $PY -m laserlab.cli init --source C:\captures\control --kind image-set --label control --experiment experiments\trial-001
```

For video sources, use `--all-frames` to turn the frame dial fully open:

```powershell
& $PY -m laserlab.cli init --source C:\captures\laser.mp4 --kind video --label laser --experiment experiments\trial-001 --all-frames
```

Run blinded analysis:

```powershell
& $PY -m laserlab.cli run --experiment experiments\trial-001 --profile baseline --blind-seed 123
```

Run a wider preprocessing sweep:

```powershell
& $PY -m laserlab.cli run --experiment experiments\trial-001 --profile wide --protocol diffraction --blind-seed 123
```

Regenerate the latest report:

```powershell
& $PY -m laserlab.cli report --experiment experiments\trial-001 --format both
```

List or describe protocol presets:

```powershell
& $PY -m laserlab.cli protocols list
& $PY -m laserlab.cli protocols describe speckle
```

Export a local-first community review bundle:

```powershell
& $PY -m laserlab.cli bundle --experiment experiments\trial-001 --output exports\trial-001-review.zip
```

List or fetch fixture media:

```powershell
& $PY -m laserlab.cli fixtures list --include-restricted
& $PY -m laserlab.cli fixtures fetch --output sample_media
```

## Outputs

- `manifest.json`: stable experiment record with sources, captures, frame
  sampling, preprocessing profiles, detector settings, protocol plan, ROI,
  blinding seed, and output paths.
- `runs/<run-id>/results.json`: per-frame/per-variant detector records,
  OCR status, FFT/speckle/texture metrics, ROI crops, hashes, blinded IDs,
  unblinded labels, q-values, and aggregate statistics.
- `runs/<run-id>/report.html`: human-readable evidence summary with top
  candidates and null-result language.
- `*.zip` review bundle: manifest, reports, top crops, thumbnails, hashes,
  detector settings, environment info, and optional raw media.

## Evidence Ladder

Reports classify each run into one of these levels:

- `no signal`: laser scores did not exceed matched controls.
- `artifact`: detections are better explained by controls or weak differences.
- `anomaly`: elevated structure exists, but not enough for a controlled claim.
- `above-control candidate`: laser captures beat controls under permutation
  testing and effect-size thresholds.
- `repeatable candidate`: above-control evidence plus frame-to-frame persistence.

The system is intentionally conservative. A null result means this detector set
and capture set did not beat the control baseline, not that the broader idea is
disproven.

## Fixtures

The fixture catalog includes small Wikimedia Commons optical/interference videos
with explicit Creative Commons licensing, plus an external pointer to the
Illinois Wesleyan/American Journal of Physics single-photon video set. The IWU
set is scientifically stronger but stays external/manual until redistribution
terms are confirmed.

## Capture Better Footage

- Capture laser and control footage under matched camera settings, exposure, focus, distance, and surface geometry.
- Include non-diffracted laser/control footage where possible, not only blank frames.
- Avoid saturated frames; if the beam is clipped to pure white/green, many metrics become less meaningful.
- Use a stable camera or tripod so persistence and phase-registration scores are interpretable.
- Record enough frames for both laser and controls. Two frames is fine for smoke tests; real runs need more.

## Interpret Null Results

A null result is useful. It means the selected protocol, detector sweep, and capture set did not exceed matched controls under this run. It does not prove absence of a signal, and it does not settle origin claims. Repeat new blinded captures before treating any candidate as meaningful.

## What LaserLab Cannot Prove

LaserLab cannot prove metaphysical origin, intent, consciousness interaction, or that any detected structure is language. It can only report whether detector scores exceed matched controls under a reproducible local protocol.

## Build Native Release

The shared builder runs on Windows, macOS, or Linux and produces a native archive for the host platform:

```text
python scripts/build_release.py --output-dir dist
```

Windows users can use the compatibility wrapper:

```powershell
.\scripts\build_windows_exe.ps1 -OutputDir dist
```

Release archives are named by version, operating system, and architecture:

```text
dist/LaserLab-v0.3.0-windows-x86_64.zip
dist/LaserLab-v0.3.0-linux-x86_64.zip
dist/LaserLab-v0.3.0-macos-x86_64.zip
dist/LaserLab-v0.3.0-macos-arm64.zip
```

GitHub Actions builds and smoke-tests all four native bundles. Tesseract remains optional at runtime; OCR is reported as unavailable when the external Tesseract executable is not installed.

## Legacy Viewer Status

The old single-column OCR viewer has been retired from the primary app path.
Legacy helper modules remain in the repo where they still support compatibility,
but new development should target the `laserlab` engine and the LaserLab
dashboard.
