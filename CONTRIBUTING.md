# Contributing to LaserLab

Thanks for helping people investigate optical observations more carefully. Contributions from first-time users, scientists, designers, documentation editors, and developers are welcome.

## Where to start

- Need help or want to debate experiment design? Use [Discussions](https://github.com/ProhibitedTV/LaserAnalysisAI/discussions).
- Found a reproducible problem? Choose a structured [issue form](https://github.com/ProhibitedTV/LaserAnalysisAI/issues/new/choose).
- New to the app? Read the [LaserLab Wiki](https://github.com/ProhibitedTV/LaserAnalysisAI/wiki) and the [Researcher Workflow](docs/researcher_workflow.md).
- Want to contribute code or docs? Open a small pull request against main, stating what you tested.

## Local development

Use Python 3.10 or 3.11 and install the dependencies in requirements.txt. On desktop, run:

~~~sh
python -m pip install -r requirements.txt
python main.py
python -m unittest discover -s tests
~~~

The repository's CI compiles the app and runs tests, GUI startup smoke checks, and fixture tests. Prefer synthetic or redistributable fixtures in tests. Do not commit downloaded participant footage, private experimental material, or external datasets without redistribution rights.

## Scientific and engineering expectations

- Keep comparisons matched, blinded review meaningful, and source roles sealed until explicit unblinding.
- Do not alter evidence thresholds or statistical semantics without tests and a documented reason.
- Distinguish detected patterns from interpretations of their meaning or origin.
- Treat null results as valid; avoid suggesting that OCR fragments constitute decoded language.
- Protect privacy, accessibility, local-first operation, and cross-platform packaging.
- Document safety and study limitations clearly. No substance procurement/dosing instructions or unsafe human-subject experimentation guidance.

## Good bug reports

Include operating system, LaserLab version or BUILD-INFO.json, steps to reproduce, expected versus actual behavior, and redacted error output. Check even sanitized support bundles before attaching them.

## Wiki edits

Community guides live in the [GitHub Wiki](https://github.com/ProhibitedTV/LaserAnalysisAI/wiki), with version history in its [separate Git repository](https://github.com/ProhibitedTV/LaserAnalysisAI.wiki.git). Edit the Wiki directly or clone that repository, review your changes, and push there. Verify page and sidebar links after updating. Do not keep duplicate Wiki pages in the application repository; application, API, testing, and release documentation can remain under `docs/`.
