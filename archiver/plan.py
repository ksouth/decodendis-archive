"""Decide which sites to capture on this run.

Reads sites.yaml and the repository's existing releases (from `gh release list --json
tagName,createdAt,isPrerelease`) and prints GitHub Actions outputs: `matrix` (a JSON list of
jobs) and `count`.

Each capture is published as one or more releases tagged
`archive/<slug>/<capture id>-part<N>`. A part that stopped early (time or size limit) is a
pre-release carrying the crawler's saved state, and the next run continues it as part N+1.
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import SCHEDULE_DAYS, find_site, load_sites, normalise_site

TAG_RE = re.compile(r"^archive/(?P<slug>[a-z0-9-]+)/(?P<capture>\d{8}T\d{6}Z)-part(?P<part>\d+)$")
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
# The daily run starts at slightly different times; don't make a monthly site wait a day.
SCHEDULE_TOLERANCE = timedelta(hours=12)


@dataclass
class Release:
    tag: str
    slug: str
    capture: str
    part: int
    created: datetime
    partial: bool


def parse_releases(items: List[Dict[str, Any]]) -> Dict[str, Release]:
    """Latest archive release per site."""
    latest: Dict[str, Release] = {}
    for item in items:
        m = TAG_RE.match(item.get("tagName", ""))
        if not m:
            continue
        rel = Release(
            tag=item["tagName"],
            slug=m["slug"],
            capture=m["capture"],
            part=int(m["part"]),
            created=datetime.fromisoformat(item["createdAt"].replace("Z", "+00:00")),
            partial=bool(item.get("isPrerelease")),
        )
        current = latest.get(rel.slug)
        if current is None or (rel.created, rel.part) > (current.created, current.part):
            latest[rel.slug] = rel
    return latest


def new_job(site: Dict[str, Any], now: datetime, reason: str) -> Dict[str, Any]:
    return {
        "slug": site["slug"],
        "site": site,
        "capture": now.strftime(STAMP_FORMAT),
        "part": 1,
        "resume_tag": "",
        "reason": reason,
    }


def plan_site(site: Dict[str, Any], latest: Optional[Release], now: datetime) -> Optional[Dict[str, Any]]:
    schedule = site["schedule"]
    if schedule == "off":
        return None
    if latest and latest.partial:
        if latest.part >= site["max_parts"]:
            print(f"::warning::{site['slug']}: stopped after {latest.part} parts (max_parts)", file=sys.stderr)
            return None
        return {
            "slug": site["slug"],
            "site": site,
            "capture": latest.capture,
            "part": latest.part + 1,
            "resume_tag": latest.tag,
            "reason": f"continue partial capture {latest.tag}",
        }
    if latest is None:
        return new_job(site, now, "never captured")
    if schedule == "once":
        return None
    due = latest.created + timedelta(days=SCHEDULE_DAYS[schedule]) - SCHEDULE_TOLERANCE
    if now >= due:
        return new_job(site, now, f"{schedule} capture due")
    return None


def plan(
    sites: List[Dict[str, Any]],
    releases: Dict[str, Release],
    now: datetime,
    force_site: str = "",
    adhoc_url: str = "",
    page_limit: int = 0,
    resume_only: bool = False,
) -> List[Dict[str, Any]]:
    if adhoc_url:
        site = find_site(sites, adhoc_url) or normalise_site({"url": adhoc_url}, {})
        jobs = [new_job(site, now, "manual run")]
    elif force_site:
        site = find_site(sites, force_site)
        if site is None:
            raise SystemExit(f"No site named '{force_site}' in sites.yaml")
        jobs = [new_job(site, now, "manual run")]
    else:
        jobs = [j for s in sites if (j := plan_site(s, releases.get(s["slug"]), now))]
        if resume_only:
            jobs = [j for j in jobs if j["resume_tag"]]
    if page_limit:
        for job in jobs:
            job["site"] = {**job["site"], "page_limit": page_limit}
    return jobs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sites", default="sites.yaml")
    parser.add_argument("--releases", required=True, help="JSON from gh release list")
    parser.add_argument("--resume-only", action="store_true", help="only captures that need another part")
    args = parser.parse_args()

    sites = load_sites(Path(args.sites))
    releases = parse_releases(json.loads(Path(args.releases).read_text() or "[]"))
    jobs = plan(
        sites,
        releases,
        datetime.now(timezone.utc),
        force_site=os.environ.get("INPUT_SITE", ""),
        adhoc_url=os.environ.get("INPUT_URL", "").strip(),
        page_limit=int(os.environ.get("INPUT_PAGE_LIMIT") or 0),
        resume_only=args.resume_only,
    )
    for job in jobs:
        print(f"{job['slug']}: part {job['part']} ({job['reason']})", file=sys.stderr)
    if not jobs:
        print("Nothing is due.", file=sys.stderr)
    print(f"matrix={json.dumps(jobs)}")
    print(f"count={len(jobs)}")


if __name__ == "__main__":
    main()
