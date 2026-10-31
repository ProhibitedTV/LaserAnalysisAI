# Wiki publication source

These Markdown files are a **version-controlled source for the GitHub Wiki**, not the live Wiki itself. GitHub Wikis are stored in a separate Git repository; adding this folder to LaserLab does **not** automatically publish it.

## Publish the first version

A repository maintainer can:

1. Open https://github.com/ProhibitedTV/LaserAnalysisAI/wiki and use **Create the first page** if the Wiki has not yet been initialized. Name it **Home**. The repository's Wiki feature is enabled.
2. Clone the Wiki repository (a separate remote): https://github.com/ProhibitedTV/LaserAnalysisAI.wiki.git
3. Copy the Markdown pages from this folder to the root of the Wiki repository. Keep the exact names, including **Home.md** and **_Sidebar.md**.
4. Review all pages and links; commit and push to the Wiki remote.
5. Confirm that https://github.com/ProhibitedTV/LaserAnalysisAI/wiki shows Home, the sidebar, and working links.

Example after the first Wiki page has been created:

~~~sh
git clone https://github.com/ProhibitedTV/LaserAnalysisAI.wiki.git
cp docs/wiki/*.md LaserAnalysisAI.wiki/
# Remove or adapt README.md on the wiki remote; it is an editor-only guide.
cd LaserAnalysisAI.wiki
git add .
git commit -m "Publish LaserLab community wiki"
git push
~~~

On Windows without a POSIX shell, copy the files with File Explorer instead. Use a GitHub credential with appropriate permissions; do not paste passwords or tokens into commands or public issues.

## Maintenance

Edit pages via PRs under docs/wiki and mirror approved changes to the Wiki remote. There is no automatic wiki-sync workflow in this repository. If you introduce one, use least-privilege authentication and check that it does not overwrite community edits.

See [Home.md](Home.md) for the intended Wiki landing page.
