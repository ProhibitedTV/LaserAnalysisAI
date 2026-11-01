# Opt-in public catalog snapshots

Development source can save a sanitized Veilbreak public protocol/experiment catalog for 24 hours of offline use. The cache defaults **off**. Existing native v0.8.2 downloads do not include it. This feature adds no background polling, provider write access or experiment database.

Under **Export > Show community data tools**, explicitly enable **Save public catalogs on this device for offline use (24 hours)**. This saves only a boolean preference and enables **Open saved protocols / experiments**. It does not itself contact the provider or save a catalog.

**Browse / refresh public protocols / experiments** makes the existing explicit public read. If saving is enabled, it writes an atomic snapshot. **Open saved** reads only local files and refuses a missing, invalid or expired snapshot. It never fetches a replacement automatically. A failed network refresh preserves the previous file and does not silently fall back to it. If the live read succeeds but persistence fails, the picker explains that those records are available only in the live view.

## Content, provenance and rights

Snapshots use `veilbreak-public-catalog-v1` under the per-user LaserLab state directory's `public-catalog-cache` folder, outside experiments. The two managed filenames are `veilbreak-protocols-v1.json` and `veilbreak-experiments-v1.json`. There is no per-record filename or path supplied by the provider.

Stored rows contain public numeric record IDs, bounded titles, numeric optical fields, bounded equipment/tag labels, fixed confidence statuses/known source-field names and forced context-only/scoring-exclusion flags. They exclude raw HTTP/MCP responses, authors, HTML bodies, questionnaires, participant reports, substance/dose fields, arbitrary links, credentials, footage and local experiments. Public labels may themselves carry context; local caching is not anonymization or permission to redistribute them. Unknown fields are removed both before writing and after reading.

Each file records the fixed source endpoint, catalog kind, retrieval/expiry timestamps, a content checksum and the [provider license-policy reference](https://veilbreak.ai/data-usage). Per-record license/attribution stays **unverified**. No specific Creative Commons grant, author credit or canonical deep link is invented. The [public MCP documentation](https://veilbreak.ai/mcp-server) describes read-only access; maintainer rate limits, caching guarantees and contribution coordination remain open under #41. The 24-hour lifetime is a conservative LaserLab limit, not a provider guarantee.

The picker labels a **Public service** versus **Saved copy** and shows both times. Linking a saved record preserves its original retrieval time and snapshot provenance, records a separate local link time, and rechecks expiration before modifying the experiment. Reported optical values remain context; they never replace local measured settings or affect detector scores. Already-linked historical references are preserved when their former cache expires or is cleared.

## Expiration and clearing

Usable lifetime is exactly 24 hours from retrieval, using timezone-aware timestamps. At the expiry boundary, or if the local clock is earlier than retrieval, opening/linking refuses and requests an explicit refresh. A future/extended lifetime, checksum mismatch, invalid schema or oversized file is rejected. The checksum detects accidental corruption; it does not authenticate the provider or prevent a local file author from editing data.

Disabling saving stops cache reads/writes through normal browsing. Existing files remain on disk until **Clear saved catalogs** is explicitly selected; expiration prevents use but does not securely erase bytes. Clear is available even when saving is off. It removes only the two fixed managed files, refuses symbolic-link targets, and leaves other files and experiments alone. There is no recursive deletion. Atomic replacement preserves an old snapshot on write failure. Responses and saved snapshots remain capped at 4 MiB.

The optional preference is normalized as an exact boolean, with old/missing values defaulting off. Navigation updates preserve it. Preference failure restores the previous UI choice. Cache controls are disabled during active work. Browsing without saving remains supported.

## Validation boundaries

Offline tests cover default-off/no-I/O behavior, explicit UI actions, opt-in persistence, expiry boundaries and link-time rechecks, original retrieval time, atomic/network failures, safe clearing, size/schema/checksum failures, field filtering and more than 200 records. Live qualification may save only public allow-listed metadata in an isolated test directory. Neither establishes native usability, volunteer acceptance, provider licensing clearance or an authorized contribution workflow.
