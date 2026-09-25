"""The page list for a capture: every page and document it captured.

run.py writes capture-index.json into each release (one per part). The dashboard job
downloads them and renders one web page per capture with render_page().
"""

import html
import re
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Set, Tuple
from urllib.parse import unquote, urlsplit

INDEX_VERSION = 1
# A release holds at most 1000 files; leave room for the archive, zips and reports.
MAX_DOCUMENT_ASSETS = 900
# GitHub release files must be under 2 GiB.
MAX_ASSET_BYTES = 2_000_000_000

TYPE_NAMES = {
    "text/html": "Web page", "application/xhtml+xml": "Web page",
    "application/pdf": "PDF",
    "application/msword": "Word document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word document",
    "application/vnd.oasis.opendocument.text": "Text document",
    "application/rtf": "Rich text document",
    "application/vnd.ms-excel": "Excel spreadsheet",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel spreadsheet",
    "application/vnd.oasis.opendocument.spreadsheet": "Spreadsheet",
    "text/csv": "CSV spreadsheet",
    "application/vnd.ms-powerpoint": "PowerPoint presentation",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint presentation",
    "application/zip": "ZIP archive",
    "application/epub+zip": "EPUB book",
    "text/plain": "Text file",
    "application/json": "JSON data", "application/xml": "XML data", "text/xml": "XML data",
}
EXTENSION_NAMES = {".pdf": "PDF", ".doc": "Word document", ".docx": "Word document", ".xls": "Excel spreadsheet",
                   ".xlsx": "Excel spreadsheet", ".csv": "CSV spreadsheet", ".ppt": "PowerPoint presentation",
                   ".pptx": "PowerPoint presentation", ".zip": "ZIP archive", ".rtf": "Rich text document",
                   ".txt": "Text file", ".odt": "Text document", ".ods": "Spreadsheet", ".epub": "EPUB book"}


def type_name(content_type: str, name_or_url: str = "") -> str:
    """A plain description of a file type, e.g. "PDF" or "Word document"."""
    ext = PurePosixPath(unquote(urlsplit(name_or_url).path) or name_or_url).suffix.lower()
    if content_type in TYPE_NAMES and content_type not in ("application/octet-stream",):
        return TYPE_NAMES[content_type]
    if ext in EXTENSION_NAMES:
        return EXTENSION_NAMES[ext]
    return ext[1:].upper() + " file" if ext else (content_type or "File")


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def _variants(url: str) -> List[str]:
    """The same address with and without a trailing slash and www."""
    parts = urlsplit(url)
    host = parts.netloc
    hosts = {host, host[4:] if host.startswith("www.") else "www." + host}
    paths = {parts.path or "/", (parts.path or "/").rstrip("/") or "/", (parts.path or "") + "/"}
    out = [url]
    for h in hosts:
        for p in paths:
            out.append(parts._replace(netloc=h, path=p).geturl())
    return out


def find_home(seed: str, page_urls: Iterable[str], redirects: Dict[str, str]) -> str:
    """The captured page for the site's start address, following redirects; else the first page captured."""
    urls = list(page_urls)
    captured = set(urls)
    current, seen = seed, set()
    while current not in seen:
        seen.add(current)
        for candidate in _variants(current):
            if candidate in captured:
                return candidate
        target = next((redirects[c] for c in _variants(current) if c in redirects), None)
        if not target:
            break
        current = target
    return urls[0] if urls else ""


def asset_name(sha256: str, filename_or_url: str, used: Set[str]) -> str:
    """A release file name for one document: safe characters only, so its download address is predictable."""
    base = PurePosixPath(unquote(urlsplit(filename_or_url).path) or filename_or_url).name or "document"
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-.") or "document"
    stem, dot, ext = base.rpartition(".") if "." in base else (base, "", "")
    name = f"doc-{sha256[:8]}-{stem[:80]}{dot}{ext[:10]}"
    candidate, n = name, 2
    while candidate.lower() in used:
        candidate = f"doc-{sha256[:8]}-{n}-{stem[:80]}{dot}{ext[:10]}"
        n += 1
    used.add(candidate.lower())
    return candidate


def format_label(in_wacz: bool, in_site_files: bool) -> str:
    """Which capture format holds an item: WACZ (the web archive), Site (site-files.zip), or both."""
    if in_wacz and in_site_files:
        return "WACZ + Site"
    if in_wacz:
        return "WACZ"
    if in_site_files:
        return "Site"
    return "documents.zip"  # a document fetched from another website: in neither format


# ---------- Rendering ----------

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#fbfbf9; --fg:#1d1d1b; --muted:#6b6b66; --line:#e3e2dc; --card:#fff; --accent:#2f5d8a; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#161615; --fg:#ecebe6; --muted:#a3a29b; --line:#33322e;
  --card:#1f1f1d; --accent:#8db8e3; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:900px; margin:0 auto; padding:24px 16px 48px; }}
a {{ color:var(--accent); }}
h1 {{ font-size:24px; margin:4px 0; word-break:break-word; }}
h2 {{ font-size:18px; margin:32px 0 8px; }}
h3 {{ font-size:15px; margin:20px 0 8px; color:var(--muted); font-weight:600; word-break:break-all; }}
.back {{ font-size:14px; }}
.lede {{ color:var(--muted); margin:0 0 16px; }}
.notice {{ margin:0 0 16px; padding:10px 14px; border:1px solid var(--line); border-left:3px solid var(--accent);
  border-radius:6px; background:var(--card); }}
.summary {{ display:flex; flex-wrap:wrap; gap:8px 20px; margin:0 0 16px; padding:0; list-style:none; }}
.summary li {{ color:var(--muted); }} .summary strong {{ color:var(--fg); }}
input[type=search] {{ width:100%; padding:10px 12px; border:1px solid var(--line); border-radius:8px;
  background:var(--card); color:var(--fg); font:inherit; margin:8px 0 4px; }}
ul.items {{ list-style:none; margin:0; padding:0; border:1px solid var(--line); border-radius:10px; background:var(--card); }}
ul.items > li {{ padding:12px 14px; border-bottom:1px solid var(--line); }}
ul.items > li:last-child {{ border-bottom:0; }}
.name {{ font-weight:600; word-break:break-word; }}
.addr {{ display:block; font-size:13px; word-break:break-all; margin:2px 0 6px; }}
dl {{ display:grid; grid-template-columns:max-content 1fr; gap:2px 14px; margin:0; font-size:14px; }}
dt {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; padding-top:2px; }}
dd {{ margin:0; }}
.download {{ font-weight:600; }}
code {{ font-size:12px; word-break:break-all; }}
.empty {{ color:var(--muted); }}
[hidden] {{ display:none !important; }}
</style>
</head>
<body>
<main>
<p class="back"><a href="{dashboard_url}">Back to the dashboard</a></p>
<h1>{heading}</h1>
<p class="lede">{lede}</p>
<ul class="summary">{summary}</ul>
<p class="notice"><strong>Format</strong> is <strong>WACZ</strong> for items in the web archive,
<strong>Site</strong> for items in site-files.zip, or both. <strong>File</strong> shows where each is kept.<br>
<strong>Links:</strong> each <strong>address</strong> opens the page on the live website, which may
have changed since this capture. <strong>Download</strong> links, and the file names under <strong>File</strong>,
download that file straight away from this archive; a .zip or .wacz can be large. To see pages as they were captured, download the web archive (.wacz) from the
<a href="{release_url}">release page</a> and open it at <a href="https://replayweb.page">replayweb.page</a>.</p>
<label for="filter" class="lede">Filter this list</label>
<input type="search" id="filter" placeholder="Type part of a name or address">
{sections}
</main>
<script>
function zoneAbbr(d) {{
  var fmt = function (style) {{
    try {{
      var p = new Intl.DateTimeFormat(undefined, {{ timeZoneName: style }}).formatToParts(d)
        .filter(function (x) {{ return x.type === "timeZoneName"; }})[0];
      return p ? p.value : "";
    }} catch (e) {{ return ""; }}
  }};
  var s = fmt("shortGeneric");
  if (/^[A-Z]{{2,5}}$/.test(s)) return s;  // already an abbreviation, e.g. "PT"
  var long = fmt("longGeneric") || fmt("long");  // e.g. "Australian Eastern Time" -> "AET"
  if (long && !/^(GMT|UTC)/.test(long)) return long.split(/\\s+/).map(function (w) {{ return w[0]; }}).join("").toUpperCase();
  return s || long || "";
}}
document.querySelectorAll("time[datetime]").forEach(function (el) {{
  var d = new Date(el.getAttribute("datetime"));
  if (isNaN(d)) return;
  el.textContent = d.toLocaleDateString(undefined, {{ day: "numeric", month: "short", year: "numeric" }}) + ", " +
    d.toLocaleTimeString(undefined, {{ hour: "numeric", minute: "2-digit", hour12: true }}) + " (" + zoneAbbr(d) + ")";
}});
var filter = document.getElementById("filter");
filter.addEventListener("input", function () {{
  var q = filter.value.trim().toLowerCase();
  document.querySelectorAll("ul.items > li").forEach(function (li) {{
    li.hidden = q && li.textContent.toLowerCase().indexOf(q) === -1;
  }});
  document.querySelectorAll("section[data-group]").forEach(function (s) {{
    s.hidden = q && !s.querySelector("ul.items > li:not([hidden])");
  }});
}});
</script>
</body>
</html>
"""


def _time(value: str) -> str:
    """A WARC or ISO timestamp as a <time> element (the page's script shows it in local time)."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})", value or "")
    if not m:
        return html.escape(value or "unknown")
    return f'<time datetime="{html.escape(value)}">{m.group(1)} {m.group(2)} UTC</time>'


def _item(entry: Dict[str, Any], document: bool) -> str:
    esc = html.escape
    name = entry.get("title") or entry.get("name") or PurePosixPath(urlsplit(entry["url"]).path).name or entry["url"]
    def file_html(f):
        # Older indexes list plain strings; newer ones {"text", "url"} so each file name downloads that file.
        if isinstance(f, dict) and f.get("url"):
            return f'<a href="{esc(f["url"])}"><code>{esc(f["text"])}</code></a>'
        return f"<code>{esc(f['text'] if isinstance(f, dict) else f)}</code>"
    files = "<br>".join(file_html(f) for f in entry.get("files", []))
    rows = [("Format", f'<strong>{esc(entry.get("format", ""))}</strong>'), ("Type", esc(entry["type"])),
            ("Size", human(entry.get("size", 0))), ("Captured", _time(entry.get("captured_at", ""))), ("File", files)]
    if document:
        if entry.get("linked_from"):
            rows.append(("Linked from", f'<a href="{esc(entry["linked_from"])}">{esc(entry["linked_from"])}</a>'))
        if entry.get("download_url"):
            rows.insert(0, ("Download", f'<a class="download" href="{esc(entry["download_url"])}">Download '
                                        f'{esc(entry["type"])}, {human(entry.get("size", 0))}</a>'))
        else:
            rows.insert(0, ("Download", "in documents.zip on the release page"))
    dl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
    return (f'<li><div class="name">{esc(name)}</div><a class="addr" href="{esc(entry["url"])}">{esc(entry["url"])}</a>'
            f"<dl>{dl}</dl></li>")


def _section(title: str, entries: List[Dict[str, Any]], document: bool = False, level: str = "h2") -> str:
    if not entries:
        return ""
    items = "".join(_item(e, document) for e in entries)
    return (f'<section data-group><{level}>{html.escape(title)} ({len(entries)})</{level}>'
            f'<ul class="items">{items}</ul></section>')


def group_key(url: str, home_host: str) -> Tuple[int, str, str]:
    """(0 = the site's own host, 1 = its subdomains, 2 = unrelated websites, host, first folder)."""
    parts = urlsplit(url)
    host = parts.netloc.lower()
    bare = lambda h: h[4:] if h.startswith("www.") else h
    segments = [s for s in parts.path.split("/") if s]
    folder = segments[0] if len(segments) > 1 else ""
    if bare(host) == bare(home_host.lower()):
        rank = 0
    elif host.endswith("." + bare(home_host.lower())):
        rank = 1
    else:
        rank = 2  # e.g. an embedded YouTube video the crawler captured with a page
    return (rank, host, folder)


def merge_parts(indexes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Combine the page lists of every part of one capture."""
    indexes = sorted(indexes, key=lambda i: i.get("part", 1))
    first = indexes[0]
    pages, docs, seen_pages, seen_docs = [], [], set(), set()
    for index in indexes:
        for page in index.get("pages", []):
            if page["url"] not in seen_pages:
                seen_pages.add(page["url"])
                pages.append(page)
        for doc in index.get("documents", []):
            key = (doc["url"], doc.get("sha256"))
            if key not in seen_docs:
                seen_docs.add(key)
                docs.append(doc)
    return {**first, "pages": pages, "documents": docs, "parts": len(indexes),
            "release_urls": [i.get("release_url", "") for i in indexes]}


def render_page(indexes: List[Dict[str, Any]], dashboard_url: str) -> str:
    esc = html.escape
    index = merge_parts(indexes)
    pages = index["pages"]
    home_url = index.get("home") or (pages[0]["url"] if pages else "")
    by_url = {p["url"]: p for p in pages}
    home = by_url.get(home_url)
    home_links = [u for u in dict.fromkeys(index.get("home_links", [])) if u in by_url and u != home_url]
    listed = set(home_links) | {home_url}
    rest = [p for p in pages if p["url"] not in listed]
    home_host = urlsplit(home_url or index.get("site", "")).netloc

    sections = []
    if home:
        sections.append(_section("Home page", [home]))
    sections.append(_section("Linked from the home page", [by_url[u] for u in home_links]))
    groups: Dict[Tuple[int, str, str], List[Dict[str, Any]]] = {}
    for page in rest:
        groups.setdefault(group_key(page["url"], home_host), []).append(page)
    if groups:
        sections.append("<h2>Other pages, by folder and subdomain</h2>")
        for (rank, host, folder), entries in sorted(groups.items()):
            label = f"{host}/{folder}/" if folder else f"{host}/ (top level)"
            if rank == 2:
                label = f"Embedded from other websites: {label}"
            entries.sort(key=lambda p: p["url"])
            sections.append(_section(label, entries, level="h3"))
    docs = index["documents"]
    site_docs = [d for d in docs if d.get("source") != "offsite"]
    other_docs = [d for d in docs if d.get("source") == "offsite"]
    if docs:
        sections.append(f"<h2>Documents ({len(docs)})</h2>")
        sections.append(_section("From this website", sorted(site_docs, key=lambda d: d["url"]), True, "h3"))
        sections.append(_section("From other websites", sorted(other_docs, key=lambda d: d["url"]), True, "h3"))
    else:
        sections.append('<h2>Documents</h2><p class="empty">No documents were captured.</p>')

    capture = index.get("capture", "")
    when = f"{capture[:4]}-{capture[4:6]}-{capture[6:8]}" if len(capture) >= 8 else capture
    parts = index["parts"]
    release_links = ", ".join(f'<a href="{esc(u)}">part {n}</a>' for n, u in enumerate(index["release_urls"], 1) if u)
    summary = [f"<li><strong>{len(pages):,}</strong> pages</li>", f"<li><strong>{len(docs):,}</strong> documents</li>",
               f"<li>Captured in <strong>{parts}</strong> part{'s' if parts != 1 else ''}</li>",
               f"<li>Release: {release_links or 'none'}</li>"]
    return PAGE_TEMPLATE.format(
        title=esc(f"{index.get('slug', '')} capture {when}"),
        heading=esc(index.get("site", "")),
        lede=f"Page list for the capture of {when}: every page and document captured, and where each is kept.",
        summary="".join(summary),
        release_url=esc(index["release_urls"][-1] if index["release_urls"] else ""),
        dashboard_url=esc(dashboard_url),
        sections="".join(s for s in sections if s),
    )


# ---------- Building the index at capture time ----------

def build_index(site: Dict[str, Any], slug: str, capture: str, part: int, release_url: str, download_base: str,
                wacz_name: str, scan: Any, doc_assets: Dict[int, str], site_paths: Dict[str, str]) -> Dict[str, Any]:
    """The capture-index.json for one part. scan is an extract.ScanResult; doc_assets maps id(document) to the
    release file uploaded for it; site_paths maps a URL to its place in site-files.zip."""
    def zip_file(location: str) -> Dict[str, str]:
        """'site-files.zip › path' -> a link to download that zip."""
        return {"text": location, "url": download_base + location.split(" › ", 1)[0]}

    wacz = {"text": wacz_name, "url": download_base + wacz_name}
    pages_out = []
    for page in scan.page_list:
        in_site = page.url in site_paths
        pages_out.append({
            "url": page.url, "title": page.title, "type": type_name(page.content_type, page.url),
            "content_type": page.content_type, "size": page.size, "captured_at": page.captured_at,
            "format": format_label(True, in_site),
            "files": [wacz] + ([zip_file(site_paths[page.url])] if in_site else []),
        })
    docs_out = []
    for doc in scan.documents:
        in_wacz = doc.source == "crawl"
        in_site = doc.url in site_paths
        name = doc.filename or PurePosixPath(unquote(urlsplit(doc.url).path)).name or doc.url
        asset = doc_assets.get(id(doc))
        files = ([{"text": asset, "url": download_base + asset}] if asset else []) + ([wacz] if in_wacz else [])
        files += [zip_file(f"{doc.zip_file} › {doc.path}")] + ([zip_file(site_paths[doc.url])] if in_site else [])
        docs_out.append({
            "url": doc.url, "name": name, "type": type_name(doc.content_type, doc.filename or doc.url),
            "content_type": doc.content_type, "size": doc.size, "sha256": doc.sha256, "captured_at": doc.captured_at,
            "source": "offsite" if doc.source == "offsite" else "site", "linked_from": doc.linked_from,
            "format": format_label(in_wacz, in_site), "files": files,
            "download_url": download_base + asset if asset else "",
        })
    home = find_home(site["url"], [p.url for p in scan.page_list], scan.redirects)
    return {"version": INDEX_VERSION, "site": site["url"], "slug": slug, "capture": capture, "part": part,
            "release_url": release_url, "home": home, "home_links": scan.page_links.get(home, []),
            "pages": pages_out, "documents": docs_out}
