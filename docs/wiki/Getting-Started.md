# Getting Started

LaserLab is designed for curious first-time users as well as people doing repeatable optical experiments.

## 1. Install

Open [GitHub Releases](https://github.com/ProhibitedTV/LaserAnalysisAI/releases) and choose the archive matching your system: Windows x64, Linux x64, Intel macOS, or Apple Silicon macOS (when an archive is available for that release). **Extract the complete archive**, not just the executable; keep its sample_media folder beside the app.

Launch LaserLab.exe (Windows), LaserLab (Linux), or LaserLab.app (macOS). Native bundles do not require a separate Python installation. They are currently unsigned, so review any operating-system security prompt carefully.

## 2. Try the bundled demo

Select **Run bundled demo** (in some development versions this is named **Try sample demo**). The demo checks that the analysis workflow, fixtures, and reports work.

**Important:** bundled public optical clips are educational fixtures, **not a scientifically matched laser/control pair**. Interesting demo detections should never be used as experimental evidence.

## 3. Create a real experiment

Under **Setup**, create or open an experiment folder. In **Add Capture**:
1. Add your recorded laser footage or image folder. Choose its true source role.
2. Add a matched control recorded with nearly identical camera settings, surface, angle, illumination, and beam geometry. See [Recording Matched Controls](Recording-Matched-Controls.md).
3. Enter known capture details truthfully. Unknown is better than guessing.
4. Choose an **Analysis Plan** suited to your data: diffraction, speckle, OCR/symbol recovery, or a general anomaly scan.

A source role is used by the software for blinding; labeling a recording "laser" does not itself verify the hardware or any scientific hypothesis.

## 4. Run, inspect, compare

Go to **Run**, review quality warnings and estimate the work, then run the analysis. In **Review**, examine images, crops, and proposed candidate regions **without** seeing source attribution. Save notes before revealing the roles.

After inspection, **Mark review complete**, then explicitly **Unblind and compare**. Review the matched-control statistics and caveats. An OCR fragment is a detector output, not decoded language.

## 5. Share only if you choose

Use **Export** for a blinded review bundle or a more complete report. Check that it contains no personal or restricted information before distributing. LaserLab is local-first and does not automatically upload your recordings.

Continue with [Understanding Results](Understanding-Results.md), or check [Troubleshooting](Troubleshooting.md).
