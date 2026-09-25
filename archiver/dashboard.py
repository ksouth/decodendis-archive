"""Build DASHBOARD.md and docs/index.html: what each site has captured.

Reads sites.yaml, the repository's releases (JSON lines from
`gh api --paginate repos/<owner>/<repo>/releases --jq '.[]'`), and optionally the capture
jobs of failed workflow runs (JSON lines with name, conclusion, completed_at, html_url).
"""

import argparse
import html
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import load_dashboard_settings, load_sites
from .plan import STAMP_FORMAT, TAG_RE, parse_releases, plan_site

STATS_RE = re.compile(r"<!-- capture-stats (\{.*?\}) -->")
# Older reports, written before the stats comment existed.
TABLE_ROWS = {
    "pages": r"\| Pages captured \| (\d+)",
    "failed": r"\| Pages failed \| (\d+)",
    "documents": r"\| Documents from the site \| (\d+)",
    "offsite_documents": r"\| Documents from other sites \| (\d+)",
    "site_files": r"\| Site files \| (\d+)",
}
REPORT_URL_RE = re.compile(r"^# (https?://\S+)", re.MULTILINE)
JOB_NAME_RE = re.compile(r"^(?P<slug>[a-z0-9-]+) \(part (?P<part>\d+)\)$")
CRON_RE = re.compile(r"cron:\s*[\"']?(\d+) (\d+) \* \* \*")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fmt_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC")


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def release_stats(body: str) -> Dict[str, int]:
    m = STATS_RE.search(body or "")
    if m:
        return json.loads(m.group(1))
    stats = {}
    for key, pattern in TABLE_ROWS.items():
        found = re.search(pattern, body or "")
        if found:
            stats[key] = int(found.group(1))
    return stats


def daily_run_time(workflow: Path) -> Optional[Tuple[int, int]]:
    """(hour, minute) UTC of the workflow's daily schedule."""
    try:
        m = CRON_RE.search(workflow.read_text())
    except OSError:
        return None
    return (int(m.group(2)), int(m.group(1))) if m else None


def next_daily(after: datetime, hour_minute: Tuple[int, int]) -> datetime:
    t = after.replace(hour=hour_minute[0], minute=hour_minute[1], second=0, microsecond=0)
    return t if t > after else t + timedelta(days=1)


def published(rel: Dict[str, Any]) -> str:
    """When a release was published. Its created_at is the date of the tagged commit, not of the release."""
    return rel.get("published_at") or rel.get("created_at") or ""


def group_captures(releases: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Captures per site, newest first. A capture is all the parts sharing one capture id."""
    parts: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for rel in releases:
        m = TAG_RE.match(rel.get("tag_name", ""))
        if m:
            parts[(m["slug"], m["capture"])].append({**rel, "part": int(m["part"])})
    by_site: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for (slug, capture), rels in parts.items():
        rels.sort(key=lambda r: r["part"])
        totals: Dict[str, int] = defaultdict(int)
        for rel in rels:
            for key, value in release_stats(rel.get("body", "")).items():
                totals[key] += value
        assets = [a for r in rels for a in r.get("assets", [])]
        url = next((m.group(1) for r in rels if (m := REPORT_URL_RE.search(r.get("body") or ""))), "")
        last = rels[-1]
        by_site[slug].append({
            "capture": capture,
            "finished": parse_time(published(last)) if published(last) else
            datetime.strptime(capture, STAMP_FORMAT).replace(tzinfo=timezone.utc),
            "parts": last["part"],
            "complete": not last.get("prerelease"),
            "size": sum(a.get("size", 0) for a in assets),
            "release_url": last.get("html_url", ""),
            "url": url,
            "document_zips": [a["browser_download_url"] for a in assets if re.match(r"documents(-\d+)?\.zip$", a.get("name", ""))],
            "site_zips": [a["browser_download_url"] for a in assets if re.match(r"site-files(-\d+)?\.zip$", a.get("name", ""))],
            **totals,
        })
    for captures in by_site.values():
        captures.sort(key=lambda c: c["capture"], reverse=True)
    return by_site


def latest_failures(jobs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Most recent failed capture job per site."""
    failures: Dict[str, Dict[str, Any]] = {}
    for job in jobs:
        m = JOB_NAME_RE.match(job.get("name", ""))
        if not m or job.get("conclusion") not in ("failure", "timed_out") or not job.get("completed_at"):
            continue
        when = parse_time(job["completed_at"])
        if m["slug"] not in failures or when > failures[m["slug"]]["when"]:
            failures[m["slug"]] = {"when": when, "url": job.get("html_url", "")}
    return failures


def site_row(slug: str, captures: List[Dict[str, Any]], now: datetime, site: Optional[Dict[str, Any]] = None,
             failure: Optional[Dict[str, Any]] = None, releases=None, daily: Optional[Tuple[int, int]] = None) -> Dict[str, Any]:
    """site is None for captures of sites not in sites.yaml, which are never continued or repeated."""
    latest = captures[0] if captures else None
    schedule = site["schedule"] if site else "one-off"
    if failure and (latest is None or failure["when"] > latest["finished"]):
        status = "failed"
    elif latest is None:
        status = "off" if schedule == "off" else "waiting"
    elif not latest["complete"]:
        stopped = site is None or schedule == "off" or latest["parts"] >= site["max_parts"]
        status = "stopped" if stopped else "in progress"
    else:
        status = "complete"

    next_run: Any = "—"
    if site and status == "in progress":
        next_run = "continuing now"
    elif site and status not in ("stopped",) and schedule != "off" and daily:
        parsed = releases.get(slug) if releases else None
        t = now
        for _ in range(400):
            t = next_daily(t, daily)
            if plan_site(site, parsed, t):
                next_run = t
                break
        else:
            next_run = "none (once)" if schedule == "once" else "—"
    elif site and schedule == "off":
        next_run = "never (off)"
    return {"slug": slug, "url": (site or {}).get("url") or (latest or {}).get("url", ""), "schedule": schedule,
            "status": status, "next": next_run, "latest": latest, "count": len(captures), "failure": failure,
            "site_files_on": site["site_files"] if site else None}


def build(sites: List[Dict[str, Any]], releases: List[Dict[str, Any]], now: datetime,
          jobs: Optional[List[Dict[str, Any]]] = None, daily: Optional[Tuple[int, int]] = None) -> Dict[str, Any]:
    captures = group_captures(releases)
    failures = latest_failures(jobs or [])
    parsed = parse_releases([{"tagName": r["tag_name"], "createdAt": published(r), "isPrerelease": r.get("prerelease")}
                             for r in releases if published(r)])
    listed = [site_row(s["slug"], captures.get(s["slug"], []), now, s, failures.get(s["slug"]), parsed, daily)
              for s in sites]
    names = {s["slug"] for s in sites}
    other = [site_row(slug, caps, now, None, failures.get(slug)) for slug, caps in sorted(captures.items())
             if slug not in names]
    times = [c["finished"] for caps in captures.values() for c in caps]
    return {"sites": listed, "other": other, "updated": max(times) if times else None, "daily": daily}


STATUS_LABELS = {"complete": "Complete", "in progress": "In progress", "waiting": "Waiting",
                 "off": "Off", "stopped": "Stopped", "failed": "Failed"}


def cell_values(row: Dict[str, Any]) -> List[Tuple[str, str, Optional[str], str]]:
    """(label, text, link, css class) for each column, shared by the Markdown and HTML versions."""
    c = row["latest"]
    status = STATUS_LABELS[row["status"]]
    status_link = None
    if row["status"] == "failed":
        status += " (view log)"
        status_link = row["failure"]["url"]
    elif row["status"] == "stopped":
        status += f" after part {c['parts']}"
    elif row["status"] == "in progress":
        status += f" (part {c['parts']})"

    pages = f"{c.get('pages', 0):,}" + (f" ({c['failed']:,} failed)" if c.get("failed") else "") if c else "—"
    docs = c.get("documents", 0) + c.get("offsite_documents", 0) if c else None
    doc_text = "—" if docs is None else f"{docs:,}"
    doc_link = None
    if docs:
        doc_link = c["document_zips"][0] if len(c["document_zips"]) == 1 else c["release_url"]
    if row["site_files_on"] is False:
        site_text, site_link = "off", None
    elif c and "site_files" in c:
        site_text = f"{c['site_files']:,}"
        site_link = (c["site_zips"][0] if len(c["site_zips"]) == 1 else c["release_url"]) if c["site_files"] else None
    else:
        site_text, site_link = "—", None
    nxt = row["next"]
    return [
        ("Last capture", fmt_time(c["finished"]) if c else "never", None, "time" if c else ""),
        ("Status", status, status_link, "status " + row["status"].replace(" ", "-")),
        ("Pages", pages, None, "num"),
        ("Documents", doc_text, doc_link, "num"),
        ("Site files", site_text, site_link, "num"),
        ("Size", human(c["size"]) if c else "—", None, "num"),
        ("Next run", fmt_time(nxt) if isinstance(nxt, datetime) else nxt, None, "time" if isinstance(nxt, datetime) else ""),
        ("Files", "open" if c else "—", c["release_url"] if c else None, ""),
    ]


def render_md(model: Dict[str, Any], repo_url: str) -> str:
    updated = fmt_time(model["updated"]) if model["updated"] else "no captures yet"
    daily = f" The daily check runs at {model['daily'][0]:02d}:{model['daily'][1]:02d} UTC." if model["daily"] else ""
    lines = ["# Archive dashboard", "",
             f"Rebuilt automatically after each run. Latest capture: {updated}.{daily} "
             f"All captures are under [Releases]({repo_url}/releases).", ""]

    def table(rows):
        out = ["| Site | Schedule | Last capture | Status | Pages | Documents | Site files | Size | Next run | Files |",
               "|---|---|---|---|---|---|---|---|---|---|"]
        for row in rows:
            name = f"**{row['slug']}**" + (f"<br>{row['url']}" if row["url"] else "")
            values = [f"[{text}]({link})" if link else text for _, text, link, _ in cell_values(row)]
            out.append("| " + " | ".join([name, row["schedule"], *values]) + " |")
        return out

    if model["sites"]:
        lines += table(model["sites"])
    else:
        lines.append("No sites in `sites.yaml` yet. Add one to start archiving.")
    if model["other"]:
        lines += ["", "## One-off captures", "",
                  "Captures of sites that aren't in `sites.yaml`, such as runs started from the Run workflow form. "
                  "They are never repeated or continued.", ""]
        lines += table(model["other"])
    lines += ["", "**Documents** and **Site files** link to the zip of those files (or to the release page when a "
              "capture has several). **Files** opens the release with everything from that capture. Counts and size "
              "cover every part of the latest capture; documents include those fetched from other websites."]
    return "\n".join(lines) + "\n"


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Archive dashboard</title>
<style>
:root {{ --bg:#fbfbf9; --fg:#1d1d1b; --muted:#6b6b66; --line:#e3e2dc; --card:#fff; --accent:#2f5d8a;
  --ok:#2e7d4f; --run:#9a6700; --bad:#b42318; --wait:#6b6b66; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#161615; --fg:#ecebe6; --muted:#a3a29b; --line:#33322e;
  --card:#1f1f1d; --accent:#8db8e3; --ok:#6fcf97; --run:#e3b341; --bad:#f97066; --wait:#a3a29b; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1200px; margin:0 auto; padding:32px 16px 48px; }}
h1 {{ font-size:26px; margin:0 0 4px; }} h2 {{ font-size:18px; margin:36px 0 4px; }}
p.lede, p.note {{ color:var(--muted); margin:0 0 20px; }}
a {{ color:var(--accent); }}
.wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:10px; background:var(--card); }}
table {{ border-collapse:collapse; width:100%; min-width:900px; }}
th, td {{ text-align:left; padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top; }}
th {{ font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); font-weight:600; }}
tr:last-child td {{ border-bottom:0; }}
td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
td.num {{ white-space:nowrap; }} td.time {{ min-width:150px; }}
.lbl {{ display:none; }}
.site {{ font-weight:600; }} .url {{ display:block; font-size:13px; color:var(--muted); word-break:break-all; }}
.status {{ font-weight:600; }}
.complete {{ color:var(--ok); }} .in-progress, .stopped {{ color:var(--run); }} .failed, .failed a {{ color:var(--bad); }}
.waiting, .off {{ color:var(--wait); }}
@media (max-width: 760px) {{
  table, tbody, tr, td {{ display:block; min-width:0; }}
  tr.head {{ display:none; }}
  tr {{ padding:10px 0; border-bottom:1px solid var(--line); }} tr:last-child {{ border-bottom:0; }}
  td {{ padding:3px 14px; border:0; }}
  td > a, td > span.cell {{ display:flex; justify-content:space-between; gap:16px; }}
  .lbl {{ display:inline; color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em;
    font-weight:400; flex:none; }}
  .val {{ text-align:right; min-width:0; }}
  td.time {{ min-width:0; }}
  td.name {{ padding-bottom:6px; }}
}}
</style>
</head>
<body>
<main>
<h1>Archive dashboard</h1>
<p class="lede">Latest capture: {updated}.{daily} Every capture is under <a href="{repo_url}/releases">Releases</a>;
open a <code>.wacz</code> file at <a href="https://replayweb.page">replayweb.page</a> to browse it.</p>
{sections}
<p class="note"><strong>Documents</strong> and <strong>Site files</strong> download the zip of those files (or open the
release page when a capture has several). <strong>Files</strong> opens the release with everything from that capture.
Counts and size cover every part of the latest capture; documents include those fetched from other websites.
Times are in your local time.</p>
</main>
<script>
// Show every time in the viewer's own time zone, 12-hour, followed by the zone's name in brackets.
function zoneName(d) {{
  var styles = ["longGeneric", "long"];  // "Australian Eastern Time"; older browsers only have "long"
  for (var i = 0; i < styles.length; i++) {{
    try {{
      var part = new Intl.DateTimeFormat(undefined, {{ timeZoneName: styles[i] }}).formatToParts(d)
        .filter(function (p) {{ return p.type === "timeZoneName"; }})[0];
      if (part) return part.value;
    }} catch (e) {{}}
  }}
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}}
document.querySelectorAll("time[datetime]").forEach(function (el) {{
  var d = new Date(el.getAttribute("datetime"));
  if (isNaN(d)) return;
  var clock = {{ hour: "numeric", minute: "2-digit", hour12: true }};
  if (el.hasAttribute("data-time-only")) {{
    // Use today's date, so the time reflects daylight saving as it is now.
    var now = new Date();
    d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), d.getUTCHours(), d.getUTCMinutes()));
    el.textContent = d.toLocaleTimeString(undefined, clock) + " (" + zoneName(d) + ")";
  }} else {{
    el.textContent = d.toLocaleDateString(undefined, {{ day: "numeric", month: "short", year: "numeric" }}) + ", " +
      d.toLocaleTimeString(undefined, clock) + " (" + zoneName(d) + ")";
  }}
}});
</script>
</body>
</html>
"""


def render_html(model: Dict[str, Any], repo_url: str) -> str:
    esc = html.escape

    def time_html(text: str) -> str:
        m = re.match(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) UTC$", text)
        return f'<time datetime="{m.group(1)}T{m.group(2)}:00Z">{esc(text)}</time>' if m else esc(text)

    def table(rows):
        head = ("<tr class=head><th>Site</th><th>Schedule</th><th>Last capture</th><th>Status</th><th class=num>Pages</th>"
                "<th class=num>Documents</th><th class=num>Site files</th><th class=num>Size</th><th>Next run</th>"
                "<th>Files</th></tr>")
        body = []
        for row in rows:
            url = f'<a class="url" href="{esc(row["url"])}">{esc(row["url"])}</a>' if row["url"] else ""
            tds = [f'<td class="name"><span class="site">{esc(row["slug"])}</span>{url}</td>',
                   f'<td><span class="cell"><span class="lbl">Schedule</span><span class="val">{esc(row["schedule"])}</span></span></td>']
            for label, text, link, cls in cell_values(row):
                inner = f'<span class="lbl">{label}</span><span class="val">{time_html(text) if "time" in cls else esc(text)}</span>'
                inner = f'<a href="{esc(link)}">{inner}</a>' if link else f'<span class="cell">{inner}</span>'
                tds.append(f'<td class="{cls}">{inner}</td>')
            body.append("<tr>" + "".join(tds) + "</tr>")
        return f'<div class="wrap"><table>{head}{"".join(body)}</table></div>'

    sections = table(model["sites"]) if model["sites"] else \
        "<p>No sites in <code>sites.yaml</code> yet. Add one to start archiving.</p>"
    if model["other"]:
        sections += ("<h2>One-off captures</h2><p class=note>Sites that aren't in <code>sites.yaml</code>, such as runs "
                     "started from the Run workflow form. They are never repeated or continued.</p>" + table(model["other"]))
    updated = time_html(fmt_time(model["updated"])) if model["updated"] else "no captures yet"
    daily = ""
    if model["daily"]:
        h, m = model["daily"]
        daily = (f' The daily check runs at <time data-time-only datetime="2026-01-01T{h:02d}:{m:02d}:00Z">'
                 f"{h:02d}:{m:02d} UTC</time> each day.")
    return HTML_TEMPLATE.format(updated=updated, daily=daily, repo_url=esc(repo_url), sections=sections)


def load_json_lines(path: Optional[Path]) -> List[Dict[str, Any]]:
    if not path or not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sites", default="sites.yaml")
    parser.add_argument("--releases", required=True, help="JSON lines of GitHub releases")
    parser.add_argument("--jobs", help="JSON lines of capture jobs from failed runs")
    parser.add_argument("--workflow", default=".github/workflows/archive.yml")
    parser.add_argument("--repo-url", required=True)
    parser.add_argument("--md", default="DASHBOARD.md")
    parser.add_argument("--html", default="docs/index.html")
    args = parser.parse_args()
    settings = load_dashboard_settings(Path(args.sites))
    model = build(load_sites(Path(args.sites)), load_json_lines(Path(args.releases)), datetime.now(timezone.utc),
                  load_json_lines(Path(args.jobs)) if args.jobs else [], daily_run_time(Path(args.workflow)))
    if settings["markdown"]:
        Path(args.md).write_text(render_md(model, args.repo_url))
        print(f"Wrote {args.md}")
    if settings["web_page"]:
        Path(args.html).parent.mkdir(parents=True, exist_ok=True)
        Path(args.html).write_text(render_html(model, args.repo_url))
        print(f"Wrote {args.html}")
    print(f"web_page={'true' if settings['web_page'] else 'false'}")


if __name__ == "__main__":
    main()
