import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from archiver.config import ConfigError, load_dashboard_settings, normalise_site
from archiver.dashboard import build, daily_run_time, release_stats, render_html, render_md

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
DAILY = (3, 17)
REPO = "https://github.com/me/archive"
EMOJI = re.compile("[\\U0001F300-\\U0001FAFF\\u2600-\\u27BF]")


def rel(slug, capture, part, created, prerelease=False, body="", assets=None):
    tag = f"archive/{slug}/{capture}-part{part}"
    return {"tag_name": tag, "prerelease": prerelease, "body": body, "published_at": created,
            "created_at": "2020-01-01T00:00:00Z",  # commit date; must be ignored
            "html_url": f"{REPO}/releases/tag/{tag}",
            "assets": assets if assets is not None else [{"name": "x.wacz", "size": 100, "browser_download_url": "w"}]}


def stats(pages, docs, offsite=0, site_files=None, failed=0, url="https://a.example/"):
    s = f'"pages": {pages}, "failed": {failed}, "documents": {docs}, "offsite_documents": {offsite}'
    if site_files is not None:
        s += f', "site_files": {site_files}'
    return f"# {url}\n\nreport\n<!-- capture-stats {{{s}}} -->"


def zip_asset(name):
    return {"name": name, "size": 10, "browser_download_url": f"{REPO}/releases/download/t/{name}"}


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.monthly = normalise_site({"url": "https://a.example", "schedule": "monthly", "site_files": True}, {})
        self.big = normalise_site({"url": "https://big.example"}, {})
        self.new = normalise_site({"url": "https://new.example"}, {})
        self.paused = normalise_site({"url": "https://paused.example", "schedule": "off"}, {})
        self.releases = [
            rel("a-example", "20260801T000000Z", 1, "2026-08-01T01:00:00Z", body=stats(10, 1)),
            rel("a-example", "20260910T000000Z", 1, "2026-09-10T02:30:00Z", body=stats(12, 2, site_files=40, failed=3),
                assets=[zip_asset("documents.zip"), zip_asset("site-files.zip")]),
            rel("big-example", "20260925T000000Z", 1, "2026-09-25T05:00:00Z", body=stats(1000, 50, url="https://big.example/")),
            rel("big-example", "20260925T000000Z", 2, "2026-09-25T10:00:00Z", prerelease=True,
                body=stats(800, 30, 5, url="https://big.example/")),
            rel("adhoc-example", "20260920T000000Z", 1, "2026-09-20T00:05:00Z", body=stats(3, 0, url="https://adhoc.example/x")),
        ]

    def model(self, jobs=None):
        return build([self.monthly, self.big, self.new, self.paused], self.releases, NOW, jobs, DAILY)

    def test_stats_from_comment_and_old_table(self):
        self.assertEqual(release_stats(stats(5, 2))["pages"], 5)
        old = "| Pages captured | 20 |\n| Documents from the site | 3 (1 MB) |\n| Documents from other sites | 1 (2 KB) |"
        self.assertEqual(release_stats(old), {"pages": 20, "documents": 3, "offsite_documents": 1})

    def test_statuses_next_runs_and_totals(self):
        m = self.model()
        a, big, new, paused = m["sites"]
        self.assertEqual((a["status"], a["latest"]["pages"], a["count"]), ("complete", 12, 2))
        # Due 30 days after 2026-09-10 02:30, less the 12-hour tolerance -> first daily run at or after 2026-10-09 14:30.
        self.assertEqual(a["next"], datetime(2026, 10, 10, 3, 17, tzinfo=timezone.utc))
        self.assertEqual((big["status"], big["latest"]["parts"], big["latest"]["pages"]), ("in progress", 2, 1800))
        self.assertEqual(big["next"], "continuing now")
        self.assertEqual((new["status"], new["next"]), ("waiting", datetime(2026, 9, 26, 3, 17, tzinfo=timezone.utc)))
        self.assertEqual((paused["status"], paused["next"]), ("off", "never (off)"))
        (adhoc,) = m["other"]
        self.assertEqual((adhoc["schedule"], adhoc["url"], adhoc["next"]), ("one-off", "https://adhoc.example/x", "—"))

    def test_once_site_has_no_next_run(self):
        once = normalise_site({"url": "https://once.example"}, {})
        m = build([once], [rel("once-example", "20260920T000000Z", 1, "2026-09-20T00:00:00Z", body=stats(1, 0))],
                  NOW, [], DAILY)
        self.assertEqual(m["sites"][0]["next"], "none (once)")

    def test_markdown_links_and_values(self):
        md = render_md(self.model(), REPO)
        self.assertIn(f"[2 (download zip, 10 B)]({REPO}/releases/download/t/documents.zip)", md)
        self.assertIn(f"[40 (download zip, 10 B)]({REPO}/releases/download/t/site-files.zip)", md)
        self.assertIn("(opens release page)", md)  # big.example's documents have no zip asset in this fixture
        self.assertIn("**Clicking a Documents or Site files number downloads a zip file**", md)
        self.assertIn("12 (3 failed)", md)
        self.assertIn("| off |", md)  # site files turned off for big.example
        self.assertIn("2026-09-10 02:30 UTC", md)
        self.assertIn("2026-10-10 03:17 UTC", md)
        self.assertIn(f"[open page]({REPO}/releases/tag/archive/a-example/20260910T000000Z-part1)", md)
        self.assertIn("## One-off captures", md)
        self.assertIn("daily check runs at 03:17 UTC", md)

    def test_failures_show_until_a_later_capture(self):
        jobs = [
            {"name": "new-example (part 1)", "conclusion": "failure", "completed_at": "2026-09-25T11:00:00Z", "html_url": "LOG1"},
            {"name": "a-example (part 1)", "conclusion": "failure", "completed_at": "2026-09-01T00:00:00Z", "html_url": "OLD"},
            {"name": "plan", "conclusion": "failure", "completed_at": "2026-09-25T11:00:00Z", "html_url": "x"},
        ]
        m = self.model(jobs)
        a, _, new, _ = m["sites"]
        self.assertEqual(new["status"], "failed")
        self.assertEqual(a["status"], "complete")  # its failure is older than its latest capture
        md = render_md(m, REPO)
        self.assertIn("[Failed (view log)](LOG1)", md)

    def test_stopped_captures(self):
        capped = normalise_site({"url": "https://capped.example", "max_parts": 2}, {})
        releases = [rel("capped-example", "20260925T000000Z", 2, "2026-09-25T00:00:00Z", prerelease=True, body=stats(5, 0)),
                    rel("gone-example", "20260925T000000Z", 1, "2026-09-25T00:00:00Z", prerelease=True, body=stats(5, 0))]
        m = build([capped], releases, NOW, [], DAILY)
        self.assertEqual((m["sites"][0]["status"], m["sites"][0]["next"]), ("stopped", "—"))
        self.assertEqual(m["other"][0]["status"], "stopped")
        self.assertIn("Stopped after part 2", render_md(m, REPO))

    def test_html(self):
        page = render_html(self.model(), REPO)
        self.assertIn("<title>Archive dashboard</title>", page)
        self.assertIn('class="status in-progress"', page)
        self.assertIn('<time datetime="2026-09-10T02:30:00Z">', page)
        # Label and value sit inside the same link, so both are clickable.
        self.assertRegex(page, r'<a href="[^"]+documents\.zip"><span class="lbl">Documents</span><span class="val">2'
                               r'<span class="hint">download zip, 10 B</span></span></a>')
        self.assertIn('<p class="notice"><strong>Downloads:</strong>', page)

    def test_page_list_links(self):
        m = build([self.monthly, self.big, self.new, self.paused], self.releases, NOW, [], DAILY,
                  lists={("a-example", "20260910T000000Z")})
        md = render_md(m, REPO)
        self.assertIn("[12 (3 failed) (view list)](https://me.github.io/archive/captures/a-example/20260910T000000Z/)", md)
        self.assertNotIn("1,800 (view list)", md)  # no page list for that capture
        page = render_html(m, REPO)
        self.assertIn('<a href="captures/a-example/20260910T000000Z/">', page)

    def test_no_emoji(self):
        m = self.model([{"name": "new-example (part 1)", "conclusion": "failure",
                         "completed_at": "2026-09-25T11:00:00Z", "html_url": "L"}])
        self.assertIsNone(EMOJI.search(render_md(m, REPO)))
        self.assertIsNone(EMOJI.search(render_html(m, REPO)))

    def test_empty(self):
        model = build([], [], NOW, [], None)
        self.assertIn("No sites in `sites.yaml` yet", render_md(model, REPO))
        self.assertIn("no captures yet", render_html(model, REPO))

    def test_html_is_escaped(self):
        site = normalise_site({"url": "https://x.example/?q=<script>"}, {})
        page = render_html(build([site], [], NOW, [], DAILY), REPO)
        self.assertNotIn("q=<script>", page)

    def test_daily_run_time_from_workflow(self):
        self.assertEqual(daily_run_time(Path(".github/workflows/archive.yml")), DAILY)

    def test_settings(self):
        path = Path(tempfile.mkdtemp()) / "sites.yaml"
        path.write_text("sites: []\n")
        self.assertEqual(load_dashboard_settings(path), {"markdown": True, "web_page": True})
        path.write_text("dashboard:\n  web_page: false\nsites: []\n")
        self.assertEqual(load_dashboard_settings(path), {"markdown": True, "web_page": False})
        path.write_text("dashboard:\n  colour: blue\n")
        with self.assertRaises(ConfigError):
            load_dashboard_settings(path)


if __name__ == "__main__":
    unittest.main()
