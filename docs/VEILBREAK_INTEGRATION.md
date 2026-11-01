# Veilbreak + LaserLab: complementary, opt-in interoperability

LaserLab is **not** a replacement for [Project Veilbreak](https://veilbreak.ai/). Veilbreak organizes the community's published protocols, experiments, and questionnaire data. LaserLab is a local desktop instrument for testing features in recorded optical footage against matched controls.

## What works in development source

- In LaserLab's **Setup**, select **Explore Veilbreak protocols**; or under **Export > Show community data tools**, choose the public protocol or experiment catalog.
- On request, LaserLab accesses Veilbreak's published, read-only MCP endpoint at `https://veilbreak.ai/api/mcp`. This catalog endpoint is documented as free and without an API key.
- Search titles, equipment and tags locally, optionally filter by reported wavelength, and use **Previous / Next** to reach the complete downloaded catalog. These filters send no search terms to the provider. The MCP list tools currently take no search or pagination parameters; the separate REST API has different capabilities.
- Choose **Use selected protocol as reference** (or experiment), create/open a local experiment, and confirm the local link. LaserLab stores the numeric Veilbreak record ID, selected reported optical metadata, and a reference to the public endpoint.
- The link is labeled `context_only` and **excluded from image-detector scoring**. It cannot change pre-specified experimental settings or override local capture metadata.
- Linking the same Veilbreak record twice updates its reference rather than duplicating it.
- No private footage, participant notes, review results, experiment paths, account credentials, or personally identifying data are sent to Veilbreak. There is no automatic background polling or data upload.
- Optional [24-hour saved public catalogs](public_catalog_cache.md) default off. Open saved is disk-only; Browse / refresh explicitly reads the service. Saved copies retain source/retrieval/expiry and an unverified per-record license status.

This is a **read-only, user-initiated bridge**. The standalone LaserLab app and current local JSON/CSV import tools work without the network.

## Getting a Veilbreak API key (optional)

The **public MCP catalog does not require a key**. LaserLab's current bridge reads this public catalog and does **not** accept, use, save, or upload API keys.

For community members who also want to use **Veilbreak's separate read-only REST API** in their own tools:

1. In LaserLab, open **Help > Get optional Veilbreak API key**, or use **Export > Show community data tools > Get optional Veilbreak API key**.
2. LaserLab opens Veilbreak's official [API Access](https://veilbreak.ai/api-access) webpage in the default browser. The webpage, not LaserLab, handles requesting the key.
3. Follow the website's instructions and provide your email address there. Veilbreak currently documents **no account required**, **one active key per email**, and **30-day validity**. Regenerating a key invalidates the previous one.
4. Keep the resulting key private. Do not paste it into Discord, GitHub issues, LaserLab experiment files, screenshots, or chat.

**This button only opens Veilbreak's official website.** It cannot create an API key on your behalf, connect authenticated REST queries inside LaserLab, extend a key's expiry, or verify that Veilbreak issued one.

Veilbreak's REST API is read-only: it does not authorize publishing or updating research results. The published URL is `https://veilbreak.ai/api-access`; sample snippets on the page may contain a different placeholder hostname, so check the provider's current documentation before using an endpoint.

## Live compatibility and limits

On November 1, 2026, a live public probe verified initialization using MCP `2025-03-26`, tool discovery, the protocol catalog, exact protocol-ID lookup and missing-ID behavior. Separate live reads verified the experiment catalog and exact experiment-ID lookup. The advertised read-only tools are `get_protocols`, `get_protocol_by_id`, `get_experiments`, `get_experiment_by_id` and `get_schema`. These are point-in-time service checks, not native UI, volunteer or authorized contribution acceptance. No collaboration or compatibility guarantee from Veilbreak maintainers is implied.

The live protocol schema nests optical values in `meta`. LaserLab reads only allow-listed fields from that object; authors, descriptions, questionnaire answers, substance/dose values and arbitrary links are excluded. The provider's `get_schema` describes wavelength in nanometers, power in milliwatts and **projection distance in feet**. The Veilbreak adapter converts that distance to meters and records the original source field in confidence metadata. An explicit `projection_distance_meters` takes precedence. Reported values remain community context, not measurements of the local setup. Existing saved references are not rewritten.

Catalogs are bounded by a 4 MiB response limit and a per-request timeout. The former 200-record truncation has been removed: every downloaded record is available through local paging. If a future MCP response signals additional server pages, LaserLab reports an unsupported partial catalog instead of silently omitting records or inventing unadvertised request parameters. Rate limits, authorization errors, unsupported negotiated versions and malformed responses produce local errors without echoing server content. Requests cannot redirect to a different endpoint.

Maintainers can repeat the sanitized live check explicitly:

```powershell
& .\.venv\Scripts\python.exe scripts/check_veilbreak.py --live
```

It sends only fixed public read requests and numeric protocol IDs. Its JSON output contains counts, tool names, unit/schema facts and a timestamp; no record titles, authors, raw content or local experiment data. Without `--live` it refuses network access. Normal CI remains offline. The provider may change or become unavailable; LaserLab never silently switches hosts or requests a key.

In the meantime, you can use **Import reference metadata** with a user-downloaded JSON or CSV file and still obtain normal local LaserLab analyses.

## Scientific boundaries

- A Veilbreak protocol is a **published community reference**, not a validated calibration of the user's physical laser/camera setup.
- Wavelength, reported power, class, pattern, and distance are descriptive fields; they must not be silently imposed on local experiments.
- Participant experiences, observed symbols, and drug/dose fields are not imported as detector evidence or operational guidance.
- The sample demo's fixtures are not matched scientific controls; use independently recorded and documented control footage.
- The app makes no claim that detected patterns are language, intentional messages, or evidence of extraordinary origin.

## Next steps for deeper collaboration

The reviewed local exchange is implemented in development source. These coordination and acceptance steps remain:

1. Agree with Veilbreak maintainers on a stable API/MCP version, schemas, rate limits, and license/attribution conventions.
2. Confirm canonical protocol-ID deep links and maintainer caching/attribution guarantees. A [local opt-in cache](public_catalog_cache.md) now implements bounded offline snapshots without claiming those guarantees.
3. Development source provides a [reviewed local results exchange](research_exchange.md) with optional linked reference IDs and recorded hashes, fixed evidence/settings fields and privacy gates. This draft format does not imply Veilbreak accepts it. Agree on an authorized contribution workflow and provider mapping before any submission.
4. Agree on a published common dataset format for control pairs, hashes, detector settings, blinded review status, and replication outcomes.
5. Keep network reads opt-in and any possible future write/upload actions separately consented, reviewed, and clearly labeled.

## API references

- [Veilbreak MCP server](https://veilbreak.ai/mcp-server) — public read-only tools and server URL.
- [Veilbreak REST API access](https://veilbreak.ai/api-access) — separate Bearer-key endpoint.
- [Veilbreak data use](https://veilbreak.ai/data-usage) — check licensing and third-party contributor restrictions before redistribution.
- [LaserLab community data](../laserlab/community_data.py) — allow-listed JSON/CSV normalization.
