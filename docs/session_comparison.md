# Local session comparison

Development source includes `session-comparison-v1`. In **Compare → Compare unblinded sessions**, choose two to eight local experiment folders. Every selected run must have an explicit unblinded state, and the active review must also be unblinded. The normal single-experiment workflow remains unchanged. Existing native v0.8.2 downloads do not include this feature, and this change does not publish a release.

The view keeps per-session outcomes separate, with pseudonyms such as `S01` and `S02`. It reports empirical laser/control capture counts, frames/probes, generated diagnostics, declared independent-pair counts, processing settings, Pair Quality and camera/geometry metadata completeness. Each session's p-value, if supported, remains a **within-session** value in JSON. No combined score, p-value, effect size, FDR or pooled significance is computed.

## Four different concepts

| Term | Meaning and limit |
| --- | --- |
| Frame persistence | Adjacent-frame mask overlap within a recording. A stationary artifact can persist. |
| Repeat within capture | More observations from one acquisition. These are not independent experiments. |
| Across-capture replication | Requires distinct acquisitions, lineage and compatible design; different filenames do not establish it. |
| Independent-session replication | Requires separately acquired original sessions, compatible predeclared hypotheses and controls, and independent outcomes. Software cannot verify independence from hashes or local declarations. |

## Record a local plan before the first run

Optional fields under **Setup → Analysis Plan → Advanced** record a short non-identifying hypothesis token, the selected protocol/primary metric, and an explicit declaration about independently acquired original sessions. The fixed criterion is that each selected session must exceed its own matched controls on that same primary metric. It does not test recurrence of a particular glyph, image region or meaning.

The token is committed as a SHA-256 value; its original text is not stored. Use no names, participant IDs or private details. A commitment can still link experiments, so ordinary unblinded bundle exports with a replication plan require the existing privacy acknowledgement. The plan and its commitment remain sealed until explicit unblinding.

A plan cannot be overwritten or attached after an experiment's first saved analysis. Preserve old experiments and use a separate experiment for a different prospective plan. Recording a local plan is **not external preregistration** and cannot rule out prior knowledge, selective reporting, repeated analysis or omitted sessions. Do not select only favorable sessions and call that independent replication.

CLI equivalent, after creating a new experiment but before its first analysis:

```text
python -m laserlab.cli sessions plan --experiment experiments/session-a --hypothesis-token fringe-primary-v1 --protocol diffraction --primary-metric fft_peak_prominence --declare-independent-acquisition
```

Use the same intended hypothesis token and protocol/metric for the separately acquired planned sessions. Actual runs must use those recorded protocol/metric choices; changing them makes the comparison exploratory. Unknown acquisition assumptions should remain undeclared.

## Acquisition provenance

Advanced capture details accept an optional **Original acquisition SHA-256** (`acquisition_source_sha256`). Enter the known hash of the original acquisition, including when a selected file is a derived clip; never invent a hash to obtain a passing result. Hexadecimal case is normalized. Leave unknown lineage unset. CLI import supports `--acquisition-source-sha256`.

For an original video or image set already imported before analysis, its source hash is recorded in the local manifest; for a derived clip, the original acquisition hash must come from its documented provenance. The comparator checks original source hashes, extracted frame hashes, declared acquisition lineage and copied experiment/run identities across sessions. Nonoverlapping clips with different container/frame bytes are still flagged when they share an original lineage. Re-encoded derivatives without truthful lineage can escape byte checks; different hashes cannot prove independent acquisition.

A replication candidate requires known original acquisition hashes that agree with the selected original source bytes. Derived or unknown inputs remain useful descriptively but do not establish independent sessions. These extra checks affect the session comparator, not the existing within-session inference requirements.

## Compatibility and outcomes

The comparator checks the saved protocol, primary metric, statistics method, detector/processing configuration, ROI, OCR engine configuration and recording dimensions/FPS/encoding. It compares declared camera, exposure, focus, compression, surface, geometry, lighting, wavelength, pattern and optic details. Private values are not copied into the summary; statuses distinguish missing information from mismatches. Literal matching declarations are not verified optical measurements. A consistent Pair Quality assessment is also required for the saved run.

- **Exploratory comparison:** missing/incompatible settings, unsupported inference, unknown lineage or absent/different pre-run commitments. Individual outcomes remain visible; no replication claim is manufactured.
- **Shared source—not replication:** reused run/source/frame bytes or a shared declared original acquisition. Copies and derived clips cannot count as independent replication.
- **No positive replication:** the checks are compatible, but not every session exceeded its own matched controls. Tested nulls are distinguished from untested sessions.
- **Declared replication candidate:** all selected sessions meet the compatible locally predeclared primary criterion, have supported independent capture-pair outcomes, known distinct original provenance and explicit acquisition declarations. This remains a candidate under reported assumptions, not verified independence, validated language, proof of origin or replication of a particular visual feature.

Within-session testing still requires [independent matched pairs](statistical_inference.md) and [Pair Quality](pair_quality.md). A single video, demo fixture, synthetic benchmark, missing comparison, or high frame-persistence score cannot promote the comparison. Unsupported or incomplete saved significance is displayed as untested.

## Review and export

The on-screen table can be viewed locally without exporting. **Export local session summary** stays disabled until the user reviews the current summary and checks its privacy acknowledgement. The saved JSON omits original experiment/capture IDs, paths, dates, source/frame hashes, private metadata values, subjective reports, annotations and OCR text. Session/capture aliases are local to the selected ordering. Pseudonymization is not anonymity; outcomes and settings can still disclose context, so review before sharing.

Export rechecks the source result snapshots. If a selected run changed after review, export refuses and requests a fresh comparison. Existing files are preserved. Opening another experiment, starting a run or entering sealed review clears the previous comparison and privacy choice. There is no upload, background scan, Veilbreak write or competing database.

CLI viewing and optional export:

```text
python -m laserlab.cli sessions compare --experiments experiments/session-a experiments/session-b
python -m laserlab.cli sessions compare --experiments experiments/session-a experiments/session-b --output session-summary.json --acknowledge-privacy
```

## Saved-run compatibility

Comparison reads saved unblinded results without modifying their source artifacts or media. Legacy statistics use the existing in-memory migration. Missing prospective declarations, original lineage or saved processing configuration remain unknown; no new acquisition facts or pre-run commitments are backfilled. Legacy runs with no explicit unblinded state need a new analysis before comparison. Old standalone reports remain preserved; they do not gain a retrospective replication certification.

This feature does not alter image detectors, within-session statistics, thresholds or evidence ladders. The session comparison is a separately versioned descriptive/candidate summary. Native packaged and volunteer acceptance remain separate release work.
