# Fixture Catalog

LaserLab separates redistributable bundled fixtures from external scientific references. Bundled fixtures are small workflow and detector sanity checks; none is a matched control for a user's camera setup.

## Bundled Fixtures

| Fixture | Phenomena | License | Intended Use | Expected Behavior | Limitations |
| --- | --- | --- | --- | --- | --- |
| Double slit experiment | interference, simulation | CC BY-SA 4.0 | Structured control | Stable fringe-like spatial frequencies; no readable text expected | Rendered simulation, not physical camera footage |
| Young's double slit experiment clip | diffraction, interference | CC BY-SA 3.0 or GFDL | Optical demo input | FFT and fringe metrics should respond more strongly than OCR | Compressed educational video with unknown capture history |
| 3D interference through two pinholes | interference, diffraction, visualization | CC BY-SA 4.0 | Structured optical positive | Repeatable spectral structure expected; text recovery is not | Tomographic visualization, not raw sensor footage |
| Focused Laguerre-Gaussian beam | structured beam, diffraction, rendered control | CC BY-SA 4.0 | Non-text false-positive control | Ring and texture metrics may respond while OCR remains null | Rendered beam field, not a matched camera control |

Exact source URLs, attribution, filenames, SHA-256 hashes, and download URLs are stored in `sample_media/fixture_manifest.json`. Human-readable attribution is in `sample_media/ATTRIBUTION.md`.

## External Manual Fixture

The Illinois Wesleyan single-photon double-slit and ghost-imaging video set is listed in the in-app catalog but is not downloaded or redistributed. Its source page is <https://sun.iwu.edu/~gspaldin/SinglePhotonVideos.html>. Redistribution terms are not confirmed, so users must obtain it manually and document local provenance.

## Validation Rules

Every catalog entry must include an ID, title, media kind, analysis label, license, attribution, source page, optical phenomena, expected detector behavior, limitations, and redistribution status. Every redistributable entry must name a bundled file. Fixture demos stop before analysis if required metadata or a bundled file is missing.

## Interpretation

These fixtures prove that the software can process known optical structure and preserve provenance. They do not validate a claim about a user's footage. Evidence-bearing experiments still require controls recorded with the same camera and optical conditions as the laser capture.
