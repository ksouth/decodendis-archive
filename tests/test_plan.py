import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

from archiver.config import ConfigError, load_sites, normalise_site, slugify
from archiver.plan import parse_releases, plan

NOW = datetime(2026, 9, 25, 3, 17, tzinfo=timezone.utc)


def release(slug, days_ago, part=1, partial=False, capture="20260801T000000Z"):
    created = NOW - timedelta(days=days_ago)
    return {"tagName": f"archive/{slug}/{capture}-part{part}", "createdAt": created.isoformat().replace("+00:00", "Z"),
            "isPrerelease": partial}


def site(url, **kw):
    return normalise_site({"url": url, **kw}, {})


class PlanTest(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify("https://www.ndis.gov.au"), "ndis-gov-au")
        self.assertEqual(slugify("https://www.ndis.gov.au/about-us/"), "ndis-gov-au-about-us")

    def test_new_site_is_captured_once(self):
        s = site("https://a.example")
        self.assertEqual([j["reason"] for j in plan([s], {}, NOW)], ["never captured"])
        done = parse_releases([release(s["slug"], 1)])
        self.assertEqual(plan([s], done, NOW), [])

    def test_monthly_and_weekly(self):
        m, w = site("https://m.example", schedule="monthly"), site("https://w.example", schedule="weekly")
        releases = parse_releases([release(m["slug"], 29.6), release(w["slug"], 3)])
        self.assertEqual([j["slug"] for j in plan([m, w], releases, NOW)], [m["slug"]])
        releases = parse_releases([release(m["slug"], 20), release(w["slug"], 7)])
        self.assertEqual([j["slug"] for j in plan([m, w], releases, NOW)], [w["slug"]])

    def test_off_is_skipped(self):
        self.assertEqual(plan([site("https://a.example", schedule="off")], {}, NOW), [])

    def test_partial_capture_continues(self):
        s = site("https://big.example")
        releases = parse_releases([release(s["slug"], 2, part=1), release(s["slug"], 1, part=2, partial=True)])
        (job,) = plan([s], releases, NOW)
        self.assertEqual((job["part"], job["capture"]), (3, "20260801T000000Z"))
        self.assertEqual(job["resume_tag"], f"archive/{s['slug']}/20260801T000000Z-part2")

    def test_resume_only(self):
        big, new = site("https://big.example"), site("https://new.example")
        releases = parse_releases([release(big["slug"], 1, part=1, partial=True)])
        self.assertEqual([j["slug"] for j in plan([big, new], releases, NOW)], [big["slug"], new["slug"]])
        self.assertEqual([j["slug"] for j in plan([big, new], releases, NOW, resume_only=True)], [big["slug"]])

    def test_partial_stops_at_max_parts(self):
        s = site("https://big.example", max_parts=2)
        releases = parse_releases([release(s["slug"], 1, part=2, partial=True)])
        self.assertEqual(plan([s], releases, NOW), [])

    def test_manual_runs(self):
        s = site("https://a.example")
        done = parse_releases([release(s["slug"], 1)])
        self.assertEqual(len(plan([s], done, NOW, force_site=s["slug"])), 1)
        (job,) = plan([], {}, NOW, adhoc_url="https://new.example/x", page_limit=5)
        self.assertEqual((job["slug"], job["site"]["page_limit"]), ("new-example-x", 5))
        with self.assertRaises(SystemExit):
            plan([s], {}, NOW, force_site="nope")

    def test_ignores_other_releases(self):
        self.assertEqual(parse_releases([{"tagName": "v1.0", "createdAt": "2026-01-01T00:00:00Z"}]), {})

    def test_config_validation(self):
        with self.assertRaises(ConfigError):
            site("ftp://a.example")
        with self.assertRaises(ConfigError):
            site("https://a.example", schedule="daily")
        with self.assertRaises(ConfigError):
            site("https://a.example", shedule="monthly")  # misspelled setting
        path = Path(tempfile.mkdtemp()) / "sites.yaml"
        path.write_text("sites:\n  - url: https://a.example\n  - url: https://www.a.example\n")
        with self.assertRaises(ConfigError):
            load_sites(path)
        path.write_text("defaults:\n  schedule: monthly\nsites:\n  - url: https://a.example\n")
        self.assertEqual(load_sites(path)[0]["schedule"], "monthly")

    def test_time_limit_is_capped(self):
        self.assertEqual(site("https://a.example", time_limit_hours=12)["time_limit_hours"], 5)


if __name__ == "__main__":
    unittest.main()
