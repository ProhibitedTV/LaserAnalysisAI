# First-user field checklist

This voluntary 5–10 minute check is for the next packaged onboarding build. Record the version, platform, and build commit from `BUILD-INFO.json` and **Help > About LaserLab**. A source checkout, automated tests, or screenshots alone do not establish that a shipped native build works. The existing v0.8.2 download predates the new walkthrough and practice banner.

No Python installation, command prompt, account, API key, or internet connection is needed for the bundled sample. Internet is needed only for downloading the app or opening the optional online guides.

## Try the app

1. Download the archive for your computer and extract the entire folder. Keep `sample_media` with the app. Open **LaserLab** (on Windows, **LaserLab.exe**, rather than **LaserLabCLI.exe**).
2. Find **How it works**. Close the walkthrough and reopen it from **Help > First-time walkthrough**. Does the first screen make sense without reading GitHub?
3. Choose **Run bundled demo** and wait for Review. Confirm the visible **Practice demo** notice. The included public videos are practice fixtures, not a matched scientific experiment.
4. Inspect a proposed shape and an OCR attempt, if available. OCR is a software guess, not proof of a message. Source roles should remain hidden until you mark review complete and explicitly choose **Unblind and compare**.
5. Choose **Try your own footage**, then cancel the folder dialog. The same demo should remain open. Try again and choose a different, empty personal experiment folder. Only then should a recording picker appear; canceling that picker must not add any recording.
6. If you already have authorized local recordings, choose **Laser recording**, add the file, and check that the app asks for a **Matched comparison (same setup)**. Use a comparison with matching camera, target, focus, exposure, and geometry. Unknown equipment details should stay unknown. Do not collect or send new footage for this usability check.
7. Reopen the saved demo using **Open existing experiment** or **File > Open Recent**. Its practice label should return. Export a local review ZIP with source media unchecked. Confirm the practice warning in the report and ZIP's `README.txt`; no upload should occur.
8. Open **Help > System Check**. Missing optional Tesseract should be explained as unavailable. Try **Export Support Bundle** to a local folder, then inspect it before deciding whether to share. For a launch, file, or codec problem, use the public troubleshooting guide or **Help > Report a problem**. Merely reading guidance does not require a GitHub account.

## Tell us what confused you

- What did you expect the app to do?
- Which screen, label, or step was confusing?
- Did you run a practice demo or compare your own matched recordings?
- What would have made the next step clearer?
- Can you explain a null result in your own words? It means these measurements did not exceed the controls; it does not settle the broader claim.

Record pass/fail, exact step, expected behavior, and actual behavior. File non-sensitive findings with the [issue forms](https://github.com/ProhibitedTV/LaserAnalysisAI/issues/new/choose), referencing #48 and the build version. Remove private filenames, local paths, participant details, personal stories, keys, and identifiers from any screenshot or diagnostics. Never request or attach volunteers' personal recordings. Do not claim volunteer testing or a platform pass unless it actually occurred.

## Maintainer release gate

Run Python 3.10/3.11 integration and GUI CI, verify the controls visually in the native dashboard, then build and exercise the packaged app from an unrelated directory with networking unavailable. Check repeated demos, cancel/error paths, and source hashes for preserved personal experiments. Record native-platform and willing-volunteer results separately. Keep #48 open until the packaged field acceptance work is complete; do not cut a release solely because source tests pass.
