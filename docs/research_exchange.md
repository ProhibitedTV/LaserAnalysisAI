# Reviewed local results exchange

`laserlab-research-exchange-v1` is a draft, media-free LaserLab summary format for an explicitly unblinded saved run. It is not a Veilbreak submission schema, an upload API, a license grant or proof of provider acceptance. No network request occurs during preview or export. Veilbreak's documented APIs remain read-only; submission coordination is tracked in #41.

In development source, open **Export > Show community data tools > Review local results exchange**. Inspect the exact JSON, optionally include recorded source hashes or one already-linked community reference, then acknowledge consent/privacy/attribution and choose a new local file. Both options default off. Changing an option resets acknowledgement. Cancellation creates no export; saving refuses an existing destination. Existing native v0.8.2 downloads do not include this flow.

## Mapping and omissions

| Field | Meaning and boundary |
| --- | --- |
| `schema_version`, `exporter`, `analysis_software_version` | Exchange schema and current exporter version; saved analysis version is null for older runs. Package versions in development source do not identify an exact commit or establish a shipped release. |
| `review`, `experiment_purpose` | Explicit unblinding and whether review was marked complete. Practice markers persist; an absent legacy purpose stays unspecified. |
| `community_references` | Empty by default. Optionally one already-linked Veilbreak protocol/experiment numeric ID; no title, author, content, imported optical metadata or guessed canonical URL. This is context, not detector evidence. Check attribution and provider terms separately. |
| `method` | Supported protocol/metric/profile, detector IDs, bounded ROI, preprocessing/control settings, sampling mode and the same threshold constants used by the evidence ladder. Unknown/custom free text is omitted. |
| `findings` | Current `paired-capture-v2` summary, declared pair count, descriptive means, tested within-run p-value when eligible and a permanently unset candidate FDR. No new inference, pooled significance, OCR text or interpretation is created. |
| `quality` | Saved Pair Quality status/exploratory flag. Missing quality remains not assessed; export never invents a retrospective pass. |
| `primary_metric_validity` | `primary-metric-v1` completion status and empirical sample-observation counts, not independent sample sizes. Incomplete OCR is untested; unavailable, failed, null or unaudited attempts are not zeros. Raw OCR/error text is omitted. |
| `captures` | Export-local aliases and fixed source classes; allow-listed numeric/categorical setup, dimensions and recorded extraction settings. Camera, exposure and geometry prose become presence/unknown indicators. Local IDs, paths, timestamps, notes and serial numbers are omitted. |
| `recorded_source_hashes` | Absent by default. Explicit opt-in adds valid capture/original-acquisition SHA-256 values recorded at analysis time. These can link recordings and do not prove independence. Media bytes are not opened or freshly reverified. |
| `limitations`, `privacy` | Fixed boundaries and the selected export options. Omitting names is not anonymity; settings, outcomes, hashes and selected references may disclose context. |

No source media, frames/crops, participant/session IDs, stories, questionnaire answers, subjective reports, symbol transcriptions, reviewer annotations, free-form settings, API keys or credentials enter the document. The selected reference ID and optical values are user declarations, not proof of equipment calibration or publication permission.

Each capture row reflects its first saved result record, not a fresh physical measurement. Missing extraction settings stay unknown; current manifest sampling defaults do not substitute for absent saved settings. The summary alone cannot reproduce the full analysis. Use appropriately reviewed original artifacts when a reproducibility workflow requires them and sharing is authorized.

## Snapshot review and CLI

Preview hashes the saved manifest/results and the complete allow-listed document into a local review token. Saving rebuilds the preview with the same options and refuses if either source artifact or the document changed. The token and internal reference choices do not enter the exported document. Preview/export never open a sealed map or media, and legacy statistics are migrated in memory without rewriting originals.

```powershell
python -m laserlab.cli exchange preview --experiment experiments/trial
python -m laserlab.cli exchange export --experiment experiments/trial --output exports/research-exchange.json --review-token <token-from-preview> --acknowledge-privacy
```

Optional `--include-source-hashes` and the paired `--reference-kind protocol --reference-id 7` flags must be identical for preview and save. The reference must already be linked to the experiment. Keep review tokens local; inspect the document that will actually be saved before acknowledging. Neither CLI command requests a provider key or submits results.

Source, offline GUI and integration tests establish the mapping and gates. Native interaction, willing-researcher comprehension, provider approval/compatibility and an authorized contribution workflow remain separate acceptance work under #41/#48. No release follows automatically from source tests.
