# Veilbreak + LaserLab: complementary, opt-in interoperability

LaserLab is **not** a replacement for [Project Veilbreak](https://veilbreak.ai/). Veilbreak organizes the community's published protocols, experiments, and questionnaire data. LaserLab is a local desktop instrument for testing features in recorded optical footage against matched controls.

## What works in this proposed integration

- In LaserLab's **Setup**, select **Explore Veilbreak protocols**; or under **Export > Show community data tools**, choose the public protocol or experiment catalog.
- On request, LaserLab accesses Veilbreak's published, read-only MCP endpoint at \`https://veilbreak.ai/api/mcp\`. This catalog endpoint is documented as free and without an API key.
- Choose a record from the returned list, create/open a local experiment, and confirm **Link**. LaserLab stores the numeric Veilbreak record ID, selected reported optical metadata, and a reference to the public endpoint.
- The link is labeled \`context_only\` and **excluded from image-detector scoring**. It cannot change pre-specified experimental settings or override local capture metadata.
- Linking the same Veilbreak record twice updates its reference rather than duplicating it.
- No private footage, participant notes, review results, experiment paths, account credentials, or personally identifying data are sent to Veilbreak. There is no automatic background polling or data upload.

This is a **read-only, user-initiated bridge**. The standalone LaserLab app and current local JSON/CSV import tools work without the network.

## Why the live catalog may not open

Veilbreak documents an MCP server, but its public website also describes a **separate authenticated REST API**, and its main page and MCP page advertise different historical MCP URLs. This client uses the current main-domain MCP documentation's \`https://veilbreak.ai/api/mcp\` endpoint. The website's transport behavior was not integration-tested in a live app session as part of this change. If the server changes or is unavailable, LaserLab shows an error and **does not silently switch** to an unknown host or ask for an API key.

In the meantime, you can use **Import reference metadata** with a user-downloaded JSON or CSV file and still obtain normal local LaserLab analyses.

## Scientific boundaries

- A Veilbreak protocol is a **published community reference**, not a validated calibration of the user's physical laser/camera setup.
- Wavelength, reported power, class, pattern, and distance are descriptive fields; they must not be silently imposed on local experiments.
- Participant experiences, observed symbols, and drug/dose fields are not imported as detector evidence or operational guidance.
- The sample demo's fixtures are not matched scientific controls; use independently recorded and documented control footage.
- The app makes no claim that detected patterns are language, intentional messages, or evidence of extraordinary origin.

## Next steps for deeper collaboration

These are follow-on projects, **not** features implemented by this bridge:

1. Agree with Veilbreak maintainers on a stable API/MCP version, schemas, rate limits, and license/attribution conventions.
2. Provide protocol-ID deep links and optional saved local catalog cache for offline use.
3. Add a **user-reviewed, export-only** results mapping so researchers can submit appropriate analysis metadata to Veilbreak through Veilbreak's own authorized contribution workflow.
4. Agree on a published common dataset format for control pairs, hashes, detector settings, blinded review status, and replication outcomes.
5. Keep network reads opt-in and any possible future write/upload actions separately consented, reviewed, and clearly labeled.

## API references

- [Veilbreak MCP server](https://veilbreak.ai/mcp-server) — public read-only tools and server URL.
- [Veilbreak REST API access](https://veilbreak.ai/api-access) — separate Bearer-key endpoint.
- [Veilbreak data use](https://veilbreak.ai/data-usage) — check licensing and third-party contributor restrictions before redistribution.
- [LaserLab community data](../laserlab/community_data.py) — allow-listed JSON/CSV normalization.
