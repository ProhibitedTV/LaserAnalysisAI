# Pair Quality setup diagnostics

Development source includes `pair-quality-v1`, a local pre-run check of declared laser/control comparisons. Native v0.8.2 downloads do not include it. It complements [independent capture inference](statistical_inference.md); consistent checks cannot validate an experiment or establish independence.

## Use and interpretation

On **Run**, choose **Check pair quality**. The comparison table shows **Matched**, **Mismatch**, or **Unknown**, with the recorded values and a specific explanation. Camera/device, exposure, focus and compression history can be entered under advanced capture details. Fixed camera, fixed geometry, non-reflective target and unclipped projection use three states: partially checked means unknown, checked means yes, and empty means no. Unknown physical settings are not filled in automatically.

The check uses existing `independent_pair_id` declarations to compare exactly one laser and one `matched_control` capture per pair. It never creates a pair ID or changes a role. One undeclared laser/control pair can be inspected descriptively, with its design marked unknown. Ambiguous, incomplete or unassigned sets require exploratory analysis. Generated probes, calibration/demo footage, unrelated controls and sensor noise do not become empirical matched controls.

Run rechecks every declared pair in a worker. If any required check is unknown or mismatched, the desktop offers **Proceed as exploratory** or **Cancel**. Cancel does not launch analysis. Exploratory analysis retains detector outputs and blind review, while withholding inferential significance and effect-size claims. The pipeline independently recomputes the assessment, so changing a GUI preview cannot bypass the gate. A consistent assessment still needs the declared independent-pair design, minimum replication, hashes and statistical thresholds.

## Bounded measurements and limits

- Compare cached resolution, frame rate, encoding, source frame counts and duration. Known unequal frame counts/durations are descriptive coverage differences; they do not invalidate capture-level inference by themselves. Missing video timing remains unknown. Image sets have no video timing.
- Compare declared camera, exposure, focus, compression, surface, distance, optical geometry, intermediate material and lighting. Free-text comparison is literal after trimming/case folding: different wording needs review. Matching declarations are not measurements; automatic exposure/focus modes do not establish equal settings and remain unknown. Blank means unknown; record explicit absence truthfully when appropriate. Summaries show whether private text is recorded rather than repeating its contents.
- Check cached source/frame hashes within and across pairs for obvious reuse. Different hashes cannot prove independent acquisition or detect every re-encoded derivative. No full source-video hashing or decoding is repeated by Pair Quality.
- Decode at most the first, middle and last already-imported frames per capture. Only paths within the experiment's imported `frames` tree are followed. Work scales with capture pairs, not the duration of the original videos.
- Approximate clipping is the mean fraction of sampled raw pixels with any color channel at least 250/255; a fraction of at least 2% raises a warning. This heuristic is not calibrated to a camera sensor and can miss small clipped regions.
- Motion and brightness processing use previews with a maximum 256-pixel edge. Translational [OpenCV phase correlation](https://docs.opencv.org/4.x/d7/df3/group__imgproc__motion.html) needs textured images and a usable correlation response. The implementation requires grayscale standard deviation at least 3 and response at least .3 for every adjacent preview comparison. A shift over 2% of the smaller image dimension warns of apparent motion. Sparse, untextured, unreliable or incompatible previews stay unknown. Rotation, parallax, local motion and unsampled changes can be missed; moving light patterns can also resemble camera motion.
- Brightness histograms are descriptive. Laser and control intensities need not be identical; similar distributions do not verify exposure or fair optical matching.

Thresholds are conservative setup heuristics, not validated optical benchmark performance. They never modify detector scores, source media or researcher declarations. More complete optical benchmark qualification is tracked in issue #53.

## Blinding, reports and saved runs

The full assessment lives in the local integrity-checked unblind map until explicit unblinding. Sealed manifests, results, reports and ZIPs contain no role-specific assessment. Pair Quality rejects sealed reviews, and setup diagnostics are cleared from retained GUI widgets when analysis starts or a blinded report opens. There is no upload.

After unblinding, `pre_run_quality` records the version, statuses, checks, bounded observations and limitations in results and JSON/HTML/ZIP reports. It does not contain original filenames, raw hashes or private declaration text. Source media and normal provenance retain their existing privacy controls. The assessment applies to the inputs at run time, not to later edits.

Earlier saved runs were not assessed. Opening one shows **Not assessed in this saved run**, without inventing a retrospective pass. The dashboard generates a separate `report.pair-quality-v1.json` / `.html` view when needed; older statistics migrations continue to use `report.statistics-v2.*`. Original results and reports are preserved byte-for-byte. A new run records a fresh assessment. No metadata is automatically added to old captures, and prior exports are not retroactively changed.
