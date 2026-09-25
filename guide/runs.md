# How runs work

Everything happens in one GitHub Actions workflow, **Archive sites** (`.github/workflows/archive.yml`), on GitHub's servers. Nothing runs on your computer.

## What starts a run

| Trigger | When | Captures |
|---|---|---|
| A change to `sites.yaml` pushed to `main` | within a minute | Sites that have never been captured, and anything else due |
| The daily schedule | 03:17 UTC every day (1:17 pm AEST, 2:17 pm AEDT) | `weekly` and `monthly` sites that are due, and new sites a failed run missed |
| The previous run, automatically | as soon as it finishes | The next part of a large site that stopped at its time or size limit |
| **Actions → Archive sites → Run workflow** | when you click it | See below |

Changes to other files (code, README) don't start a capture.

To change the daily time, edit the `cron:` line in `archive.yml`. It is in UTC, in the form `minute hour * * *`: `"17 3 * * *"` is 03:17 UTC. GitHub often starts scheduled runs several minutes late, and sometimes skips one when its servers are busy; the next day's run then catches up.

### The Run workflow form

| Field | Effect |
|---|---|
| (all empty) | A normal run: captures whatever is due, the same as the daily run |
| site | Capture this site from `sites.yaml` now, by its name or URL, even if it isn't due. Starts a new capture; it doesn't continue an incomplete one. |
| url | Capture any address once now, with the default settings. Listed under **One-off captures** on the dashboard. If it's large and stops part way, it isn't continued; add it to `sites.yaml` instead. |
| page_limit | Stop this run's captures after this many pages. Good for a quick test. |

## Inside a run

```text
plan ──> archive (one job per site, 2 at a time) ──> continue
                                                 └──> dashboard
```

1. **plan** (about 10 seconds) decides which sites to capture. If none are due, the run skips straight to **dashboard**.
2. **archive**, one job per site, captures and publishes it. Two sites run at a time; others wait their turn.
3. **continue** starts another run if any capture is incomplete, but only if every capture in this run succeeded, so a site that keeps failing can't restart in a loop. A failed site is retried at the next daily run.
4. **dashboard** rebuilds the dashboard and page lists, even if a capture failed, so the failure shows.

Only one run happens at a time. If one is triggered while another is running, it waits; if several are waiting, GitHub keeps only the newest.

## How long a capture takes

It depends on the site, not on your settings. Some rough guides with the default 4 workers:

| Site size | Time |
|---|---|
| A handful of pages | 2 to 4 minutes, mostly setting up |
| A few hundred pages | 10 to 30 minutes |
| Thousands of pages | hours, over one or more parts |

Each page is loaded in a real browser and given time to finish loading, so it's much slower than downloading the HTML, but it captures what visitors actually see.

## Limits, and parts

GitHub stops any job after 6 hours, and a single release file can't be over 2 GB. So each run of a site (a **part**) stops at whichever comes first:

- **`time_limit_hours`** of crawling (default and maximum 5), leaving an hour to package and upload;
- **1.8 GB** of captured data, so the web archive stays under 2 GB.

When a part stops early, the crawler saves its place: the pages it has visited, and the queue it still has to visit. That is published with the part as `crawl-state.yaml`, and the release is marked as a pre-release (incomplete). The next run loads it and carries on with only the pages not yet visited. Each part holds different pages; together they are the whole capture. The page list combines them.

A capture stops being continued after `max_parts` parts (default 50), and the dashboard shows it as Stopped.

Other limits:

| Limit | Value | What happens |
|---|---|---|
| Documents uploaded individually | 900 per part | Beyond that, documents are only in `documents.zip` |
| One zip file | 1.9 GB | Split into `documents-1.zip`, `documents-2.zip`, ... |
| Documents from other websites | `max_offsite_documents`, default 2000 | The rest are listed in the report |
| Disk space on GitHub's server | well over 10 GB after the workflow clears unused software | A part needs a few times its 1.8 GB limit while packaging, which fits |

## Being polite to websites

- `respect_robots: true` (the default) obeys each site's `robots.txt`, both in the crawl and when fetching documents from other websites.
- Every request says what it is: the crawler adds `+SiteArchiver (<your repository's address>)` to its browser identity, so site owners can see who is archiving and why.
- Documents from other websites are fetched one per second.
- `workers` sets how many pages load at once. Lower it (`1` or `2`) for small sites, or sites that start refusing requests.
- Ads are blocked, so no ad traffic is generated.

## Permissions

The workflow uses GitHub's built-in token with only these permissions:

| Permission | Why |
|---|---|
| `contents: write` | Publish releases, and commit the dashboard |
| `actions: write` | Start the next run when a capture needs another part |
| `pages: read` | Check whether Pages is on, to warn you if it isn't |

No passwords or keys need setting up.

## Cost

GitHub Actions is free and unlimited for **public** repositories. For **private** repositories, GitHub Free includes 2,000 minutes a month; a large capture can use several hundred minutes (two jobs at once count twice). Release storage is free and has no total limit for either.

## Software versions

- The crawler is pinned to one version, `CRAWLER_IMAGE` in `archiver/run.py` (`webrecorder/browsertrix-crawler:1.14.3`), so captures don't change behaviour unexpectedly. To upgrade, change the version, run a test capture with a page limit, and check the result.
- Python packages are pinned in `archiver/requirements.txt`.
- The workflow uses GitHub's `ubuntu-latest` runner and Python 3.12.

## Running on your own computer

Not needed, but possible for testing. You need Docker, Python 3.9 or later, and the `gh` command-line tool signed in to GitHub.

```bash
pip install -r archiver/requirements.txt
python -m unittest discover -s tests
```

To capture, set `JOB` to one entry of the plan's output and run `python -m archiver.run` from the repository folder. It publishes a real release, so use a test repository.
