# Researcher Workflow

LaserLab is a local analysis bench for asking a narrow question: do selected image features in laser footage exceed features found in matched controls under the same pipeline? It does not establish the origin or meaning of a detection.

Development source provides **Run → Check pair quality** before analysis. Review missing settings and differences between declared laser/control pairs, then resolve them or explicitly proceed as exploratory. The bounded check does not validate the experiment; [Pair Quality method notes](pair_quality.md) describe the measurements, limitations and saved-run behavior. Native v0.8.2 downloads do not include this feature.

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

LaserLab remembers up to five existing experiment directories and the last source folder in a small local preferences file. It does not copy capture roles, media metadata, hashes, review notes, or experiment contents into preferences. Packaged builds place new experiments in a writable per-user LaserLab folder and resolve bundled demo media without relying on the launch directory.

## Capture A Controlled Pair

Record a laser capture and a matched control with the same camera, lens, distance, angle, focus, exposure, resolution, frame rate, compression, and scene geometry. A non-diffracted laser capture is usually a stronger control than an unrelated dark frame.

Avoid saturated footage. When large regions clip to maximum brightness, texture and edge detectors can measure camera clipping rather than optical structure. Stabilize the camera and record enough frames for comparison; two-frame runs are packaging smokes, not evidence-bearing experiments.

### Wall-Projection Template

The primary footage model is: fixed laser → optional diffraction optic/material → non-reflective wall or flat target → fixed camera. Record wavelength, reported power/class, projected pattern type, target surface, distances, geometry, room lighting, camera settings, intermediate material, and saturation status when known.

Use trained laser handling, a fixed mount, a beam stop, and a controlled non-reflective path. Never view the beam directly or align it at eye level. Treat device power/class labels as unverified until checked under the applicable safety standard. Reflective surfaces, glass, jewelry, mirrors, glossy paint, and unexpected secondary beams require separate safety review.

Useful matched controls keep camera, target, focus, exposure, and geometry fixed while changing one planned variable: laser off; intermediate layer absent; neutral optical path; sensor/dark capture; repeated session; or alternate non-glossy target. Do not change several variables and call the result matched.

## Create The Experiment

In **Setup**, use the four short subtasks: **Experiment**, **Add Capture**, **Analysis Plan**, and **Demo**. Assign real roles during capture ingestion; LaserLab derives blinded IDs before scoring. Advanced hardware, sampling, ROI, and subjective-context fields are hidden by default.

Choose a sampling profile before ingestion. `quick` is a workflow check, `baseline` is the normal starting point, `wide` samples more densely, and `exhaustive` considers every frame. Near-duplicate suppression prevents a static segment from dominating the run and records every skipped duplicate in the capture diagnostics. Provenance warnings identify missing camera, exposure, focus, compression, resolution, or frame-rate details; warnings do not invalidate a capture, but they limit what can be reproduced.

Before running, confirm the protocol quality checklist shows both laser and control inputs. A run without matched controls is exploratory and should not be interpreted above the `anomaly` level.

## Choose A Protocol

- **Diffraction / interference** emphasizes FFT peaks, spatial frequencies, fringe structure, and stability.
- **Laser speckle / scatter** emphasizes spatial and temporal speckle contrast and local variance.
- **OCR / symbol recovery** runs OCR and structure detectors with synthetic positive calibration.
- **General anomaly scan** performs a broad sweep and uses strict false-positive language.

Start with the preset that matches the optical setup. Wider preprocessing increases runtime and the number of comparisons; it does not automatically produce stronger evidence. Use an ROI only when it is defined before reviewing outcomes.

## Run And Review

Set a blind seed and save it with the experiment. In **Review**, inspect blind IDs, raw views, processed views, scored ROI overlays, candidate crops, persistence, and detector families without source attribution. Use **ROI boxes** to switch between the processed image and its detector overlay. Filter by detector family, preprocessing variant, score, persistence, or OCR output. Notes and flags are stored against blind IDs only and are included in reports and bundles. Setup and Run are locked while review remains sealed. A readable OCR fragment by itself is not evidence.

Each OCR attempt records its engine/version, ROI or `full_frame` reference, preprocessing metadata, runtime, boxes, text state, and failure reason. Empty output and an unavailable engine are different recorded outcomes. Candidate regions are proposals for review, not evidence that the region contains a symbol.

When candidate inspection is complete, choose **Mark review complete**, then **Unblind and compare**. This irreversible action restores source roles and provenance, separates generated probes from recorded controls, and evaluates the declared independent capture-pair design. Candidate q-values are not estimated for related frames/variants. Setup and Run then unlock for the next experiment.

Interpret the evidence ladder conservatively:

- `not tested`: no suitable declared empirical comparison or independent design; exploratory, not a null result.
- `insufficient independent samples`: fewer than five independent matched capture pairs; extra frames do not count as repeats.
- `no signal`: a supported capture-pair comparison did not clear the selected threshold.
- `artifact`: control behavior or processing explains the result better.
- `anomaly`: a feature is elevated but not supported as a controlled finding.
- `above-control candidate`: capture-level scores pass the declared paired permutation comparison.

Within-video persistence is descriptive and never establishes independent replication. Generated nulls and calibration images remain separate from empirical controls. In advanced capture details, declare a non-identifying **Independent matched pair ID** shared by exactly one laser recording and one `matched_control`, and acknowledge a justified within-pair exchangeable design. Leave these unset when unknown; never invent independent repeats. Read [Statistical inference](statistical_inference.md) before interpreting significance or reopening legacy results.

Evidence colors are consistent in the dashboard and HTML report: cyan for neutral or `no signal`, amber for warnings and artifacts, violet for context/anomaly states, magenta for sealed or above-control attention states, and mint for passed/repeatable states. Every state remains labeled in text for accessibility and auditability.

A null result is a valid result for this footage, protocol, and detector version. It does not prove that every possible signal is absent.

Subjective perception notes are optional context, not image evidence. Use only pseudonymous session IDs, review privacy before sharing, and keep participant work under appropriate legal, ethical, consent, and safety review outside LaserLab. The app provides no substance procurement, dosing, administration, or intoxication instructions.

## Optional Falsification Modules

Open **Show advanced analysis controls** only when the protocol declares a separate yes/no discrimination task. Import JSON or CSV with stimulus truth, yes/no response, confidence from 0 to 1, and optional pseudonymous trial IDs and timestamps. Include both signal-present and signal-absent trials; without false-alarm controls, LaserLab will not calculate d-prime or criterion.

Imported trials remain sealed during image review. After unblind, the report shows participant sensitivity and response bias in a psychophysics section separate from camera detectors, and lists untested confounds instead of silently omitting them.

The collapsed community-data tools under **Export** accept local JSON/CSV only. External metadata and symbol transcriptions are hashed and labeled `context_only`; they cannot affect detector scores. Review pseudonymous IDs, licensing, attribution, and privacy before export. LaserLab does not connect to or scrape Veilbreak or any other service automatically.

## Export And Share

Use **Export Review Bundle** to create a local-first archive containing the manifest, reports, settings, hashes, environment details, original/processed candidates, ROI overlays, masks, and top evidence crops. A blinded bundle remains attribution-safe and cannot include source media. After unblind, leave raw media excluded unless redistribution is lawful and participants have consented to sharing it.

The bundle is designed for independent review. Share the archive unchanged so hashes and provenance remain useful. Unblinded exports containing subjective, psychophysics, or imported community context require an explicit privacy acknowledgement in the GUI or `--acknowledge-privacy` in the CLI.

## Troubleshooting

Start with **Help > System Check**. It reports the LaserLab and Python versions, packaged-runtime state, detector dependencies, bundled fixture readiness, and optional Tesseract status. OCR being unavailable is a supported state, not a failed installation.

Use **Help > Export Support Bundle** or `LaserLabCLI support-bundle --output LaserLab-support.zip` when reporting a problem. The archive contains redacted diagnostics and a sanitized recent application log. It does not include source media, capture labels, experiment manifests, participant context, or unredacted home/install paths. Review any file before sharing it.

**OCR unavailable:** Tesseract is a separate optional executable. Install it for your operating system and make it discoverable on `PATH`. LaserLab continues with non-OCR detectors when it is absent.

**Video opens with zero frames:** the OpenCV build may not support that codec. Convert a copy to H.264 MP4 or an image sequence, retain the original file, and document the conversion in capture metadata.

**Paths fail:** extract the release before running it. Packaged builds default to a per-user LaserLab experiment folder; choose another short writable path when needed. Avoid network shares for initial troubleshooting.

**The run looks stuck:** wide profiles and all-frame video scans can create many variants. Use **Estimate Run**, set a frame cap for the first pass, and reserve exhaustive analysis for a confirmed workflow.

**The packaged app will not start:** run `LaserLabCLI diagnostics --format json` from a terminal, then create a support bundle if possible. `BUILD-INFO.json` identifies the exact native build.

## Boundaries

LaserLab cannot prove language, intent, consciousness interaction, metaphysical origin, or a subjective account. It can report whether configured detectors exceed matched controls under a recorded, reproducible protocol.
