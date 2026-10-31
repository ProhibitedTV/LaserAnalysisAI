# Frequently Asked Questions

### Do I need Python or an AI account?
Not for the native desktop download. There is no required cloud account, login, or automatic upload.

### Is LaserLab connected to Veilbreak or Discord?
LaserLab optionally browses Veilbreak's published protocols and experiments using its public **read-only MCP catalog**. It links selected optical metadata to your local experiment as context only, not detector evidence. No Discord connection, automatic upload, or login is required. The live MCP bridge is pending end-to-end compatibility verification.

### How do I get a Veilbreak API key?
**You do not need a key to use LaserLab's public Veilbreak catalog.** If you want one for Veilbreak's separate read-only REST API, choose **Help > Get optional Veilbreak API key** in LaserLab or visit [Veilbreak API Access](https://veilbreak.ai/api-access). Veilbreak asks for an email address; no account is required. Keys expire after 30 days, with one active key per email. LaserLab opens the official page but does not request, receive, or store the key. Never share a key in a bug report or Discord message.

### Can I use a phone recording?
Yes, if it decodes successfully and you can record comparable laser and control footage. A stable mount and fixed exposure/focus improve interpretability.

### Can it decode mysterious symbols?
It can suggest regions and optionally run OCR. The output may be ordinary visual structure or recognition error; the software does not validate meaning or origin.

### Why do I need controls?
Without meaningful matched controls, differences may reflect ordinary camera, surface, laser, or processing artifacts. A compelling-looking image alone is not a statistical comparison.

### Why isn't Tesseract giving me text?
Tesseract is optional and may not be installed. The non-OCR detectors still work. See [Troubleshooting](Troubleshooting.md).

### What if I get no signal?
A null result for the tested metrics and footage is a valuable outcome, not a failure to find something.

### Can I share results publicly?
Yes, when lawful and consensual, after carefully reviewing the bundle and any unblinded provenance. Do not post private recordings or identifying information as part of troubleshooting.

### How can I help?
Try a demo, describe a reproducible problem using an [issue template](https://github.com/ProhibitedTV/LaserAnalysisAI/issues/new/choose), or discuss experiment design in [GitHub Discussions](https://github.com/ProhibitedTV/LaserAnalysisAI/discussions).
