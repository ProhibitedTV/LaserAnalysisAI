# Wiki publication source

These Markdown files are a **version-controlled source for the GitHub Wiki**, not the live Wiki itself. GitHub Wikis are stored in a separate Git repository; adding this folder to LaserLab does **not** automatically publish it.

## Published wiki

The [live LaserLab Wiki](https://github.com/ProhibitedTV/LaserAnalysisAI/wiki) was initialized and published on October 31, 2026, with seven visitor pages and a custom sidebar. This folder remains its reviewable source. Repository source links use `.md`; published links use the Wiki's page URLs.

## Publish approved updates

A repository maintainer can:

1. Open https://github.com/ProhibitedTV/LaserAnalysisAI/wiki and use **Create the first page** if the Wiki has not yet been initialized. Name it **Home**. The repository's Wiki feature is enabled.
2. Clone the Wiki repository (a separate remote): https://github.com/ProhibitedTV/LaserAnalysisAI.wiki.git
3. Copy the Markdown pages from this folder to the root of the Wiki repository, excluding this maintainer-only **README.md**. Keep the exact names, including **Home.md** and **_Sidebar.md**. Convert local links such as `(Getting-Started.md)` to `(/ProhibitedTV/LaserAnalysisAI/wiki/Getting-Started)` so navigation opens Wiki pages rather than Markdown attachments.
4. Review all pages and links; commit and push to the Wiki remote.
5. Confirm that https://github.com/ProhibitedTV/LaserAnalysisAI/wiki shows Home, the sidebar, and working links.

Example in PowerShell from the source checkout, after reviewing any community edits on the remote:

~~~powershell
git clone https://github.com/ProhibitedTV/LaserAnalysisAI.wiki.git
$wikiPages = Get-ChildItem docs/wiki -Filter *.md | Where-Object Name -ne 'README.md'
foreach ($page in $wikiPages) {
    $body = Get-Content -LiteralPath $page.FullName -Raw
    $body = [regex]::Replace($body, '\]\(([A-Za-z0-9_-]+)\.md(#[^)]*)?\)', '](/ProhibitedTV/LaserAnalysisAI/wiki/$1$2)')
    Set-Content -LiteralPath (Join-Path LaserAnalysisAI.wiki $page.Name) -Value $body -NoNewline -Encoding utf8
}
git -C LaserAnalysisAI.wiki diff
git -C LaserAnalysisAI.wiki add -- '*.md'
git -C LaserAnalysisAI.wiki commit -m "Update LaserLab community wiki"
git -C LaserAnalysisAI.wiki push
~~~

Use a GitHub credential with appropriate permissions; do not paste passwords or tokens into commands or public issues. Verify Home, the sidebar, and every local page link after pushing. Do not copy this README into the published Wiki.

## Maintenance

Edit pages via PRs under docs/wiki and mirror approved changes to the Wiki remote. There is no automatic wiki-sync workflow in this repository. If you introduce one, use least-privilege authentication and check that it does not overwrite community edits.

See [Home.md](Home.md) for the intended Wiki landing page.
