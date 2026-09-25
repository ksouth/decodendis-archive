# NDIS Decoded archive

Captures of [NDIS Decoded](https://decodendis.pplx.app), made with the [SCRAPE](https://github.com/ksouth/SCRAPE) website archiver template.

- **Captures:** under [Releases](https://github.com/ksouth/decodendis-archive/releases). Each has the site as a web archive (`.wacz`) and, because this repository sets `site_files: true`, every file of the site as ordinary files in `site-files.zip`.
- **Page list:** every page and file in a capture, linked from the dashboard's Pages count (needs GitHub Pages on).
- **Status:** [DASHBOARD.md](DASHBOARD.md), or the web page at https://ksouth.github.io/decodendis-archive/ once GitHub Pages is turned on.
- **Schedule:** captured once. Change `schedule:` in `sites.yaml` to `monthly` or `weekly` to keep capturing it.

The site's content belongs to its author. These captures are for archival reference; reuse needs their permission.

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
| `documents.zip` | Every linked document (PDF, Word, Excel, CSV, PowerPoint, ZIP and similar) as ordinary files, in folders by website and path. Includes documents the site links to on *other* websites. Split into `documents-1.zip`, `documents-2.zip`, … if very large. Not included when the site has no documents. |
| `documents.csv` | One row per document: its place in the zip, source URL, the page that linked to it, type, size, SHA-256, and whether it came from the crawl or from another site. |
| `site-files.zip`, `site-files.csv` | Only with `site_files: true`. Every file the crawl captured (HTML, CSS, scripts, images, fonts, documents) exactly as the server sent it, in folders by website and path, with an index. Useful for reusing or rebuilding a site's own files (with the owner's permission). Pages without an extension are saved as `.html`, and other files without one get an extension from their type (e.g. `.css`). |
| `doc-<id>-<name>` files | Each captured document on its own (up to 900 per capture), so the page list can link straight to it. |
| `capture-index.json` | The data behind the capture's page list (see below). |
| `crawl-report.md` | Pages captured and failed, sizes, and every linked document that could not be captured and why. Also shown as the release description. |

## Dashboard

After every run, the workflow rebuilds a dashboard with one row per site:

| Column | Shows |
|---|---|
| Site | The site's name and address. |
| Schedule | `once`, `weekly`, `monthly` or `off`; `one-off` for captures of sites not in `sites.yaml`. |
| Last capture | When the latest capture finished. The web page shows it in your local time, 12-hour, with the time zone's short name, e.g. "6:07 pm (AET)"; `DASHBOARD.md` shows UTC. |
| Status | Complete, In progress (still continuing across parts), Waiting (not captured yet), Stopped (an incomplete capture that won't continue), Off, or Failed. A failed capture links to its log, and stays marked until a later capture succeeds. |
| Pages | Pages captured, and how many failed to load. Clicking the number opens the capture's page list (see below). |
| Documents | Documents captured. Clicking the number downloads `documents.zip` straight away; its size is shown with the link. |
| Site files | Files captured with `site_files`. Clicking the number downloads `site-files.zip` straight away, with its size shown; `off` when `site_files` is off for that site. |
| Size | Total size of the capture's files. |
| Next run | Date and time of the next scheduled capture, worked out with the same rules the workflow uses; `continuing now` while a large site is between parts; `none (once)` for a site captured once. |
| Files | "Open page" opens the capture's release page, listing every file from that capture. Nothing downloads until you choose a file there. |

The web page says above the table which links download files. When a capture has several zips (a large site captured in parts), the number opens the release page instead of downloading.

Sites that aren't in `sites.yaml`, such as one-off runs, are listed separately.

### Page list for each capture

Each capture also gets a page list at `captures/<site>/<capture>/` on the web page, listing everything it captured:

1. **Home page**: the site's starting page (after any redirect).
2. **Linked from the home page**: pages the home page links to.
3. **Other pages, by folder and subdomain**: the rest, grouped as `example.org/news/`, `blog.example.org/`, and so on.
4. **Documents**: from the site, and from other websites, each with a **Download** link to that one file.

Every entry shows its name, source address (a link to the live site), and these fields:

| Field | Shows |
|---|---|
| Format | **WACZ** (in the web archive), **Site** (in `site-files.zip`), or **WACZ + Site**. Documents fetched from other websites are in neither, so show `documents.zip`. |
| Type | Web page, PDF, Word document, Excel spreadsheet, and so on. |
| Size | The file's size. |
| Captured | When it was captured, in your local time. |
| File | Where it's kept: the `.wacz` file name, and its path inside `site-files.zip` or `documents.zip`. |

A filter box at the top narrows the list as you type. Page lists need `web_page: true` and GitHub Pages turned on, and exist for captures made after this feature was added.

Choose the formats in `sites.yaml`:

```yaml
dashboard:
  markdown: true    # DASHBOARD.md in this repository, readable on GitHub
  web_page: true    # docs/index.html, a web page for GitHub Pages
```

The workflow writes the web page but can't publish it by itself: to put it online, turn on **Settings → Pages → Deploy from a branch → main, /docs** once. Set `web_page: false` if you don't want it.

Pages are captured in a real browser ([Browsertrix Crawler](https://github.com/webrecorder/browsertrix-crawler) from Webrecorder), so sites that build pages with JavaScript are captured too.

## `sites.yaml` settings

Set any of these under `defaults:` for every site, or on one site to override. The `dashboard:` section is described above.

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

## Updating a copy

A repository made from this template doesn't receive later changes to it. To update a copy, replace its `archiver/`, `tests/` and `.github/workflows/` folders with the ones from [ksouth/SCRAPE](https://github.com/ksouth/SCRAPE), and compare its `sites.yaml` comments and this README for new settings. Keep your own `sites.yaml` entries.

## Run the tests

Requires Python 3.9 or later.

```bash
pip install -r archiver/requirements.txt
python -m unittest discover -s tests
```

Capturing locally also needs Docker and the `gh` command-line tool: set `JOB` to one entry of `python -m archiver.plan`'s output and run `python -m archiver.run`.
