# Troubleshooting

Start with the **Actions** tab: click the most recent **Archive sites** run, then the job with a red cross, then the step that failed. The last lines of its log usually say what went wrong. The dashboard's **Failed (view log)** link goes straight there.

## Nothing happens after I add a site

- **Actions are off in your copy.** Forks start with workflows disabled. Open **Actions** and click the button to enable them, then change `sites.yaml` again (or use **Run workflow**).
- **The change isn't on `main`.** The workflow only reacts to `sites.yaml` on the `main` branch.
- **The site is already captured.** A `once` site is captured one time only. Use **Run workflow** with its name in **site** to capture it again.
- **`sites.yaml` has a mistake.** Check the **Test** run for the same commit; its log names the problem. See the error table in [sites-yaml.md](sites-yaml.md#error-messages).

## A capture failed

Open the failed job's log and look near the end.

| Log says | Likely cause | What to do |
|---|---|---|
| `The crawler did not produce a web archive` | The site couldn't be loaded at all: wrong address, site down, or it blocked the crawler | Check the address in a browser. Try again later. If the site blocks automated visitors, lower `workers` to `1`; some sites can't be captured this way. |
| `No site named '...' in sites.yaml` | The **site** field of the Run workflow form doesn't match | Use the site's `name` (as shown on the dashboard) or its exact URL |
| Errors mentioning `docker pull` or `ghcr.io` | GitHub couldn't download the crawler | Usually temporary; run again |
| `Unknown ...` or `must be one of` | A mistake in `sites.yaml` | See [sites-yaml.md](sites-yaml.md#error-messages) |
| The job was cancelled after about 6 hours | The part ran past GitHub's limit | Lower `time_limit_hours`, e.g. to `4`, to leave more time for packaging |

A failed site is retried at the next daily run. The dashboard shows **Failed** until a capture succeeds.

## The capture worked but something is missing

**Few pages captured.**
- The crawl follows links, so pages nothing links to are only found through the sitemap (`use_sitemap: true`, and no `page_limit`).
- `scope` may be narrower than you think: `prefix` only follows addresses under the starting path, and `host` doesn't follow subdomains.
- `robots.txt` may exclude parts of the site. The report's "not captured" list shows linked documents that were skipped.
- The site may build its content with JavaScript and load everything into one page, so there are genuinely few pages. Open the `.wacz` at replayweb.page to check the content is there.
- With a `page_limit`, the crawl captures the starting page's links in order, which is often the whole navigation menu before any content.

**No documents, or fewer than expected.**
- Documents are found by extension, by type, and by the file name the server sends. A document behind a link like `/view?id=7` that serves a web page rather than the file won't be found.
- Documents on other websites need `offsite_documents: true`, and are only fetched when the link looks like a file or a download. Anything the other site blocks with `robots.txt` is listed in the report.
- Check the report's "Linked documents on the site that were not captured" list.

**Pages look wrong at replayweb.page.** Some interactive features (search boxes, maps, embedded videos, logins) depend on live servers and don't work in any archive. The page text and files are still captured.

**Content behind a login** isn't captured.

## A big site is stuck

- **Dashboard says In progress but nothing is running.** The next part only starts straight away if every capture in the previous run succeeded; otherwise it waits for the daily run. Check the Actions tab for a failure, or start it now with **Run workflow** (all fields empty).
- **Dashboard says Stopped.** It reached `max_parts`. Raise `max_parts` and it continues at the next run, or narrow the capture with `scope` or `exclude`.
- **Each part captures very little.** The site may be slow or rate-limiting. Try fewer `workers`, and `exclude` sections you don't need (search results, calendars, tag pages, and similar never-ending lists).

## The dashboard or page lists

**The web page shows a 404.** GitHub Pages is off. Turn it on: **Settings → Pages → Deploy from a branch → main, /docs**. The first build takes a minute or two.

**The dashboard hasn't updated.** It is rebuilt at the end of each run; Pages takes about another minute to publish it. Refresh the page, or do a hard refresh (Shift + reload) if your browser is showing an old copy.

**A capture has no page list, or the Pages count isn't a link.** Page lists exist only for captures made after the feature was added, and only when `web_page: true`. Capture the site again to get one.

**Numbers look wrong for an old capture.** Captures made before the hidden statistics line existed are read from their report tables, and some newer fields (site files, failed pages) may be missing.

**Times.** The web page shows your local time. `DASHBOARD.md` on GitHub shows UTC.

**Emails saying "pages build and deployment" failed.** Pages is publishing from `docs/`, but `docs/` is missing. Either set `web_page: true` so the dashboard is written there, or turn Pages off.

## Pushing your own changes is rejected

The workflow commits the dashboard after every run, so GitHub often has a commit you don't. Run `git pull --rebase` and push again.

## Removing things

- **Stop capturing a site but keep its captures:** set `schedule: off`.
- **Remove a site entirely:** delete it from `sites.yaml`. Its captures stay under **Releases** and on the dashboard as one-off captures until you delete the releases.
- **Delete a capture:** delete its release (and its tag) on the Releases page. The next run removes it from the dashboard and deletes its page list. This can't be undone.

## Updating a copy of the template

Repositories made from the template don't receive later changes. Replace your copy's `archiver/`, `tests/`, `guide/` and `.github/workflows/` folders with the ones from [ksouth/SCRAPE](https://github.com/ksouth/SCRAPE), keep your own `sites.yaml` entries, and compare the README and `sites.yaml` comments for new settings.

## Still stuck

Run the tests, which also check that the code works on your setup:

```bash
pip install -r archiver/requirements.txt
python -m unittest discover -s tests
```

Then try the site from the **Run workflow** form with a small **page_limit** (like 5), and read that job's log from the top: every command it runs is printed with a `+` in front.
