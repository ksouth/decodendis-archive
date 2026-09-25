# The dashboard and page lists

After every run, the workflow's `dashboard` job rebuilds:

| What | Where | Built by |
|---|---|---|
| Dashboard, as a page on GitHub | `DASHBOARD.md` | `dashboard.render_md()` |
| Dashboard, as a web page | `docs/index.html` | `dashboard.render_html()` |
| Page list for each capture | `docs/captures/<site>/<capture>/index.html` | `pagelist.render_page()` |

and commits them as **github-actions[bot]** with the message "Update dashboard". Choose which to build in the `dashboard:` section of `sites.yaml` ([sites-yaml.md](sites-yaml.md)).

## Putting the web pages online

The web dashboard and page lists are ordinary files in `docs/`. To publish them, turn on **Settings → Pages → Deploy from a branch → main, /docs** once. They then appear at `https://<owner>.github.io/<repo>/`, updated about a minute after each run. If Pages is off, the run's summary shows a notice saying so; `DASHBOARD.md` works either way.

Everything in `docs/captures/` is rebuilt from scratch each time, so don't put your own files there. Page lists for deleted releases disappear on the next run.

## The dashboard

One card per site (on narrow screens) or one row per site (on wide screens). Sites in `sites.yaml` come first, then **One-off captures**: sites captured from the Run workflow form, or removed from `sites.yaml`.

| Field | Where it comes from |
|---|---|
| Site, address | `sites.yaml`, or the first line of the crawl report for one-off captures |
| Schedule | `sites.yaml`; `one-off` for sites not in it |
| Last capture | When the latest part of the latest capture was published |
| Status | See below |
| Pages | Pages captured, and failed, across every part of the latest capture. Links to the page list. |
| Documents | Documents captured, including from other websites. Downloads `documents.zip`. |
| Site files | Files in `site-files.zip` (downloads it), or `off` |
| Size | Total size of all the capture's release files |
| Next run | See below |
| Files | The capture's release page |

The numbers come from the hidden `capture-stats` line at the end of each crawl report ([code.md](code.md#the-hidden-statistics-line)).

### Status

Checked in this order:

| Status | Meaning |
|---|---|
| Failed | The site's most recent capture job failed after its latest successful capture. Links to the job's log. Cleared by the next successful capture. |
| Waiting | Never captured yet; it will be at the next run. |
| Off | `schedule: off` and never captured. |
| In progress | The latest capture stopped at a time or size limit and will continue as another part. |
| Stopped | An incomplete capture that won't continue: it reached `max_parts`, the site is `off`, or it isn't in `sites.yaml`. |
| Complete | The latest capture finished. |

Failures are found by reading the jobs of the current run and the 20 most recent failed runs.

### Next run

Worked out by stepping through upcoming daily runs and asking `plan.py` whether it would capture the site at each, so the dashboard and the scheduler always agree.

| Shows | When |
|---|---|
| a date and time | The next daily run that will capture it (for `weekly`, `monthly`, or not yet captured) |
| continuing now | A large site between parts; the next part starts as soon as this one finishes |
| none (once) | A `once` site that has been captured |
| never (off) | `schedule: off` |
| — | Stopped captures and one-off captures |

The daily run time is read from the `cron:` line in `.github/workflows/archive.yml`.

### Times

The web page shows times in the viewer's own time zone, 12-hour, with a short zone name: "25 Sept 2026, 6:07 pm (AET)". The page is built with UTC times, and a small script converts them in the browser. `DASHBOARD.md` shows UTC, because a page on GitHub can't know your time zone.

The short name is the browser's own abbreviation where it has one (such as "PT"), otherwise the initials of the zone's full name ("Australian Eastern Time" becomes "AET").

## The page list

One page per capture, combining every part of it. It lists everything the capture found, in this order:

1. **Home page**: the captured page for the site's starting address, following redirects and allowing for `www.` and a trailing slash. If none matches, the first page captured.
2. **Linked from the home page**: pages the home page links to, in the order they appear on it.
3. **Other pages, by folder and subdomain**: everything else, grouped by host and the first folder of the address (`www.example.org/news/`, `www.example.org/ (top level)`, `blog.example.org/ ...`). The site's own host comes first, then other hosts in alphabetical order.
4. **Documents**: "From this website", then "From other websites".

Each page is listed once, even if several parts captured it.

### Fields

| Field | Meaning |
|---|---|
| Name | The page's title, or the document's file name |
| Address | The original address, linked to the live website (which may have changed since) |
| Download | Documents only: downloads that one document from the release |
| Format | `WACZ` if it's in the web archive, `Site` if it's in `site-files.zip`, `WACZ + Site` if both. Documents from other websites are in neither and show `documents.zip`. |
| Type | Web page, PDF, Word document, and so on |
| Size | The file's size as captured |
| Captured | When the crawler received it, in your local time |
| File | Every file it's kept in; each name downloads that file. The web archive (`.wacz`), and `site-files.zip › <path>` or `documents.zip › <path>` for its place inside a zip. |
| Linked from | Documents only: the first page found linking to it |

The filter box hides everything that doesn't contain what you type, anywhere in the entry.

### Document downloads

Each document is uploaded to the release as its own file, named `doc-<first 8 characters of its SHA-256>-<name>`, with only safe characters so its address is predictable. A release can hold 1000 files, so when a capture has more than 900 documents they are only in `documents.zip`, and the page list says so. Documents over 2 GB are also only in the zip.

A single document can't be opened inside the web archive from a link, because GitHub doesn't let other websites load release files directly. To see pages as they were, download the `.wacz` and open it at [replayweb.page](https://replayweb.page).

### Size

A page list is a single web page. A capture of a few thousand pages makes a page list of a few megabytes, which loads fine. For very large captures (tens of thousands of pages) it loads more slowly, and the filter takes a moment.

## Changing how they look

- Dashboard: `HTML_TEMPLATE` and `render_html()` in `archiver/dashboard.py`; `render_md()` for `DASHBOARD.md`; `cell_values()` decides what each field shows, for both.
- Page list: `PAGE_TEMPLATE`, `_item()` and `render_page()` in `archiver/pagelist.py`.
- Both use CSS variables at the top of the template for colours, with a dark-mode set under `prefers-color-scheme: dark`.
- Run `python -m unittest discover -s tests` after changing either. `tests/test_dashboard.py` also checks that no emoji appear.

To preview without waiting for a run, download your releases list and run the builder locally:

```bash
gh api --paginate repos/<owner>/<repo>/releases --jq '.[]' > releases.jsonl
python -m archiver.dashboard --releases releases.jsonl --repo-url https://github.com/<owner>/<repo> --md /tmp/DASHBOARD.md --html /tmp/site/index.html
```

then open `/tmp/site/index.html` in a browser. Add `--indexes <folder>` with downloaded `capture-index.json` files to build page lists too.
