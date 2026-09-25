# How the code fits together

This page explains every file that does work in this repository, and how data moves between them. You don't need it to use the template; read it when you want to change how something works.

## The short version

```text
sites.yaml ──> plan ──> run (one job per site) ──> GitHub release
                                                        │
          dashboard <── releases + capture-index.json ──┘
              │
              ├── DASHBOARD.md
              ├── docs/index.html                (the web dashboard)
              └── docs/captures/<site>/<capture>/index.html   (page lists)
```

1. **plan** reads `sites.yaml` and the existing releases, and decides which sites need capturing on this run.
2. **run** captures one site: crawls it, pulls out the documents, writes a report, and publishes a release.
3. **continue** starts another run straight away if a large site stopped part way.
4. **dashboard** rebuilds the dashboard and the page lists from all the releases, and commits them.

Nothing captured is ever committed to the repository; captures live only in releases. The only files the workflow commits are the dashboard and page lists.

## Files

### `sites.yaml`

The one file you edit. It lists the sites to capture, settings that apply to all of them, and which dashboard formats to build. See [sites-yaml.md](sites-yaml.md).

### `archiver/config.py`: reading `sites.yaml`

- `load_sites()` reads the `sites:` list, fills in each site's settings from `defaults:` and the built-in defaults, and checks them. It stops with a clear message if something is wrong (an unknown schedule, two sites with the same name, and so on).
- `slugify()` turns an address into the short name used in release tags and folder names: `https://www.ndis.gov.au/about` becomes `ndis-gov-au-about`.
- `load_dashboard_settings()` reads the `dashboard:` section.
- `DEFAULTS` holds the built-in value of every setting. It is the single source of truth: the README tables and [sites-yaml.md](sites-yaml.md) describe these values.

### `archiver/plan.py`: deciding what to capture

- Reads the list of releases (from `gh release list`) and finds each site's latest capture from its tag, `archive/<site>/<capture time>-part<N>`.
- `plan_site()` applies the rules for one site, in this order:
  1. `schedule: off`: skip.
  2. Latest capture is incomplete (a pre-release): continue it as the next part, unless it has reached `max_parts`.
  3. Never captured: capture now.
  4. `once`: skip; it's done.
  5. `weekly` or `monthly`: capture if 7 or 30 days have passed since the last capture, less 12 hours, so the daily run's changing start time never pushes a capture back a day.
- Handles the **Run workflow** form: a site name captures that site now; a URL captures any address once with default settings; a page limit applies to that run only.
- Prints a job list (`matrix`) that GitHub Actions turns into one `archive` job per site.
- `--resume-only` lists only captures that need another part. The `continue` job uses it.

### `archiver/run.py`: capturing one site

Runs inside each `archive` job. For one site it:

1. Downloads the previous part's `crawl-state.yaml` if it is continuing a capture.
2. Runs Browsertrix Crawler in Docker (`crawler_command()` builds the command from the site's settings). The crawler loads every page in a real browser and writes WARC files and a WACZ web archive.
3. Scans the WARC files with `extract.py` (`scan_collection()` combines the results from each file).
4. Fetches documents that pages link to on other websites.
5. Writes `documents.zip`, `documents.csv`, each document as its own file, `site-files.zip` (if on), `capture-index.json` and `crawl-report.md`.
6. Publishes everything as a release. If the crawler stopped at its time or size limit, the release is a pre-release with the crawler's `crawl-state.yaml`, and marked incomplete.

`CRAWLER_IMAGE` pins the crawler version; `PART_SIZE_LIMIT` (1.8 GB) keeps each part's archive under GitHub's 2 GB file limit.

### `archiver/extract.py`: reading what was captured

- `scan_warcs()` goes through every response in the WARC files once. For each successful one it:
  - records web pages for the page list: address, title, size, capture time, and the links on the page;
  - pulls out documents, recognised by file extension, by type, or by the file name the server sends;
  - with `site_files` on, keeps every file;
  - records redirects, so the page list can find the home page after a redirect.
- `fetch_offsite()` downloads document links that point to other websites, one per second, obeying robots.txt, and records failures for the report.
- `write_outputs()` writes files into a zip (split into several past 1.9 GB) and a CSV index. `zip_path()` makes safe, unique paths inside the zip and adds missing extensions (`.html` for pages, `.css` for stylesheets, and so on).
- `uncaptured_in_scope()` lists document links on the site that the crawl didn't capture, for the report.

### `archiver/pagelist.py`: the page list for each capture

- `build_index()` (called by `run.py`) turns a scan into `capture-index.json`: every page and document with its name, address, type, size, capture time, format (WACZ, Site or both) and file locations with download links.
- `find_home()` works out which captured page is the home page, following redirects and allowing for `www.` and trailing slashes.
- `render_page()` (called by `dashboard.py`) turns one capture's index files (one per part) into its page list web page.

See [dashboard-and-page-list.md](dashboard-and-page-list.md).

### `archiver/dashboard.py`: the dashboard

- Groups releases into captures, reads each capture's statistics from the hidden `capture-stats` line in its report, and marks failures from the workflow's job results.
- Works out each site's next run with `plan.py`'s own rules, so the two can't disagree.
- `render_md()` writes `DASHBOARD.md`; `render_html()` writes `docs/index.html`; `write_page_lists()` writes every capture's page list and deletes page lists for releases that no longer exist.

See [dashboard-and-page-list.md](dashboard-and-page-list.md).

### `.github/workflows/archive.yml`: the workflow

Four jobs. Details, triggers and limits are in [runs.md](runs.md).

| Job | Runs | Does |
|---|---|---|
| `plan` | every run | `python -m archiver.plan` |
| `archive` | once per site in the plan, 2 at a time | `python -m archiver.run` |
| `continue` | after `archive`, if every capture succeeded | starts the next run if a capture is incomplete |
| `dashboard` | after `archive`, even if a capture failed | downloads release data, runs `python -m archiver.dashboard`, commits the result |

### `.github/workflows/test.yml`

Runs the tests and checks `sites.yaml` whenever code or `sites.yaml` changes, so a mistake in `sites.yaml` shows up as a failed check before any capture runs.

### `tests/`

| File | Covers |
|---|---|
| `test_plan.py` | Settings, names, schedules, continuing parts, manual runs |
| `test_extract.py` | Finding documents, download links, offsite fetching, zips, file names |
| `test_run.py` | Combining results from several WARC files |
| `test_pagelist.py` | Home page, grouping, formats, download links, joining parts |
| `test_dashboard.py` | Statuses, next run, failures, links, time format, no emoji |

Tests build small WARC files in memory, so they run in under a second and need no network or Docker.

## Data that passes between steps

### Release tags

`archive/<site>/<capture time>-part<N>`, for example `archive/decodendis/20260925T095705Z-part1`. The capture time is when part 1 started, in UTC. Every part of one capture shares it. `plan.py` and `dashboard.py` both read captures from these tags, so don't rename them.

### Release files

| File | Written by | Read by |
|---|---|---|
| `<site>-<capture>-part<N>.wacz` | crawler, copied by `run.py` | you, at replayweb.page |
| `documents.zip`, `documents.csv` | `extract.write_outputs()` | you |
| `doc-<id>-<name>` | `run.py` | page list download links |
| `site-files.zip`, `site-files.csv` | `extract.write_outputs()` | you |
| `capture-index.json` | `pagelist.build_index()` | `dashboard.py` for the page list |
| `crawl-report.md` | `run.write_report()` | you (also the release description) and `dashboard.py` |
| `crawl-state.yaml` | crawler, only for incomplete parts | the next part's `run.py` |

### The hidden statistics line

The end of each `crawl-report.md` has an HTML comment that GitHub doesn't display:

```text
<!-- capture-stats {"pages": 5, "failed": 0, "documents": 0, "offsite_documents": 0, "site_files": 12} -->
```

The dashboard reads the numbers from it. Reports written before it existed are read from their tables instead.

### `capture-index.json`

One per part. Format:

```json
{
  "version": 1,
  "site": "https://decodendis.pplx.app/",
  "slug": "decodendis",
  "capture": "20260925T095705Z",
  "part": 1,
  "release_url": "https://github.com/<owner>/<repo>/releases/tag/archive/decodendis/20260925T095705Z-part1",
  "home": "https://decodendis.pplx.app/",
  "home_links": ["https://decodendis.pplx.app/burrows.html", "..."],
  "pages": [
    {"url": "...", "title": "...", "type": "Web page", "content_type": "text/html", "size": 193700,
     "captured_at": "2026-09-25T09:59:10Z", "format": "WACZ + Site",
     "files": [{"text": "<name>.wacz", "url": "<download address>"},
               {"text": "site-files.zip › decodendis.pplx.app/index.html", "url": "<download address>"}]}
  ],
  "documents": [
    {"url": "...", "name": "...", "type": "PDF", "content_type": "application/pdf", "size": 105158, "sha256": "...",
     "captured_at": "...", "source": "site", "linked_from": "...", "format": "WACZ", "files": ["..."],
     "download_url": "<address of this document's own release file>"}
  ]
}
```

`source` is `site` or `offsite` (fetched from another website). If you change the format, raise `INDEX_VERSION` in `pagelist.py`.

## Changing things safely

- Run the tests before and after: `python -m unittest discover -s tests`.
- Add a test for anything you change. Most bugs found while building this came from code paths the tests didn't go through.
- Try a change on a real site with a small page limit from the **Run workflow** form before relying on it.
- Keep `DEFAULTS`, the README and [sites-yaml.md](sites-yaml.md) in step when you add or change a setting.
