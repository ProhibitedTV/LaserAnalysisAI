# Native OCR field test (synthetic images only)

Use these two artificial images to check that the installed executable can run
CodeOfReality template comparisons without Tesseract or private research media.
Neither file has a known encoded-text label. This is a software field check,
not an independent scientific experiment.

## 1. Obtain an identified candidate

[Four-platform candidate run 45435587461](https://github.com/ProhibitedTV/LaserAnalysisAI/actions/runs/45435587461)
passed all four automated native builds on November 24, 2026. Its package
names contain source revision prefix `2453932af635`. This historical candidate
predates later OCR changes; do not confuse it with the final integrated build.
Prefer a newer fully qualified candidate when available. GitHub Actions
artifact downloads may require signing in and expire.

Choose the matching platform and extract the artifact, which contains a native
ZIP and its `.sha256` sidecar. Check the native ZIP's SHA-256 against the sidecar
before extracting it. On Windows, use `Get-FileHash -Algorithm SHA256 <zip-file>`
in PowerShell; on Linux use `sha256sum <zip-file>`; on macOS use
`shasum -a 256 <zip-file>`. Inspect the extracted `BUILD-INFO.json` for version,
source_revision, target and build_channel. Keep older installs and experiment
folders intact; extract the candidate into a new folder.

## 2. Desktop check

Open the extracted LaserLab GUI (the app bundle on macOS). Record whether
the window opens and whether Help > System Check lists the seven verified
CodeOfReality fonts separately from optional Tesseract. Record whether
Appearance > Compare CodeOfReality glyphs (experimental) can be enabled.
A missing Tesseract installation is not a missing reference font.

## 3. Optional CLI check

Save the raw [blank.pgm](blank.pgm) and [geometric.pgm](geometric.pgm)
files in the extracted candidate folder. They are plain-text portable graymap
images, not captures. Use a terminal opened in the extracted candidate folder.

Windows PowerShell:

```powershell
.\LaserLabCLI.exe font-verify --require-all
.\LaserLabCLI.exe font-ocr --image blank.pgm --variant all
.\LaserLabCLI.exe font-ocr --image geometric.pgm --variant all
```

Linux/macOS terminal:

```sh
./LaserLabCLI font-verify --require-all
./LaserLabCLI font-ocr --image blank.pgm --variant all
./LaserLabCLI font-ocr --image geometric.pgm --variant all
```

Expected: seven verified fonts and seven distinct
`codeofreality-template:<variant>` attempts for each image. The blank image
should abstain with no text and no glyph boxes. The geometric image can produce
either a match or abstention; it has no validated target label. Check
`available` and `failure_reason` independently of text. Older candidate
revisions can still echo English in shared settings; newer builds containing
#100 should report null language and script for template attempts.

## 4. Record results

- OS and architecture:
- Native ZIP filename and SHA-256 verification result:
- BUILD-INFO version, source_revision, target, build_channel:
- GUI opens / System Check / experimental toggle:
- Verified fonts count:
- Blank: available attempts, failures, unexpected text:
- Geometric: available attempts, failures, matches or abstentions:
- Old install still present, if applicable:
- Exact steps and sanitized error message:

Report software issues to [#96](https://github.com/ProhibitedTV/LaserAnalysisAI/issues/96)
or the [first-user issue #48](https://github.com/ProhibitedTV/LaserAnalysisAI/issues/48).
If additional support data is needed, review the redacted Help > Export Support
Bundle before sharing. Do not attach private recordings, participant details,
or research/review ZIPs. A completed field check does not validate OCR accuracy
on laser footage.
