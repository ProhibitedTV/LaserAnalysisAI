# Troubleshooting

## The desktop app does not start
- Extract the *entire* release archive and keep all its files together.
- Choose the archive for your platform and CPU architecture.
- Releases are currently unsigned. Inspect system security prompts; do not globally disable operating-system protections.
- Check BUILD-INFO.json for the build version and platform.

## The demo cannot find media
Keep the sample_media directory supplied with the extracted archive. The public video fixtures are a practice set, not controlled evidence.

## Video imports but no frames appear
Some OpenCV builds cannot decode every codec. Keep your original, convert a *copy* to an ordinary H.264 MP4 or supported image sequence, and record the conversion in your experiment notes.

## OCR is unavailable
Tesseract is an optional external executable. Its absence should be reported as unavailable rather than silently treated as a failed detection. You can still use non-OCR detectors.

## Analysis appears stuck
Try a quick or baseline sampling profile and a modest frame cap. Wide and exhaustive sweeps can require many image variants and considerable processing. Review the Run estimate.

## I have a problem to report
On supported newer releases, **Help > System Check** and **Export Support Bundle** can generate sanitized diagnostics without source footage. Review even a sanitized bundle before sharing it. Never attach personal footage, full local paths, passwords, or tokens just to report a bug.

Use the [bug report form](https://github.com/ProhibitedTV/LaserAnalysisAI/issues/new/choose) with your OS, version, reproduction steps, expected result, and any safe error output.

For deeper installation and protocol details, see [Researcher Workflow](https://github.com/ProhibitedTV/LaserAnalysisAI/blob/main/docs/researcher_workflow.md).
