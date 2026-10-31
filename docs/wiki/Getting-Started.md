# Getting Started

LaserLab is designed for curious first-time users as well as people doing repeatable optical experiments.

## 1. Install

Open [GitHub Releases](https://github.com/ProhibitedTV/LaserAnalysisAI/releases) and choose the archive matching your system: Windows x64, Linux x64, Intel macOS, or Apple Silicon macOS (when an archive is available for that release). **Extract the complete archive**, not just the executable; keep its sample_media folder beside the app.

Launch LaserLab.exe (Windows), LaserLab (Linux), or LaserLab.app (macOS). Native bundles do not require a separate Python installation. They are currently unsigned, so review any operating-system security prompt carefully.

## Not technical? Start here

The walkthrough, friendly recording labels, fresh demo folders, and **Try your own footage** action described in this section are development changes for the next desktop build. Already-downloaded v0.8.2 files do not gain these controls automatically.

You can learn the app without Python, an API key, a Veilbreak login, or specialized research training. Start with **Run bundled demo** to see what the controls do; then use **Analyze my footage** when you have recordings to examine. The app creates/opens a local experiment folder, then prompts you to pick footage.

For actual research, **recordings need a fair comparison**. A matched comparison means a second recording using the same camera, surface, focus, exposure, angle, and similar lighting, changing only the variable being studied where safe. The demo clips help you practice using the software but are not suitable matched scientific controls.

Under **Setup > Add Capture**, the recording-role menu uses friendly names like **Laser recording** and **Matched comparison (same setup)**. If you add a laser recording, LaserLab suggests the matched comparison as your next recording. Choose the role that truthfully describes the file.

There is a **How it works** button on the first screen and a **Help > First-time walkthrough** menu item. You may continue with the advanced controls when ready; the beginning steps do not change the blinding or evidence requirements.

Each demo runs in a new practice folder. Its practice label stays visible during review and in saved reports and exported ZIP files. When you choose **Try your own footage**, select a separate personal experiment folder before choosing a recording. Canceling keeps the demo open. A folder already marked as a demo cannot receive personal recordings through this shortcut.

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
