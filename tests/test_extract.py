import csv
import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter

from archiver import extract
from archiver.config import normalise_site

PDF = b"%PDF-1.4 test document"
PAGE = b"""<html><body>
<a href="/files/report.pdf">Report</a>
<a href="/files/report.pdf#page=2">Same report</a>
<a href="https://other.example.net/paper.docx">Offsite paper</a>
<a href="https://other.example.net/media/12/download?attachment">Offsite download</a>
<a href="https://other.example.net/news/">Offsite page</a>
<a href="/files/missing.xlsx">Not captured</a>
<a href="/about/">About</a>
<a href="mailto:someone@example.org">Email</a>
</body></html>"""


def write_warc(path: Path, records):
    with open(path, "wb") as fh:
        writer = WARCWriter(fh, gzip=True)
        for url, status, ctype, body, *extra in records:
            headers = StatusAndHeaders(status, [("Content-Type", ctype), *extra], protocol="HTTP/1.1")
            writer.write_record(writer.create_warc_record(url, "response", payload=io.BytesIO(body), http_headers=headers))


class ExtractTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.tmp = self.dir / "tmp"
        self.tmp.mkdir()
        self.site = normalise_site({"url": "https://www.example.org/"}, {})
        self.warc = self.dir / "crawl.warc.gz"
        write_warc(self.warc, [
            ("https://www.example.org/", "200 OK", "text/html; charset=utf-8", PAGE),
            ("https://www.example.org/files/report.pdf", "200 OK", "application/pdf", PDF),
            ("https://www.example.org/files/report.pdf", "200 OK", "application/pdf", PDF),  # repeat capture
            ("https://www.example.org/download?id=7", "200 OK", "application/pdf", PDF + b"2"),
            ("https://www.example.org/gone.pdf", "404 Not Found", "application/pdf", b""),
            ("https://www.example.org/style.css", "200 OK", "text/css", b"body{}"),
            ("https://www.example.org/media/9/download?attachment", "200 OK", "application/octet-stream", b"x",
             ("Content-Disposition", "attachment; filename=\"Quarterly report Q3.xlsx\"")),
        ])

    def scan(self):
        return extract.scan_warcs([self.warc], self.site["document_extensions"], self.tmp)

    def test_finds_documents_by_extension_and_type(self):
        scan = self.scan()
        urls = sorted(d.url for d in scan.documents)
        self.assertEqual(urls, [
            "https://www.example.org/download?id=7",
            "https://www.example.org/files/report.pdf",
            "https://www.example.org/media/9/download?attachment",
        ])
        pdf = next(d for d in scan.documents if d.url.endswith("report.pdf"))
        self.assertEqual(pdf.sha256, hashlib.sha256(PDF).hexdigest())
        self.assertEqual(pdf.linked_from, "https://www.example.org/")
        self.assertEqual(scan.pages, 1)

    def test_offsite_fetch_and_uncaptured(self):
        scan = self.scan()
        fetched = []

        def fake_fetch(url):
            fetched.append(url)
            if url.endswith("download?attachment"):
                return io.BytesIO(b"pdf"), "application/pdf", 'attachment; filename="Plan.pdf"'
            return io.BytesIO(b"docx bytes"), "application/octet-stream", ""

        failures = extract.fetch_offsite(scan, self.site, self.tmp, fake_fetch, robots=None, delay=0)
        self.assertEqual(fetched, ["https://other.example.net/paper.docx", "https://other.example.net/media/12/download?attachment"])
        self.assertEqual(failures, [])
        offsite = [d for d in scan.documents if d.source == "offsite"]
        self.assertEqual([d.filename for d in offsite], ["", "Plan.pdf"])
        self.assertEqual(offsite[0].linked_from, "https://www.example.org/")
        self.assertEqual(
            extract.uncaptured_in_scope(scan, self.site),
            [("https://www.example.org/files/missing.xlsx", "https://www.example.org/")],
        )

    def test_offsite_failures_are_reported(self):
        scan = self.scan()

        def failing(url):
            raise OSError("connection refused")

        failures = extract.fetch_offsite(scan, self.site, self.tmp, failing, robots=None, delay=0)
        self.assertEqual(len(failures), 2)
        self.assertIn("connection refused", failures[0][2])

    def test_outputs(self):
        scan = self.scan()
        written = extract.write_outputs(scan.documents, self.dir / "out")
        self.assertEqual([p.name for p in written], ["documents.zip", "documents.csv"])
        with zipfile.ZipFile(written[0]) as zf:
            names = sorted(zf.namelist())
            self.assertIn("www.example.org/files/report.pdf", names)
            self.assertEqual(zf.read("www.example.org/files/report.pdf"), PDF)
            self.assertTrue(any(n.startswith("www.example.org/download__") for n in names))
            self.assertIn("www.example.org/media/9/Quarterly report Q3.xlsx", names)
        with open(written[1]) as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["source"] for r in rows}, {"crawl"})

    def test_zip_rolls_over_at_limit(self):
        scan = self.scan()
        written = extract.write_outputs(scan.documents, self.dir / "out", part_limit=len(PDF) + 1)
        self.assertEqual([p.name for p in written], ["documents-1.zip", "documents-2.zip", "documents-3.zip", "documents.csv"])

    def test_no_documents(self):
        written = extract.write_outputs([], self.dir / "out")
        self.assertEqual([p.name for p in written], ["documents.csv"])

    def test_zip_paths_are_unique_and_safe(self):
        used = set()
        a = extract.zip_path("https://x.org/a/b.pdf", used)
        b = extract.zip_path("https://x.org/a/B.pdf", used)
        c = extract.zip_path("https://x.org/../../etc/passwd", used)
        d = extract.zip_path("https://x.org/dir/", used)
        self.assertEqual(a, "x.org/a/b.pdf")
        self.assertEqual(b, "x.org/a/B__2.pdf")
        self.assertNotIn("..", c)
        self.assertEqual(d, "x.org/dir/index")

    def test_site_files(self):
        scan = extract.scan_warcs([self.warc], self.site["document_extensions"], self.tmp, site_files=True)
        # Every 200 response once (the repeated identical PDF capture is kept once); the 404 is skipped.
        self.assertEqual(len(scan.site_files), 5)
        self.assertEqual(len(scan.documents), 3)
        docs = extract.write_outputs(scan.documents, self.dir / "out")
        extract.cleanup(scan.documents)  # removing document temp files must not affect site files
        written = extract.write_outputs(scan.site_files, self.dir / "out", name="site-files")
        self.assertEqual([p.name for p in written], ["site-files.zip", "site-files.csv"])
        with zipfile.ZipFile(written[0]) as zf:
            names = set(zf.namelist())
            self.assertIn("www.example.org/index.html", names)
            self.assertIn("www.example.org/style.css", names)
            self.assertIn("www.example.org/media/9/Quarterly report Q3.xlsx", names)
            self.assertEqual(zf.read("www.example.org/files/report.pdf"), PDF)
            self.assertEqual(zf.read("www.example.org/index.html"), PAGE)
        with zipfile.ZipFile(docs[0]) as zf:
            self.assertEqual(zf.read("www.example.org/files/report.pdf"), PDF)

    def test_site_files_off_by_default(self):
        self.assertEqual(self.scan().site_files, [])

    def test_html_paths(self):
        used = set()
        self.assertEqual(extract.zip_path("https://x.org/", used, html=True), "x.org/index.html")
        self.assertEqual(extract.zip_path("https://x.org/about", used, html=True), "x.org/about.html")
        self.assertEqual(extract.zip_path("https://x.org/a.html", used, html=True), "x.org/a.html")
        css = extract.zip_path("https://api.x.org/v2/css?f=a", used, content_type="text/css")
        self.assertTrue(css.startswith("api.x.org/v2/css__") and css.endswith(".css"), css)
        self.assertEqual(extract.zip_path("https://x.org/logo", used, content_type="image/png"), "x.org/logo.png")

    def test_disposition_filename(self):
        f = extract.disposition_filename
        self.assertEqual(f('attachment; filename="a b.pdf"'), "a b.pdf")
        self.assertEqual(f("attachment; filename=plain.docx"), "plain.docx")
        self.assertEqual(f("attachment; filename*=UTF-8''Caf%C3%A9%20plan.pdf"), "Café plan.pdf")
        self.assertEqual(f('attachment; filename="../../etc/passwd"'), "passwd")
        self.assertEqual(f(""), "")

    def test_download_links(self):
        exts = self.site["document_extensions"]
        self.assertTrue(extract.looks_like_document_link("https://x.org/media/1/download?attachment", exts))
        self.assertTrue(extract.looks_like_document_link("https://x.org/a/report.PDF", exts))
        self.assertFalse(extract.looks_like_document_link("https://x.org/news/story", exts))
        self.assertFalse(extract.looks_like_document_link("https://www.health.gov.au/ministers/x/media/speech-22-april", exts))
        self.assertTrue(extract.looks_like_document_link("https://x.gov.au/sites/default/files/plan", exts))

    def test_scope(self):
        site = normalise_site({"url": "https://www.example.org/pubs/list", "scope": "prefix"}, {})
        self.assertTrue(extract.in_scope("https://example.org/pubs/a.pdf", site))
        self.assertFalse(extract.in_scope("https://www.example.org/other/a.pdf", site))
        dom = normalise_site({"url": "https://www.example.org/", "scope": "domain"}, {})
        self.assertTrue(extract.in_scope("https://files.example.org/a.pdf", dom))
        self.assertFalse(extract.in_scope("https://example.net/a.pdf", dom))


if __name__ == "__main__":
    unittest.main()
