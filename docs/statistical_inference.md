# Independent capture inference

Development builds use `paired-capture-v2`. Existing native v0.8.2 downloads and old saved statistics use the previous frame-level method. This change does not modify image detectors, raw captures, preprocessing scores, source hashes, or blind-review ordering.

## Which observations count

An empirical laser capture and a user-declared `matched_control`, both classified as primary wall-projection footage, can form a comparison. Their role labels and metadata are declarations, not verified optical measurements. Ordinary `control` recordings and `sensor_noise` are separately reported descriptive controls. Synthetic negatives, generated rotations/shuffles/blanks, synthetic positive calibration, public demonstration fixtures, and unknown-origin records are also separate diagnostics. None substitutes for an empirical matched capture.

No empirical matched comparison means **not tested / exploratory**, not “no signal.” Reported camera/beam motion or saturation withholds inference. New runs also use the bounded [Pair Quality setup check](pair_quality.md): unresolved comparison details withhold otherwise eligible inference. Unrecorded settings are not silently inferred as matched, and a consistent check cannot validate the optics or prove independence. Earlier saved runs disclose that Pair Quality was not assessed.

## Declare independent pairs before running

Use a short, non-identifying `independent_pair_id` shared by exactly one laser capture and one matched control. Each pair must represent an independently acquired repeat. Also set `pair_exchangeability_acknowledged=true` only when the study design justifies exchanging condition labels within that pair under the null (for example, a suitable randomized paired design). Merely having two recordings does not establish this assumption. Missing or ambiguous declarations withhold inference; unsupported unpaired designs are not silently pooled.

The desktop fields are in advanced capture details. CLI example for one pair:

```text
python -m laserlab.cli init --experiment trial --source laser-01.mp4 --kind video --label laser --independent-pair-id pair-01 --acknowledge-pair-exchangeability
python -m laserlab.cli init --experiment trial --source control-01.mp4 --kind video --label matched_control --independent-pair-id pair-01 --acknowledge-pair-exchangeability
```

Repeat with independently acquired pairs and distinct pair IDs. Do not reuse source recordings, relabel generated images as empirical, or invent optical metadata. Unset/unknown declarations still allow descriptive analysis and blind review.

## Method and limits

1. Preserve frame/variant scores for visual diagnostics. Inference uses the normalized primary metric computed **before** within-capture persistence is added.
2. Average each frame's unique preprocessing variants. Collapse repeated raw-frame hashes within a capture, then take the median across its unique frames. Each capture contributes one score, regardless of its frame count.
3. Reject shared capture-source hashes, shared raw-frame bytes across captures, missing provenance, incomplete pairs, and multiple captures for one pair/role. These checks detect obvious reuse; different hashes cannot prove independent acquisition or rule out re-encoded derivatives.
4. Compute one laser-minus-control difference per declared independent pair. Enumerate all whole-pair sign flips up to 16 pairs; above that, use a seeded Monte Carlo sign-flip test with the conservative plus-one correction (10,000 draws by default). Never shuffle individual frames between conditions.
5. Require at least **five pairs** before reporting inference. Five is a minimum p-value resolution rule: an exact one-sided test then has 32 assignments and minimum p=1/32. It is not a power calculation or a guarantee of scientific adequacy.

The alternative is higher laser scores. A candidate requires an independent-pair p-value at most .05 and a mean capture-pair difference greater than .02 on the normalized metric. Paired Cohen dz is reported separately; it is undefined if pair differences have zero variance. The old `cohen_d` JSON key is retained for compatibility, with its revised method explicitly recorded. Confidence intervals are not estimated. Frame counts remain descriptive; independent pair and empirical capture counts are reported separately after unblinding.

Candidate q-values remain null, `candidate_q_values` is empty, and `fdr_method` says `not_estimated_related_candidates`. Correlated frames and related preprocessing variants do not establish a calibrated candidate-level null distribution. No claim of candidate FDR control is made. Repeated runs, data-dependent protocol selection, and multiple-hypothesis searches are not corrected by the single primary-metric test.

After unblinding, `source_class` distinguishes generated probes, synthetic calibration, demonstrations, empirical laser/matched captures, other recorded controls, sensor noise and unverified origin in result/candidate records and CSV exports. GUI and HTML candidate labels show that class as well as the canonical role. The class fields remain sealed in blinded exports.

Frame persistence can describe stability within a recording. It never produces `repeatable candidate` or proves across-capture/session replication, language, or origin. Pair-design assumptions and the limitations remain in reproducible reports alongside the method version, seed, permutation count, and independent sample sizes.

This distinction between repeated observations and experimental units follows the [pseudoreplication analysis by Lazic](https://pmc.ncbi.nlm.nih.gov/articles/PMC2817684/). The whole-pair exchangeability test and randomized plus-one convention follow the [paired-sample permutation description in SciPy's documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html). The implementation uses the standard library; SciPy is not a runtime dependency.

## Saved experiments and exports

Legacy results lack some provenance needed for independent-unit inference. Missing data downgrade evidence; no new pair identities or acquisition assumptions are invented. Re-run analysis with valid declarations to record the needed provenance. Old frame-level p-values, confidence intervals, and candidate q-values are superseded in current views.

For old captures without these declarations, create a separate experiment and re-import the original authorized recordings with truthful pair metadata. Do not append duplicate copies and call them new independent acquisitions. Keep the old experiment for its audit trail.

Opening an old report in the dashboard writes a separate `report.statistics-v2.json` / `.html` view. Original `results.json`, `report.json`, `report.html`, media, checkpoints, and hashes remain byte-for-byte intact. An explicit CLI `report` command regenerates the requested report artifacts, while preserving original source results. Export builds a current-method report and results view inside the ZIP without overwriting the source experiment. Older ZIPs/files already shared cannot be retroactively corrected; regenerate and review them before sharing again.

Before explicit unblinding, source roles, pair IDs, source hashes, source classes, independent-unit counts, and inferential statistics remain sealed. Only source-agnostic method/quality reminders are shown. Export does not upload anything.
