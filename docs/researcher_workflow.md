# Researcher Workflow

LaserLab is a local analysis bench for asking a narrow question: do selected image features in laser footage exceed features found in matched controls under the same pipeline? It does not establish the origin or meaning of a detection.

## Install Or Download

The easiest path is the native archive for your operating system and CPU:

- Windows x64: `LaserLab-v<version>-windows-x86_64.zip`
- Linux x64: `LaserLab-v<version>-linux-x86_64.zip`
- macOS Intel: `LaserLab-v<version>-macos-x86_64.zip`
- macOS Apple Silicon: `LaserLab-v<version>-macos-arm64.zip`

Extract the complete archive before starting the app. Keep `sample_media/` next to the executable so the bundled demo remains available.

The builds are currently unsigned. On macOS, Gatekeeper may require Control-clicking `LaserLab.app`, choosing **Open**, and confirming the first launch. On Linux, restore executable permission if your archive tool removes it:

```bash
chmod +x LaserLab LaserLabCLI
```

## First Run

Use **Run bundled demo** first. It verifies that the local image stack, report generator, fixtures, and export path work without relying on personal footage. The demo frame cap is intentionally small.

Use the dashboard for interactive setup and review. Use `LaserLabCLI` for scripted batches, exhaustive frame sweeps, and reproducible automation.

## Capture A Controlled Pair

Record a laser capture and a matched control with the same camera, lens, distance, angle, focus, exposure, resolution, frame rate, compression, and scene geometry. A non-diffracted laser capture is usually a stronger control than an unrelated dark frame.

Avoid saturated footage. When large regions clip to maximum brightness, texture and edge detectors can measure camera clipping rather than optical structure. Stabilize the camera and record enough frames for comparison; two-frame runs are packaging smokes, not evidence-bearing experiments.

## Create The Experiment

In **Experiment Setup**, choose an experiment directory and add both captures. Assign the real roles there; LaserLab derives blinded IDs before scoring.

Before running, confirm the protocol quality checklist shows both laser and control inputs. A run without matched controls is exploratory and should not be interpreted above the `anomaly` level.

## Choose A Protocol

- **Diffraction / interference** emphasizes FFT peaks, spatial frequencies, fringe structure, and stability.
- **Laser speckle / scatter** emphasizes spatial and temporal speckle contrast and local variance.
- **OCR / symbol recovery** runs OCR and structure detectors with synthetic positive calibration.
- **General anomaly scan** performs a broad sweep and uses strict false-positive language.

Start with the preset that matches the optical setup. Wider preprocessing increases runtime and the number of comparisons; it does not automatically produce stronger evidence. Use an ROI only when it is defined before reviewing outcomes.

## Run And Review

Set a blind seed and save it with the experiment. In **Review**, inspect the raw frame, processed frame, candidate crop, source attribution, q-value, persistence, and detector family together. A readable OCR fragment by itself is not evidence.

Interpret the evidence ladder conservatively:

- `no signal`: selected metrics did not beat controls.
- `artifact`: control behavior or processing explains the result better.
- `anomaly`: a feature is elevated but not supported as a controlled finding.
- `above-control candidate`: the run passes configured control comparisons.
- `repeatable candidate`: above-control behavior also persists across frames or captures.

A null result is a valid result for this footage, protocol, and detector version. It does not prove that every possible signal is absent.

## Export And Share

Use **Export Review Bundle** to create a local-first archive containing the manifest, reports, settings, hashes, environment details, and top evidence crops. Leave raw media excluded unless redistribution is lawful and participants have consented to sharing it.

The bundle is designed for independent review. Share the archive unchanged so hashes and provenance remain useful.

## Troubleshooting

**OCR unavailable:** Tesseract is a separate optional executable. Install it for your operating system and make it discoverable on `PATH`. LaserLab continues with non-OCR detectors when it is absent.

**Video opens with zero frames:** the OpenCV build may not support that codec. Convert a copy to H.264 MP4 or an image sequence, retain the original file, and document the conversion in capture metadata.

**Paths fail:** extract the release before running it and prefer a short writable experiment path. Avoid network shares for initial troubleshooting.

**The run looks stuck:** wide profiles and all-frame video scans can create many variants. Use **Estimate Run**, set a frame cap for the first pass, and reserve exhaustive analysis for a confirmed workflow.

**The packaged app will not start:** run `LaserLabCLI --help` from a terminal and retain any error output. `BUILD-INFO.json` identifies the exact native build.

## Boundaries

LaserLab cannot prove language, intent, consciousness interaction, metaphysical origin, or a subjective account. It can report whether configured detectors exceed matched controls under a recorded, reproducible protocol.
