# NDIS Decoded archive

Captures of https://decodendis.pplx.app, made with the [SCRAPE](https://github.com/ksouth/SCRAPE) website archiver template. Captures are under **Releases**.

## About the archiver

Archive whole websites for the record: every page as it looked, and every document they link to. List the sites in `sites.yaml`, commit, and GitHub Actions does the rest. Each capture is published as a GitHub release.

## Use it

1. Click **Use this template** (or fork this repository).
2. In your copy, open the **Actions** tab and enable workflows if GitHub asks.
3. Edit `sites.yaml` and add a site:

   ```yaml
   sites:
     - url: https://www.example.gov.au
   ```

4. Commit. The **Archive sites** workflow starts within a minute. When it finishes, the capture is under **Releases**.

To capture something once without editing `sites.yaml`, go to **Actions → Archive sites → Run workflow** and paste a URL. The same form can re-capture a listed site on demand, and can set a page limit for a quick test.

## What you get

Each capture is a release named after the site and date, with these files:

| File | What it is |
|---|---|
| `<site>-<date>-part1.wacz` | The whole site as a standard web archive. Open https://replayweb.page and choose the file to click through the site exactly as it was captured. It runs in your browser; nothing is uploaded. |
| `documents.zip` | Every linked document (PDF, Word, Excel, CSV, PowerPoint, ZIP and similar) as ordinary files, in folders by website and path. Includes documents the site links to on *other* websites. Split into `documents-1.zip`, `documents-2.zip`, … if very large. |
| `documents.csv` | One row per document: its place in the zip, source URL, the page that linked to it, type, size, SHA-256, and whether it came from the crawl or from another site. |
| `site-files.zip`, `site-files.csv` | Only with `site_files: true`. Every file the crawl captured (HTML, CSS, scripts, images, fonts, documents) exactly as the server sent it, in folders by website and path, with an index. Useful for reusing or rebuilding a site's own files (with the owner's permission). Pages without an extension are saved as `.html`. |
| `crawl-report.md` | Pages captured and failed, sizes, and every linked document that could not be captured and why. Also shown as the release description. |

Pages are captured in a real browser ([Browsertrix Crawler](https://github.com/webrecorder/browsertrix-crawler) from Webrecorder), so sites that build pages with JavaScript are captured too.

## `sites.yaml` settings

Set any of these under `defaults:` for every site, or on one site to override.

| Setting | Default | Meaning |
|---|---|---|
| `url` | (required) | Where to start. |
| `name` | from the URL | Short name used in release titles and tags. |
| `schedule` | `once` | `once`, `weekly`, `monthly`, or `off` (keep the entry but don't capture). |
| `scope` | `host` | `host`: only this host (`www.` and the bare domain both count). `domain`: include subdomains. `prefix`: only URLs under the starting path. |
| `offsite_documents` | `true` | Also download documents the site links to on other websites. |
| `site_files` | `false` | Also publish every captured file as ordinary files in `site-files.zip`. The web archive already contains them; this unpacks them. |
| `respect_robots` | `true` | Obey each site's `robots.txt`. |
| `use_sitemap` | `true` | Use the site's sitemap to find pages that aren't linked. |
| `page_limit` | `0` | Stop after this many pages (0 = no limit). |
| `exclude` | none | Regular expressions for URLs to skip, e.g. `/tag/` or `\?replytocom=`. |
| `time_limit_hours` | `5` | Crawl time per run (at most 5, because GitHub stops jobs at 6 hours). |
| `workers` | `4` | Pages loaded in parallel. |
| `document_extensions` | common document types | File extensions treated as documents. |
| `max_offsite_documents` | `2000` | Cap on documents fetched from other websites per capture. |
| `max_parts` | `50` | Stop continuing a capture after this many parts. |

## Schedules and large sites

- The workflow runs when `sites.yaml` changes and once a day. New sites are captured straight away. `weekly` and `monthly` sites are captured again when due; `once` sites are never repeated automatically.
- A run stops at the time limit, or when the archive reaches about 1.8 GB (GitHub's limit per release file is 2 GB). The capture is then published as **part 1**, marked as a pre-release, with a `crawl-state.yaml` recording where it stopped: the pages already captured and the ones still queued. The next run starts straight away and continues from there as part 2, capturing only pages not yet visited, and so on until the site is finished. Each part holds different pages; together they are the full capture. All parts share the same date in their tag: `archive/<site>/<date>-partN`.
- If a part fails, the next part waits for the daily run instead of starting straight away.
- A capture started from the **Run workflow** form with a URL isn't in `sites.yaml`, so it isn't continued automatically. For a large site, add it to `sites.yaml` instead.
- Releases have no total storage limit, and the repository itself stays small because captures are never committed.

## Limits

- Only content reachable by links (or listed in the sitemap) is captured. Search results, content behind a login, and pages that need form input are not.
- Documents are recognised by file extension, by type (PDF, Word, Excel and so on), or by the file name the server sends. Links on other websites are fetched when they end in a document extension or look like downloads (`download`, `attachment`, `/media/<number>/`, `/sites/…/files/`); anything that turns out to be a web page is skipped.
- When a page limit is set, the sitemap is not used, so a quick test follows the starting page's own links.
- Each part's `documents.zip` contains the documents found during that part.
- Releases are public if the repository is public. Use a private repository for anything that shouldn't be.

## Run the tests

Requires Python 3.9 or later.

```bash
pip install -r archiver/requirements.txt
python -m unittest discover -s tests
```

Capturing locally also needs Docker and the `gh` command-line tool: set `JOB` to one entry of `python -m archiver.plan`'s output and run `python -m archiver.run`.
