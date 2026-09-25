"""Capture one site and publish it as a GitHub release.

Runs inside the Actions job for one entry of the plan matrix (passed as JSON in $JOB):
  1. Crawl with Browsertrix Crawler in Docker, producing a WACZ web archive.
  2. Extract linked documents from the crawl, and fetch document links hosted elsewhere.
  3. Write crawl-report.md and publish everything as release archive/<slug>/<capture>-part<N>.
If the crawl stopped at its time or size limit, the release is a pre-release that includes the
crawler's saved state (crawl-state.yaml), and the next run continues from it.
"""

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from . import extract, pagelist

CRAWLER_IMAGE = "webrecorder/browsertrix-crawler:1.14.3"
# Stop each part before its WACZ could reach GitHub's 2 GiB limit for a release file.
PART_SIZE_LIMIT = 1_800_000_000
REPORT_LIST_LIMIT = 200


def run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=check)


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def crawler_command(site: dict, collection: str, crawls: Path, user_agent_suffix: str, state: Optional[Path]) -> List[str]:
    cmd = [
        "docker", "run", "--rm", "-v", f"{crawls.resolve()}:/crawls/", CRAWLER_IMAGE, "crawl",
        "--url", site["url"],
        "--collection", collection,
        "--generateWACZ",
        "--scopeType", site["scope"],
        "--workers", str(site["workers"]),
        "--timeLimit", str(int(site["time_limit_hours"] * 3600)),
        "--sizeLimit", str(PART_SIZE_LIMIT),
        "--statsFilename", "stats.json",
        "--userAgentSuffix", user_agent_suffix,
        "--blockAds",
    ]
    if site["respect_robots"]:
        cmd.append("--useRobots")
    # With a page limit (usually a quick test), sitemap entries would crowd out the starting page's links.
    if site["use_sitemap"] and not site["page_limit"]:
        cmd.append("--useSitemap")
    if site["page_limit"]:
        cmd += ["--pageLimit", str(site["page_limit"])]
    for pattern in site["exclude"]:
        cmd += ["--exclude", pattern]
    if state:
        cmd += ["--config", f"/crawls/{state.name}"]
    return cmd


def warc_streams(collection_dir: Path, wacz: Path) -> Iterator[Tuple[str, object]]:
    warcs = sorted((collection_dir / "archive").glob("*.warc*"))
    if warcs:
        for path in warcs:
            yield path.name, open(path, "rb")
    elif wacz.exists():
        with zipfile.ZipFile(wacz) as zf:
            for name in sorted(n for n in zf.namelist() if n.startswith("archive/") and ".warc" in n):
                yield name, zf.open(name)


def scan_collection(collection_dir: Path, wacz: Path, site: dict, tmp: Path) -> extract.ScanResult:
    """Scan every WARC in the collection. Records spanning files are rare; each file is scanned on its own."""
    total = extract.ScanResult()
    for name, stream in warc_streams(collection_dir, wacz):
        print(f"Scanning {name}", flush=True)
        with stream:
            part = extract.scan_warcs([stream], site["document_extensions"], tmp, site_files=site["site_files"])
        total.documents += part.documents
        total.site_files += part.site_files
        total.captured |= part.captured
        total.pages += part.pages
        for url, page in part.links.items():
            total.links.setdefault(url, page)
        for page in part.page_list:
            if page.url not in total.page_links:
                total.page_list.append(page)
                total.page_links[page.url] = part.page_links.get(page.url, [])
        for url, target in part.redirects.items():
            total.redirects.setdefault(url, target)
    for doc in total.documents:
        doc.linked_from = doc.linked_from or total.links.get(doc.url, "")
    return total


def write_report(path: Path, job: dict, stats: dict, wacz: Path, scan: extract.ScanResult,
                 failures: list, uncaptured: list, partial: bool, crawler_rc: int, repo_url: str) -> None:
    site = job["site"]
    crawl_docs = [d for d in scan.documents if d.source == "crawl"]
    offsite_docs = [d for d in scan.documents if d.source == "offsite"]
    lines = [
        f"# {site['url']}",
        "",
        f"Capture `{job['capture']}`, part {job['part']}" + (" — **incomplete, continues on the next run**" if partial else ""),
        "",
        "| | |",
        "|---|---|",
        f"| Pages captured | {stats.get('crawled', scan.pages)} |",
        f"| Pages failed | {stats.get('failed', 'unknown')} |",
        f"| Pages still queued | {stats.get('pending', 'unknown')} |",
        f"| Web archive (WACZ) | {human(wacz.stat().st_size) if wacz.exists() else 'not produced'} |",
        f"| Documents from the site | {len(crawl_docs)} ({human(sum(d.size for d in crawl_docs))}) |",
        f"| Documents from other sites | {len(offsite_docs)} ({human(sum(d.size for d in offsite_docs))}) |",
        *([f"| Site files | {len(scan.site_files)} ({human(sum(d.size for d in scan.site_files))}) |"] if site["site_files"] else []),
        f"| Scope | {site['scope']}, robots.txt {'respected' if site['respect_robots'] else 'ignored'}"
        + (f", page limit {site['page_limit']}" if site["page_limit"] else "") + " |",
        f"| Crawler | `{CRAWLER_IMAGE}` (exit code {crawler_rc}) |",
        "",
        "## How to use these files",
        "",
        "- **Browse the site as captured:** open https://replayweb.page and choose the `.wacz` file. "
        "It runs in your browser; nothing is uploaded.",
        "- **Documents:** `documents.zip` holds every linked document as an ordinary file, in folders by "
        "website and path. `documents.csv` lists each file's source URL, the page that linked to it, and its SHA-256.",
    ]
    if site["site_files"]:
        lines.append(
            "- **Site files:** `site-files.zip` holds every file the crawl captured (HTML, CSS, scripts, images, fonts, "
            "documents) exactly as the server sent it, in folders by website and path. `site-files.csv` indexes them."
        )
    if partial:
        lines += [
            "",
            "## Incomplete capture",
            "",
            "The crawl reached its time or size limit for one run. `crawl-state.yaml` records where it stopped; "
            "the next scheduled run continues as the next part. Together, all parts of this capture make up the full archive.",
        ]
    if uncaptured:
        lines += ["", f"## Linked documents on the site that were not captured ({len(uncaptured)})", "",
                  "Blocked by robots.txt, beyond a limit, or failed to load.", ""]
        lines += [f"- {url} (linked from {page})" for url, page in uncaptured[:REPORT_LIST_LIMIT]]
        if len(uncaptured) > REPORT_LIST_LIMIT:
            lines.append(f"- … and {len(uncaptured) - REPORT_LIST_LIMIT} more")
    if failures:
        lines += ["", f"## Documents on other sites that could not be fetched ({len(failures)})", ""]
        lines += [f"- {url}: {reason} (linked from {page})" for url, page, reason in failures[:REPORT_LIST_LIMIT]]
        if len(failures) > REPORT_LIST_LIMIT:
            lines.append(f"- … and {len(failures) - REPORT_LIST_LIMIT} more")
    lines += ["", f"Made with [{repo_url.rsplit('/', 1)[-1]}]({repo_url})."]
    machine = {"pages": int(stats.get("crawled", scan.pages) or 0), "failed": int(stats.get("failed", 0) or 0),
               "documents": len(crawl_docs), "offsite_documents": len(offsite_docs)}
    if site["site_files"]:
        machine["site_files"] = len(scan.site_files)
    # Read by the dashboard; invisible when the report is shown on GitHub.
    lines += ["", f"<!-- capture-stats {json.dumps(machine)} -->"]
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    job = json.loads(os.environ["JOB"])
    site = job["site"]
    repo_url = os.environ.get("REPO_URL", "")
    slug, part = job["slug"], job["part"]
    collection = f"{slug}-{job['capture'].lower()}-part{part}"
    tag = f"archive/{slug}/{job['capture']}-part{part}"

    work = Path("work")
    crawls, out, tmp = work / "crawls", work / "out", work / "tmp"
    for d in (crawls, out, tmp):
        d.mkdir(parents=True, exist_ok=True)

    state = None
    if job.get("resume_tag"):
        got = run(["gh", "release", "download", job["resume_tag"], "-p", "crawl-state.yaml", "-D", str(crawls)], check=False)
        if got.returncode == 0:
            state = crawls / "crawl-state.yaml"
        else:
            print("::warning::No saved crawl state on the previous part; starting this part from the beginning.")

    run(["docker", "pull", "-q", CRAWLER_IMAGE])
    crawler_rc = run(crawler_command(site, collection, crawls, f"+SiteArchiver ({repo_url})", state), check=False).returncode

    collection_dir = crawls / "collections" / collection
    wacz = collection_dir / f"{collection}.wacz"
    stats_file = crawls / "stats.json"
    stats = json.loads(stats_file.read_text()) if stats_file.exists() else {}
    # The crawler writes <timestamp>-<id>-<collection>.yaml here when it stops before finishing.
    saved_states = sorted((collection_dir / "crawls").glob("*.yaml"), key=lambda p: p.stat().st_mtime)
    partial = bool(saved_states)

    if not wacz.exists():
        print(f"::error::The crawler did not produce a web archive (exit code {crawler_rc}).")
        return 1

    scan = scan_collection(collection_dir, wacz, site, tmp)
    user_agent = f"Mozilla/5.0 (compatible; SiteArchiver; +{repo_url})"
    failures = []
    if site["offsite_documents"]:
        robots = extract.RobotsCache(user_agent) if site["respect_robots"] else None
        failures = extract.fetch_offsite(scan, site, tmp, extract.http_fetcher(user_agent), robots)
    uncaptured = extract.uncaptured_in_scope(scan, site)

    assets = [out / f"{slug}-{job['capture'].lower()}-part{part}.wacz"]
    run(["cp", str(wacz), str(assets[0])])
    assets += extract.write_outputs(scan.documents, out)
    # Each document also as its own release file, so the page list can link straight to it.
    doc_assets = {}
    if len(scan.documents) <= pagelist.MAX_DOCUMENT_ASSETS:
        files_dir, used = out / "files", set()
        files_dir.mkdir(exist_ok=True)
        for doc in scan.documents:
            if doc.size < pagelist.MAX_ASSET_BYTES:
                name = pagelist.asset_name(doc.sha256, doc.filename or doc.url, used)
                shutil.copyfile(doc.tmp_path, files_dir / name)
                assets.append(files_dir / name)
                doc_assets[id(doc)] = name
    else:
        print(f"::notice::{len(scan.documents)} documents: too many to upload one by one; they are in documents.zip.")
    site_paths = {}
    if site["site_files"]:
        assets += extract.write_outputs(scan.site_files, out, name="site-files")
        for f in scan.site_files:
            site_paths.setdefault(f.url, f"{f.zip_file} › {f.path}")
        extract.cleanup(scan.site_files)
    release_url = f"{repo_url}/releases/tag/{tag}"
    index = pagelist.build_index(site, slug, job["capture"], part, release_url, f"{repo_url}/releases/download/{tag}/",
                                 assets[0].name, scan, doc_assets, site_paths)
    extract.cleanup(scan.documents)
    (out / "capture-index.json").write_text(json.dumps(index))
    assets.append(out / "capture-index.json")
    if partial:
        run(["cp", str(saved_states[-1]), str(out / "crawl-state.yaml")])
        assets.append(out / "crawl-state.yaml")
    report = out / "crawl-report.md"
    write_report(report, job, stats, wacz, scan, failures, uncaptured, partial, crawler_rc, repo_url)
    assets.append(report)
    print(report.read_text())

    title = f"{slug} — {job['capture'][:4]}-{job['capture'][4:6]}-{job['capture'][6:8]}"
    title += f" (part {part}{', incomplete' if partial else ''})" if part > 1 or partial else ""
    cmd = ["gh", "release", "create", tag, *map(str, assets), "--title", title,
           "--notes-file", str(report), "--target", os.environ.get("GITHUB_SHA", "main")]
    if partial:
        cmd.append("--prerelease")
    run(cmd)
    if job.get("resume_tag"):
        # The previous part is now continued; mark it as a finished part so it isn't resumed again.
        run(["gh", "release", "edit", job["resume_tag"], "--prerelease=false"], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
