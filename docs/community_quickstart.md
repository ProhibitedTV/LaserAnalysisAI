# LaserLab: a first-time guide for the community

Welcome! LaserLab lets you examine *recorded* laser projections and ask a testable question: **do measured features appear more strongly in the laser recording than in a comparable control?**

You do not need to know Python or statistics to try the desktop app. It runs locally; it does not automatically upload your footage or connect to Discord, Veilbreak, or any other service.

## Your first 10 minutes

1. **Download and extract** the release ZIP for your operating system from [Releases](https://github.com/ProhibitedTV/LaserAnalysisAI/releases). Keep the entire extracted folder together, including `sample_media/`. Open `LaserLab.exe` on Windows, `LaserLab` on Linux, or `LaserLab.app` on macOS. The builds are unsigned; follow your operating system's normal security review rather than disabling protection globally.
2. **Click “Try sample demo”.** It runs a small practice analysis with bundled public optical videos. If it fails because sample media is missing, check that you extracted the complete release archive. The two sample clips are *not* a matched experimental pair, so the demo does **not** validate a scientific claim.
3. **Look at Review.** You will see anonymous (blinded) samples and suggested regions. A highlighted shape is a detector proposal, not necessarily a letter or symbol.
4. **When you're ready, make your own experiment.** Click **Analyze my footage** to reach the experiment step, choose a *new* folder under `experiments/`, and click **Create / Open**.
5. **Add your laser recording and a matched control.** Use **Add Capture** for each. For a first test, choose the same recording type and similar length. LaserLab proposes **Matched control** after you add the laser capture.
6. **Choose an Analysis Plan.** The general anomaly scan is a broad introduction. OCR/symbol recovery examines proposed code-like regions; diffraction and speckle modes emphasize different image properties. Save your plan and go to **Run**.
7. **Review before revealing.** Examine results without knowing which samples came from which recording. Mark the review complete, then explicitly **Unblind and compare** to see the matched-control comparison.
8. **Share optionally.** From **Export**, a blinded review bundle is the safer starting point. Review every file you share; never assume that unblinded metadata or source videos are anonymous.

## What counts as a useful control?

A *control* is footage that helps check whether the apparent pattern might come from the camera, wall, lighting, processing, or optical setup rather than the variable you are testing.

For example, when testing a material placed in the beam path, keep the camera, exposure, target, beam alignment, and room setup fixed while recording with and without that material **only if the configuration can be changed safely**. Record what changed. A blank wall recorded with a different phone, exposure, or distance is a weak comparison. Public optical clips are excellent for learning the software, but are not substitutes for your own controlled recordings.

**Laser safety:** Use appropriate training, a fixed mount and beam stop, and a non-reflective target. Never aim or align lasers toward eyes or reflective surfaces. The app does not verify your laser's class or power rating.

## Common questions

**“I can see shapes or writing. Will LaserLab decode it?”**  
It can suggest and score regions and optionally try OCR. OCR errors and familiar-looking shapes occur in ordinary images. Neither a detector score nor an OCR fragment establishes that a meaningful message is present.

**“What does 'blinded' mean?”**  
While you inspect patterns, the app hides which source is laser footage and which is a control. This helps you judge the images before knowing the answer you might expect.

**“What if the result is 'no signal'?”**  
That is a useful result: this data, detector, and control comparison did not show the tested difference. It does not settle every possible interpretation of the experience.

**“Does LaserLab prove anything metaphysical or about consciousness?”**  
No. It measures image features and reports controlled comparisons. Personal observations can be documented separately as context, not scored as optical evidence.

**“Do I need Tesseract?”**  
Only for optional OCR text attempts. Other detectors can run without it.

**“Can I send someone my experiment?”**  
Only with appropriate permission. A blinded bundle reduces source attribution but is not an automatic privacy guarantee. Avoid including names, faces, private context, or media you cannot legally redistribute.

## Help improve LaserLab

Your first-use feedback is valuable, even if you could not finish the demo. [Open a GitHub issue](https://github.com/ProhibitedTV/LaserAnalysisAI/issues/new) and tell us:

- Your operating system and LaserLab version (from `BUILD-INFO.json` if using a release bundle).
- What you clicked, what you expected, and what happened instead.
- Any error text you can share safely. Blur usernames and private file paths in screenshots.
- Whether you used the sample demo or your own recordings; **do not upload private footage just to report a bug**.

For the detailed research protocol and troubleshooting, see the [Researcher Workflow](researcher_workflow.md).
