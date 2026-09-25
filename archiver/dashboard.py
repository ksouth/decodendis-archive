"""Build DASHBOARD.md and docs/index.html: what each site has captured.

Reads sites.yaml and the repository's releases (JSON lines from
`gh api --paginate repos/<owner>/<repo>/releases --jq '.[]'`).
"""

import argparse
import html
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import SCHEDULE_DAYS, load_dashboard_settings, load_sites
from .plan import STAMP_FORMAT, TAG_RE

STATS_RE = re.compile(r"<!-- capture-stats (\{.*?\}) -->")
# Older reports, written before the stats comment existed.
TABLE_ROWS = {
    "pages": r"\| Pages captured \| (\d+)",
    "failed": r"\| Pages failed \| (\d+)",
    "documents": r"\| Documents from the site \| (\d+)",
    "offsite_documents": r"\| Documents from other sites \| (\d+)",
    "site_files": r"\| Site files \| (\d+)",
}


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


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def capture_date(capture: str) -> datetime:
    return datetime.strptime(capture, STAMP_FORMAT).replace(tzinfo=timezone.utc)


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
        last = rels[-1]
        by_site[slug].append({
            "capture": capture,
            "date": capture_date(capture),
            "parts": rels[-1]["part"],
            "complete": not last.get("prerelease"),
            "size": sum(a.get("size", 0) for r in rels for a in r.get("assets", [])),
            "url": last.get("html_url", ""),
            **totals,
        })
    for captures in by_site.values():
        captures.sort(key=lambda c: c["capture"], reverse=True)
    return by_site


def site_row(slug: str, url: str, schedule: str, captures: List[Dict[str, Any]], now: datetime,
             max_parts: Optional[int] = None) -> Dict[str, Any]:
    """max_parts is None for sites not in sites.yaml, whose incomplete captures are never continued."""
    latest = captures[0] if captures else None
    if latest is None:
        status, next_run = ("off", "—") if schedule == "off" else ("waiting", "next run")
    elif not latest["complete"]:
        if max_parts is None or schedule == "off" or latest["parts"] >= max_parts:
            status, next_run = "stopped", "—"
        else:
            status, next_run = "in progress", "continuing"
    else:
        status = "complete"
        if schedule in SCHEDULE_DAYS:
            due = latest["date"] + timedelta(days=SCHEDULE_DAYS[schedule])
            next_run = "next run" if due <= now else due.strftime("%Y-%m-%d")
        else:
            next_run = "—"
    return {"slug": slug, "url": url, "schedule": schedule, "status": status, "next": next_run,
            "latest": latest, "count": len(captures)}


def build(sites: List[Dict[str, Any]], releases: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    captures = group_captures(releases)
    listed = [site_row(s["slug"], s["url"], s["schedule"], captures.get(s["slug"], []), now, s["max_parts"])
              for s in sites]
    names = {s["slug"] for s in sites}
    other = [site_row(slug, "", "not in sites.yaml", caps, now) for slug, caps in sorted(captures.items()) if slug not in names]
    dates = [c["date"] for caps in captures.values() for c in caps]
    return {"sites": listed, "other": other, "updated": max(dates) if dates else None}


STATUS_ICONS = {"complete": "✅", "in progress": "⏳", "waiting": "🕓", "off": "⏸️", "stopped": "⚠️"}


def cells(row: Dict[str, Any]) -> Dict[str, str]:
    c = row["latest"]
    return {
        "status": row["status"] + (f" after part {c['parts']}" if c and row["status"] == "stopped"
                                   else f" (part {c['parts']})" if c and row["status"] == "in progress" else ""),
        "date": c["date"].strftime("%Y-%m-%d") if c else "never",
        "pages": f"{c.get('pages', 0):,}" if c else "—",
        "documents": f"{c.get('documents', 0) + c.get('offsite_documents', 0):,}" if c else "—",
        "site_files": f"{c['site_files']:,}" if c and "site_files" in c else "—",
        "size": human(c["size"]) if c else "—",
    }


def render_md(model: Dict[str, Any], repo_url: str) -> str:
    updated = model["updated"].strftime("%Y-%m-%d %H:%M UTC") if model["updated"] else "no captures yet"
    lines = [
        "# Archive dashboard",
        "",
        f"Rebuilt automatically after each run. Latest capture: {updated}. "
        f"All captures are under [Releases]({repo_url}/releases).",
        "",
    ]

    def table(rows, show_url):
        out = ["| Site | Schedule | Last capture | Status | Pages | Documents | Site files | Size | Next | Captures |",
               "|---|---|---|---|---|---|---|---|---|---|"]
        for row in rows:
            v = cells(row)
            name = f"**{row['slug']}**" + (f"<br>{row['url']}" if show_url and row["url"] else "")
            date = f"[{v['date']}]({row['latest']['url']})" if row["latest"] else v["date"]
            out.append(f"| {name} | {row['schedule']} | {date} | {STATUS_ICONS.get(row['status'], '')} {v['status']} "
                       f"| {v['pages']} | {v['documents']} | {v['site_files']} | {v['size']} | {row['next']} | {row['count']} |")
        return out

    if model["sites"]:
        lines += table(model["sites"], True)
    else:
        lines.append("No sites in `sites.yaml` yet. Add one to start archiving.")
    if model["other"]:
        lines += ["", "## Other captures", "",
                  "Captures of sites that aren't in `sites.yaml`, such as one-off runs from the Run workflow form.", ""]
        lines += table(model["other"], False)
    lines += ["", "Pages, documents and size cover every part of the latest capture. "
              "Documents include those fetched from other websites."]
    return "\n".join(lines) + "\n"


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Archive dashboard</title>
<style>
:root {{ --bg:#fbfbf9; --fg:#1d1d1b; --muted:#6b6b66; --line:#e3e2dc; --card:#fff; --accent:#2f5d8a;
  --ok:#2e7d4f; --run:#9a6700; --wait:#6b6b66; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#161615; --fg:#ecebe6; --muted:#a3a29b; --line:#33322e;
  --card:#1f1f1d; --accent:#8db8e3; --ok:#6fcf97; --run:#e3b341; --wait:#a3a29b; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:32px 16px 48px; }}
h1 {{ font-size:26px; margin:0 0 4px; }} h2 {{ font-size:18px; margin:36px 0 4px; }}
p.lede, p.note {{ color:var(--muted); margin:0 0 20px; }}
a {{ color:var(--accent); }}
.wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:10px; background:var(--card); }}
table {{ border-collapse:collapse; width:100%; min-width:760px; }}
th, td {{ text-align:left; padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top; }}
th {{ font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); font-weight:600; }}
tr:last-child td {{ border-bottom:0; }}
td.num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }} td.date {{ white-space:nowrap; }} th.num {{ text-align:right; }}
.site {{ font-weight:600; }} .url {{ display:block; font-size:13px; color:var(--muted); word-break:break-all; }}
.status {{ font-weight:600; white-space:nowrap; }}
@media (max-width: 700px) {{
  table, tbody, tr, td {{ display:block; min-width:0; }}
  tr.head {{ display:none; }}
  tr {{ padding:10px 0; border-bottom:1px solid var(--line); }} tr:last-child {{ border-bottom:0; }}
  td {{ display:flex; justify-content:space-between; gap:16px; padding:3px 14px; border:0; text-align:right; }}
  td::before {{ content:attr(data-label); color:var(--muted); font-size:12px; text-transform:uppercase;
    letter-spacing:.04em; text-align:left; flex:none; }}
  td.name {{ display:block; text-align:left; padding-bottom:6px; }} td.name::before {{ content:none; }}
}}
.complete {{ color:var(--ok); }} .in-progress, .stopped {{ color:var(--run); }} .waiting, .off {{ color:var(--wait); }}
</style>
</head>
<body>
<main>
<h1>Archive dashboard</h1>
<p class="lede">Latest capture: {updated}. Every capture is under <a href="{repo_url}/releases">Releases</a>;
open a <code>.wacz</code> file at <a href="https://replayweb.page">replayweb.page</a> to browse it.</p>
{sections}
<p class="note">Rebuilt automatically after each run. Pages, documents and size cover every part of the latest capture.</p>
</main>
</body>
</html>
"""


def render_html(model: Dict[str, Any], repo_url: str) -> str:
    esc = html.escape

    def table(rows, show_url):
        head = ("<tr class=head><th>Site</th><th>Schedule</th><th>Last capture</th><th>Status</th><th class=num>Pages</th>"
                "<th class=num>Documents</th><th class=num>Site files</th><th class=num>Size</th><th>Next</th>"
                "<th class=num>Captures</th></tr>")
        body = []
        for row in rows:
            v = cells(row)
            url = f'<a class="url" href="{esc(row["url"])}">{esc(row["url"])}</a>' if show_url and row["url"] else ""
            date = f'<a href="{esc(row["latest"]["url"])}">{v["date"]}</a>' if row["latest"] else v["date"]
            body.append(
                f'<tr><td class="name"><span class="site">{esc(row["slug"])}</span>{url}</td>'
                f'<td data-label="Schedule">{esc(row["schedule"])}</td>'
                f'<td class="date" data-label="Last capture">{date}</td>'
                f'<td class="status {row["status"].replace(" ", "-")}" data-label="Status">{esc(v["status"])}</td>'
                f'<td class=num data-label="Pages">{v["pages"]}</td>'
                f'<td class=num data-label="Documents">{v["documents"]}</td>'
                f'<td class=num data-label="Site files">{v["site_files"]}</td>'
                f'<td class=num data-label="Size">{v["size"]}</td>'
                f'<td data-label="Next">{esc(row["next"])}</td>'
                f'<td class=num data-label="Captures">{row["count"]}</td></tr>'
            )
        return f'<div class="wrap"><table>{head}{"".join(body)}</table></div>'

    sections = table(model["sites"], True) if model["sites"] else \
        "<p>No sites in <code>sites.yaml</code> yet. Add one to start archiving.</p>"
    if model["other"]:
        sections += ("<h2>Other captures</h2><p class=note>Sites that aren't in <code>sites.yaml</code>, "
                     "such as one-off runs from the Run workflow form.</p>" + table(model["other"], False))
    updated = model["updated"].strftime("%Y-%m-%d %H:%M UTC") if model["updated"] else "no captures yet"
    return HTML_TEMPLATE.format(updated=esc(updated), repo_url=esc(repo_url), sections=sections)


def load_releases(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sites", default="sites.yaml")
    parser.add_argument("--releases", required=True, help="JSON lines of GitHub releases")
    parser.add_argument("--repo-url", required=True)
    parser.add_argument("--md", default="DASHBOARD.md")
    parser.add_argument("--html", default="docs/index.html")
    args = parser.parse_args()
    settings = load_dashboard_settings(Path(args.sites))
    model = build(load_sites(Path(args.sites)), load_releases(Path(args.releases)), datetime.now(timezone.utc))
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
