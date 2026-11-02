# Native release qualification

Development source and qualification artifacts are distinct from published native releases. The current source version is `0.9.0.dev0`; existing public v0.8.2 archives retain their original behavior.

## Producing candidates

Run the Cross-platform Release workflow manually on the reviewed commit. The reusable Python 3.10/3.11 CI workflow must pass before the four native builds start. A manual run uploads Actions artifacts and does not publish a GitHub release.

For a local host build, install the declared build dependencies in a development environment, then run:

```text
python scripts/build_release.py --output-dir dist
```

The builder requires a clean Git source tree, uses the current host's target, and rechecks commit/tree identity during packaging. Default archives include `candidate-<source revision>` in the name. Existing work/output folders and archives are retained; repeat into a fresh ignored directory such as `dist/qualification-02`, or a directory outside the checkout.

Embedded and external sample resources use the same allow-list: declared redistributable fixtures and fixed attribution/manifest/benchmark metadata. Unexpected local media are omitted. Fixture validation and packaged startup/resources/demo/diagnostics/benchmark checks must pass.

Each bundle records source commit/tree, version, channel, target and build environment in `BUILD-INFO.json`. `SHA256SUMS` covers the bundle files; the separate `.zip.sha256` identifies the complete archive. These identify the produced artifacts, not bit-for-bit reproducibility across machines or native usability.

## Qualification and publication

1. Identify the exact archive and source revision, and verify its checksum.
2. Record supported-version CI and headless package checks separately from actual native UI checks. Follow the canonical [Wiki first-user checklist](https://github.com/ProhibitedTV/LaserAnalysisAI/wiki/First-User-Check). Do not infer native or volunteer acceptance from an offscreen render or successful build.
3. Resolve release-blocking UI/integration failures. Record platform, artifact identity, steps, observations and limits without private footage or participant information. A tool/capture failure is an unverified check, not a pass or an application crash.
4. Prepare the intended version in both `laserlab/__init__.py` and `pyproject.toml` through the normal reviewed process. A tag must exactly match that version and point to the checkout being built. Tag builds retain the ordinary version/target archive name and stage a draft release after automated checks.
5. Qualify the actual draft assets before promoting that draft. Publishing must retain the verified bytes; rebuilding after acceptance would require requalification. Nonfinal version tags are marked prerelease. Do not publish while required native UI/integration/CI checks remain unresolved.

The workflow verifies archive checksums before draft creation. It cannot establish human comprehension, consent, optical validity, provider contribution authorization or interactive acceptance on unavailable platforms. Those remain explicit issue/field-review work, including #41, #44, #47 and #48.
