# CodeOfReality font distribution permission

**Current project status (2026-11-19):** The maintainer explicitly
authorized the exact seven supplied CodeOfReality binaries for inclusion in
public GitHub and the next LaserLab release, reporting direct permission from
the creator over Discord. This provenance is recorded in
[`CODEOFREALITY_DISTRIBUTION_ATTESTATION.md`](CODEOFREALITY_DISTRIBUTION_ATTESTATION.md).
The approved source archive is now vendored as
`assets/codeofreality/CodeOfReality-authorized-fonts.tar.xz`, verified by its
SHA-256 and each font's individual SHA-256. Native builds automatically
include those fonts and a copy of the attestation. The original Discord
message's exact legal terms have not been independently inspected.

The following checklist still applies to **new, replacement, or externally
supplied font files** and any additional license conditions. Do not assume
that the maintainer's limited attestation licenses other font artwork.

LaserLab's experimental OCR can use seven user-installed CodeOfReality fonts
without the binaries appearing in the open-source repository. Shipping those
font files in the public native installer is a **separate redistribution
decision**, not covered automatically by LaserLab's software license.

The source font metadata names Chris Johnson (2026) for the Classic OTF/TTF
family and identifies Luke Hearn as a designer of the Symbols family.
These fields alone do not establish who can authorize redistribution of
every style. Confirm the applicable rights holder(s) and license(s).

## Required operator-supplied notice

For an authorized bundled build, put a UTF-8 text file named exactly
`CODEOFREALITY-PERMISSION.txt` alongside the seven verified font binaries in
the directory specified by `LASERLAB_RELEASE_FONTS_DIR`.

The file should faithfully contain or summarize the **real permission terms**
provided by the relevant rights holder(s), including:

- Rights holder or grantor and contact/identification;
- The seven font filenames (or an unambiguous reference to the complete family);
- Whether permission covers **public redistribution of font binaries** inside
  LaserLab releases, as well as glyph-reference OCR and application branding;
- Any required copyright notice, license, attribution, restrictions, dates,
  or conditions;
- The source, date, and form of permission (email, written license, etc.).

Do **not** fill the notice with speculative or placeholder permission text.
Retain the original authorization separately in the project's release records.
The packaging script checks that a notice exists and includes it in the native
apps and ZIP archive, but it cannot determine whether the legal grant is valid.

Before packaging, the operator must explicitly set
`LASERLAB_FONT_REDISTRIBUTION_CONFIRMED=yes` and supply
`LASERLAB_RELEASE_FONTS_DIR`. The builder verifies the seven font hashes
against `docs/codeofreality_font_manifest.json`, embeds the notice alongside
the fonts, and runs packaged resource and glyph-rendering checks.

### What has not been validated

Synthetic template comparisons do not establish recognition accuracy on
independent recorded laser captures, decoded language, or an external source.
Treat all reference-font matches as exploratory and retain negative controls.
