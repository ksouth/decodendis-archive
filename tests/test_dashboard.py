import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from archiver.config import ConfigError, load_dashboard_settings, normalise_site
from archiver.dashboard import build, release_stats, render_html, render_md

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
REPO = "https://github.com/me/archive"


def rel(slug, capture, part, prerelease=False, body="", size=100):
    return {"tag_name": f"archive/{slug}/{capture}-part{part}", "prerelease": prerelease, "body": body,
            "html_url": f"{REPO}/releases/tag/archive/{slug}/{capture}-part{part}", "assets": [{"size": size}]}


def stats(pages, docs, offsite=0, site_files=None):
    s = f'"pages": {pages}, "failed": 0, "documents": {docs}, "offsite_documents": {offsite}'
    if site_files is not None:
        s += f', "site_files": {site_files}'
    return "# report\n<!-- capture-stats {" + s + "} -->"


class DashboardTest(unittest.TestCase):
    def test_stats_from_comment_and_old_table(self):
        self.assertEqual(release_stats(stats(5, 2))["pages"], 5)
        old = "| Pages captured | 20 |\n| Documents from the site | 3 (1 MB) |\n| Documents from other sites | 1 (2 KB) |"
        self.assertEqual(release_stats(old), {"pages": 20, "documents": 3, "offsite_documents": 1})

    def test_statuses_and_totals(self):
        sites = [
            normalise_site({"url": "https://a.example", "schedule": "monthly"}, {}),
            normalise_site({"url": "https://big.example"}, {}),
            normalise_site({"url": "https://new.example"}, {}),
            normalise_site({"url": "https://paused.example", "schedule": "off"}, {}),
        ]
        releases = [
            rel("a-example", "20260801T000000Z", 1, body=stats(10, 1)),
            rel("a-example", "20260910T000000Z", 1, body=stats(12, 2, site_files=40)),
            rel("big-example", "20260925T000000Z", 1, body=stats(1000, 50), size=1000),
            rel("big-example", "20260925T000000Z", 2, prerelease=True, body=stats(800, 30, 5), size=500),
            rel("adhoc-example", "20260920T000000Z", 1, body=stats(3, 0)),
        ]
        model = build(sites, releases, NOW)
        a, big, new, paused = model["sites"]
        self.assertEqual((a["status"], a["latest"]["pages"], a["count"], a["next"]), ("complete", 12, 2, "2026-10-10"))
        self.assertEqual((big["status"], big["latest"]["parts"], big["latest"]["pages"]), ("in progress", 2, 1800))
        self.assertEqual((big["latest"]["documents"], big["latest"]["size"]), (80, 1500))
        self.assertEqual((new["status"], paused["status"]), ("waiting", "off"))
        self.assertEqual([o["slug"] for o in model["other"]], ["adhoc-example"])

        md = render_md(model, REPO)
        self.assertIn("in progress (part 2)", md)
        self.assertIn("| 1,800 | 85 |", md)  # documents include offsite ones
        self.assertIn("## Other captures", md)
        page = render_html(model, REPO)
        self.assertIn("<title>Archive dashboard</title>", page)
        self.assertIn('class="status in-progress"', page)

    def test_stopped_captures(self):
        capped = normalise_site({"url": "https://capped.example", "max_parts": 2}, {})
        releases = [rel("capped-example", "20260925T000000Z", 2, prerelease=True, body=stats(5, 0)),
                    rel("gone-example", "20260925T000000Z", 1, prerelease=True, body=stats(5, 0))]
        model = build([capped], releases, NOW)
        self.assertEqual(model["sites"][0]["status"], "stopped")
        self.assertEqual(model["other"][0]["status"], "stopped")
        self.assertIn("stopped after part 2", render_md(model, REPO))

    def test_empty(self):
        model = build([], [], NOW)
        self.assertIn("No sites in `sites.yaml` yet", render_md(model, REPO))
        self.assertIn("no captures yet", render_html(model, REPO))

    def test_html_is_escaped(self):
        site = normalise_site({"url": "https://x.example/?q=<script>"}, {})
        page = render_html(build([site], [], NOW), REPO)
        self.assertNotIn("<script>", page)

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
