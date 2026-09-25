"""Pull linked documents out of a crawl's WARC files, and fetch documents hosted elsewhere.

Output:
  documents.zip (or documents-1.zip, documents-2.zip, ... if over the size limit)
  documents.csv  one row per file: where it is in the zip, source URL, the page that linked
                 it, type, size, SHA-256, and whether it came from the crawl or an offsite fetch
"""

import csv
import hashlib
import mimetypes
import os
import re
import tempfile
import time
import urllib.request
import urllib.robotparser
import zipfile
from dataclasses import dataclass, field
from html import unescape as html_unescape
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

from warcio.archiveiterator import ArchiveIterator

# Types that count as documents even when the URL has no telling extension.
DOCUMENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/rtf",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.presentation",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/zip",
    "application/epub+zip",
    "text/csv",
}
# GitHub release assets must be under 2 GiB.
ZIP_PART_LIMIT = 1_900_000_000
MAX_HTML_BYTES = 20_000_000
# Many sites serve documents from links without a file extension, e.g. /media/4907/download?attachment.
# Deliberately narrow: a broader pattern (e.g. any "/media/") also matches ordinary news pages.
DOWNLOAD_LINK_RE = re.compile(r"download|attachment|getfile|/media/\d+/|/sites/[^/]+/files/", re.IGNORECASE)
HTML_TYPES = ("text/html", "application/xhtml+xml")
# Extensions for extensionless URLs where mimetypes' choice is missing or unusual.
TYPE_EXTENSIONS = {"text/css": ".css", "text/javascript": ".js", "application/javascript": ".js",
                   "application/json": ".json", "image/jpeg": ".jpg", "image/svg+xml": ".svg",
                   "font/woff2": ".woff2", "font/woff": ".woff", "text/plain": ".txt"}
CSV_FIELDS = ["zip_file", "path", "url", "linked_from", "content_type", "size_bytes", "sha256", "source", "captured_at"]


@dataclass
class Document:
    url: str
    content_type: str
    size: int
    sha256: str
    source: str  # "crawl", "offsite", or "site" (a site file)
    captured_at: str
    tmp_path: Path
    linked_from: str = ""
    filename: str = ""  # from the server's Content-Disposition header, if any
    zip_file: str = ""
    path: str = ""


@dataclass
class Page:
    """A captured web page, for the capture's page list."""
    url: str
    title: str
    content_type: str
    size: int
    captured_at: str


@dataclass
class ScanResult:
    documents: List[Document] = field(default_factory=list)
    site_files: List[Document] = field(default_factory=list)  # every captured file, when requested
    links: Dict[str, str] = field(default_factory=dict)  # target URL -> first page linking it
    captured: Set[str] = field(default_factory=set)
    pages: int = 0
    page_list: List[Page] = field(default_factory=list)  # each captured page once, in capture order
    page_links: Dict[str, List[str]] = field(default_factory=dict)  # page URL -> links on that page
    redirects: Dict[str, str] = field(default_factory=dict)  # URL -> where it redirected


class LinkParser(HTMLParser):
    ATTRS = {"a": "href", "area": "href", "iframe": "src", "embed": "src", "object": "data"}

    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.links: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "base":
            href = dict(attrs).get("href")
            if href:
                self.base = urljoin(self.base, href)
            return
        attr = self.ATTRS.get(tag)
        if attr:
            value = dict(attrs).get(attr)
            if value and not value.startswith(("javascript:", "mailto:", "tel:", "data:", "#")):
                self.links.append(normalise_url(urljoin(self.base, value.strip())))


TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def page_title(text: str) -> str:
    m = TITLE_RE.search(text)
    return html_unescape(re.sub(r"\s+", " ", m.group(1)).strip()) if m else ""


def normalise_url(url: str) -> str:
    return urldefrag(url)[0]


def base_type(content_type: str) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def extension(url: str) -> str:
    return PurePosixPath(unquote(urlsplit(url).path)).suffix.lower()


def disposition_filename(header: str) -> str:
    """The filename in a Content-Disposition header, or ''."""
    if not header:
        return ""
    m = re.search(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", header, re.IGNORECASE)
    if m:
        name = unquote(m.group(1).strip().strip('"'))
    else:
        m = re.search(r'filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;]+)', header, re.IGNORECASE)
        name = (m.group(1) or m.group(2)).strip() if m else ""
    return PurePosixPath(name.replace("\\", "/")).name


def is_document(url: str, content_type: str, extensions: Iterable[str], disposition: str = "") -> bool:
    if base_type(content_type) in HTML_TYPES:
        return False
    extensions = set(extensions)
    return (
        extension(url) in extensions
        or base_type(content_type) in DOCUMENT_TYPES
        or PurePosixPath(disposition_filename(disposition)).suffix.lower() in extensions
    )


def looks_like_document_link(url: str, extensions: Iterable[str]) -> bool:
    """Whether a link is worth fetching as a possible document (confirmed by its type once fetched)."""
    return extension(url) in set(extensions) or bool(DOWNLOAD_LINK_RE.search(urlsplit(url).path + "?" + urlsplit(url).query))


def in_scope(url: str, site: dict) -> bool:
    """Roughly mirror the crawler's scope, to tell offsite links from ones it should have captured."""
    start, target = urlsplit(site["url"]), urlsplit(url)
    host, start_host = (target.hostname or "").lower(), (start.hostname or "").lower()
    bare = start_host[4:] if start_host.startswith("www.") else start_host
    if site["scope"] == "domain":
        return host == bare or host.endswith("." + bare)
    same_host = host in (start_host, bare, "www." + bare)
    if site["scope"] == "prefix":
        prefix = start.path.rsplit("/", 1)[0] + "/"
        return same_host and target.path.startswith(prefix)
    return same_host


class TooLarge(Exception):
    pass


def _stream_to_temp(stream, tmp_dir: Path, max_bytes: int = 0) -> Tuple[Path, int, str]:
    digest = hashlib.sha256()
    size = 0
    fd, name = tempfile.mkstemp(dir=tmp_dir)
    with open(fd, "wb") as out:
        while True:
            chunk = stream.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
            if max_bytes and size > max_bytes:
                out.close()
                Path(name).unlink()
                raise TooLarge(f"larger than {max_bytes} bytes")
            out.write(chunk)
    return Path(name), size, digest.hexdigest()


def _link_copy(path: Path, tmp_dir: Path) -> Path:
    """A second name for a temp file, so it can be cleaned up independently."""
    fd, name = tempfile.mkstemp(dir=tmp_dir)
    os.close(fd)
    os.unlink(name)
    os.link(path, name)
    return Path(name)


def scan_warcs(warcs: Iterable, extensions: Iterable[str], tmp_dir: Path, site_files: bool = False) -> ScanResult:
    """Find pages' links and extract documents. With site_files, also keep every captured file."""
    extensions = set(extensions)
    result = ScanResult()
    stored: Dict[str, str] = {}  # url -> sha256, to skip repeat captures of the same document
    kept: Set[Tuple[str, str]] = set()  # (url, sha256) of site files already kept
    for warc in warcs:
        fh = open(warc, "rb") if isinstance(warc, (str, Path)) else warc
        with fh:
            for record in ArchiveIterator(fh):
                if record.rec_type != "response" or not record.http_headers:
                    continue
                url = normalise_url(record.rec_headers.get_header("WARC-Target-URI") or "")
                if not url.startswith(("http://", "https://")):
                    continue
                status = record.http_headers.get_statuscode() or ""
                if status.startswith("3") and record.http_headers.get_header("Location"):
                    result.redirects.setdefault(url, normalise_url(urljoin(url, record.http_headers.get_header("Location"))))
                if status != "200":
                    continue
                result.captured.add(url)
                ctype = record.http_headers.get_header("Content-Type") or ""
                disposition = record.http_headers.get_header("Content-Disposition") or ""
                captured_at = record.rec_headers.get_header("WARC-Date") or ""
                is_html = base_type(ctype) in HTML_TYPES
                is_doc = not is_html and is_document(url, ctype, extensions, disposition)
                if not (site_files or is_html or is_doc):
                    continue
                tmp = None
                if site_files or is_doc:
                    tmp, size, sha = _stream_to_temp(record.content_stream(), tmp_dir)
                    raw = b""
                    if is_html:
                        with tmp.open("rb") as fh_html:
                            raw = fh_html.read(MAX_HTML_BYTES)
                else:
                    stream = record.content_stream()
                    raw = stream.read(MAX_HTML_BYTES)
                    size = len(raw)
                    while True:  # count the rest of a very large page without keeping it
                        chunk = stream.read(1 << 20)
                        if not chunk:
                            break
                        size += len(chunk)
                if is_html:
                    result.pages += 1
                    text = raw.decode("utf-8", errors="replace")
                    parser = LinkParser(url)
                    try:
                        parser.feed(text)
                    except Exception:
                        pass  # Keep whatever links were found before a parse error.
                    for link in parser.links:
                        result.links.setdefault(link, url)
                    if url not in result.page_links:
                        result.page_links[url] = parser.links
                        result.page_list.append(Page(url=url, title=page_title(text), content_type=base_type(ctype),
                                                     size=size, captured_at=captured_at))
                if tmp is None:
                    continue
                keep_site = site_files and (url, sha) not in kept
                keep_doc = is_doc and stored.get(url) != sha
                if keep_site:
                    kept.add((url, sha))
                    result.site_files.append(Document(
                        url=url, content_type=base_type(ctype), size=size, sha256=sha, source="site",
                        captured_at=captured_at, tmp_path=tmp, filename=disposition_filename(disposition),
                    ))
                if keep_doc:
                    stored[url] = sha
                    result.documents.append(Document(
                        url=url, content_type=base_type(ctype), size=size, sha256=sha, source="crawl",
                        captured_at=captured_at, tmp_path=_link_copy(tmp, tmp_dir) if keep_site else tmp,
                        filename=disposition_filename(disposition),
                    ))
                if not (keep_site or keep_doc):
                    tmp.unlink()
    for doc in result.documents:
        doc.linked_from = result.links.get(doc.url, "")
    return result


Fetcher = Callable[[str], Tuple[object, str, str]]  # url -> (readable stream, content type, content disposition)


def http_fetcher(user_agent: str, timeout: int = 60) -> Fetcher:
    def fetch(url: str):
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp, resp.headers.get("Content-Type", ""), resp.headers.get("Content-Disposition", "")
    return fetch


class RobotsCache:
    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        self.parsers: Dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.parsers:
            parser = urllib.robotparser.RobotFileParser(origin + "/robots.txt")
            try:
                parser.read()
            except Exception:
                parser = None  # Unreachable robots.txt: treat as no rules.
            self.parsers[origin] = parser
        parser = self.parsers[origin]
        return parser is None or parser.can_fetch(self.user_agent, url)


def fetch_offsite(
    scan: ScanResult,
    site: dict,
    tmp_dir: Path,
    fetcher: Fetcher,
    robots: Optional[RobotsCache],
    delay: float = 1.0,
) -> List[Tuple[str, str, str]]:
    """Download document links that point outside the crawl's scope. Returns failures as (url, linked_from, reason)."""
    extensions = set(site["document_extensions"])
    targets = [
        (url, page) for url, page in scan.links.items()
        if url.startswith(("http://", "https://"))
        and url not in scan.captured
        and not in_scope(url, site)
        and looks_like_document_link(url, extensions)
    ]
    failures = []
    for i, (url, page) in enumerate(targets):
        if i >= site["max_offsite_documents"]:
            failures += [(u, p, "over max_offsite_documents") for u, p in targets[i:]]
            break
        if robots and not robots.allowed(url):
            failures.append((url, page, "blocked by robots.txt"))
            continue
        try:
            stream, ctype, disposition = fetcher(url)
            with stream:
                if not is_document(url, ctype, extensions, disposition):
                    continue  # A web page or other non-document; leave it to the web archive.
                tmp, size, sha = _stream_to_temp(stream, tmp_dir, max_bytes=ZIP_PART_LIMIT)
        except Exception as exc:
            failures.append((url, page, f"{type(exc).__name__}: {exc}"[:200]))
            continue
        scan.documents.append(Document(
            url=url, content_type=base_type(ctype), size=size, sha256=sha, source="offsite",
            captured_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), tmp_path=tmp, linked_from=page,
            filename=disposition_filename(disposition),
        ))
        if delay:
            time.sleep(delay)
    return failures


def uncaptured_in_scope(scan: ScanResult, site: dict) -> List[Tuple[str, str]]:
    """Document links inside the crawl's scope that it did not capture (robots, limits, or errors).

    Only links ending in a document extension: download-style links without one can't be told
    apart from ordinary pages without fetching them.
    """
    extensions = set(site["document_extensions"])
    return sorted(
        (url, page) for url, page in scan.links.items()
        if url not in scan.captured and in_scope(url, site) and extension(url) in extensions
    )


def zip_path(url: str, used: Set[str], filename: str = "", html: bool = False, content_type: str = "") -> str:
    parts = urlsplit(url)
    path = unquote(parts.path)
    if filename:
        # /media/4907/download + "Quarterly report.pdf" -> /media/4907/Quarterly report.pdf
        path = path.rsplit("/", 1)[0] + "/" + filename
        parts = parts._replace(query="")
    if not path or path.endswith("/"):
        path += "index.html" if html else "index"
    elif html and PurePosixPath(path).suffix.lower() not in (".html", ".htm", ".xhtml"):
        path += ".html"  # /about -> about.html, so it opens in a browser
    elif not PurePosixPath(path).suffix and content_type:
        # e.g. a stylesheet served from /v2/css?f=... gets .css, so other tools recognise it
        path += TYPE_EXTENSIONS.get(content_type) or mimetypes.guess_extension(content_type) or ""
    segments = [re.sub(r"[^\w.\-() ]+", "_", s).strip(" .") or "_" for s in path.split("/") if s]
    name = "/".join([(parts.hostname or "unknown").lower(), *segments])
    if parts.query:
        stem, dot, ext = name.rpartition(".") if "." in segments[-1] else (name, "", "")
        suffix = hashlib.sha256(parts.query.encode()).hexdigest()[:8]
        name = f"{stem}__{suffix}{dot}{ext}"
    if len(name) > 200:
        ext = PurePosixPath(name).suffix[:12]
        name = name[: 200 - len(ext)] + ext
    candidate, n = name, 2
    while candidate.lower() in used:
        stem, dot, ext = name.rpartition(".") if "." in name.rsplit("/", 1)[-1] else (name, "", "")
        candidate = f"{stem}__{n}{dot}{ext}"
        n += 1
    used.add(candidate.lower())
    return candidate


def write_outputs(documents: List[Document], out_dir: Path, part_limit: int = ZIP_PART_LIMIT,
                  name: str = "documents") -> List[Path]:
    """Write files into <name>.zip (or <name>-1.zip, ...) and <name>.csv. Returns the files written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    groups: List[List[Document]] = []
    running = part_limit + 1
    for doc in documents:
        if running + doc.size > part_limit and not (groups and not groups[-1]):
            groups.append([])
            running = 0
        groups[-1].append(doc)
        running += doc.size
    written: List[Path] = []
    used: Set[str] = set()
    for i, group in enumerate(groups, 1):
        zip_name = f"{name}.zip" if len(groups) == 1 else f"{name}-{i}.zip"
        with zipfile.ZipFile(out_dir / zip_name, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for doc in group:
                doc.zip_file = zip_name
                doc.path = zip_path(doc.url, used, doc.filename, html=doc.content_type in HTML_TYPES,
                                    content_type=doc.content_type)
                zf.write(doc.tmp_path, doc.path)
        written.append(out_dir / zip_name)
    with open(out_dir / f"{name}.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, CSV_FIELDS)
        writer.writeheader()
        for doc in documents:
            writer.writerow({
                "zip_file": doc.zip_file, "path": doc.path, "url": doc.url, "linked_from": doc.linked_from,
                "content_type": doc.content_type, "size_bytes": doc.size, "sha256": doc.sha256,
                "source": doc.source, "captured_at": doc.captured_at,
            })
    written.append(out_dir / f"{name}.csv")
    return written


def cleanup(documents: List[Document]) -> None:
    for doc in documents:
        doc.tmp_path.unlink(missing_ok=True)
