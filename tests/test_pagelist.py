import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter

from archiver import extract, pagelist
from archiver.config import normalise_site
from archiver.dashboard import write_page_lists

EMOJI = re.compile("[\\U0001F300-\\U0001FAFF\\u2600-\\u27BF]")
HOME = b"""<html><head><title>Example   Home &amp; More</title></head><body>
<a href="/about">About</a> <a href="/news/one">News one</a> <a href="/files/plan.pdf">Plan</a></body></html>"""


def page(title):
    return f"<html><head><title>{title}</title></head><body>hi</body></html>".encode()


def write_warc(path: Path, records):
    with open(path, "wb") as fh:
        writer = WARCWriter(fh, gzip=True)
        for url, status, headers, body in records:
            http = StatusAndHeaders(status, headers, protocol="HTTP/1.1")
            writer.write_record(writer.create_warc_record(url, "response", payload=io.BytesIO(body), http_headers=http))


class PageListTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "tmp").mkdir()
        self.site = normalise_site({"url": "https://example.org/start", "site_files": True}, {})
        html = [("Content-Type", "text/html; charset=utf-8")]
        self.warc = self.dir / "c.warc.gz"
        write_warc(self.warc, [
            ("https://example.org/start", "301 Moved Permanently", [("Location", "https://www.example.org/")], b""),
            ("https://www.example.org/", "200 OK", html, HOME),
            ("https://www.example.org/about", "200 OK", html, page("About us")),
            ("https://www.example.org/news/one", "200 OK", html, page("News one")),
            ("https://www.example.org/news/two", "200 OK", html, page("News two")),
            ("https://www.example.org/contact", "200 OK", html, page("Contact")),
            ("https://blog.example.org/post", "200 OK", html, page("<script>x</script>Post")),
            ("https://www.youtube.com/embed/abc", "200 OK", html, page("Video")),
            ("https://www.example.org/files/plan.pdf", "200 OK", [("Content-Type", "application/pdf")], b"%PDF-1.4 plan"),
            ("https://www.example.org/style.css", "200 OK", [("Content-Type", "text/css")], b"body{}"),
        ])
        self.scan = extract.scan_warcs([self.warc], self.site["document_extensions"], self.dir / "tmp", site_files=True)

    def index(self, doc_assets=None, part=1):
        extract.write_outputs(self.scan.documents, self.dir / "out")
        site_paths = {}
        extract.write_outputs(self.scan.site_files, self.dir / "out", name="site-files")
        for f in self.scan.site_files:
            site_paths.setdefault(f.url, f"{f.zip_file} › {f.path}")
        return pagelist.build_index(self.site, "example-org-start", "20260925T000000Z", part,
                                    "https://github.com/me/r/releases/tag/t", "https://github.com/me/r/releases/download/t/",
                                    "capture.wacz", self.scan, doc_assets or {}, site_paths)

    def test_scan_records_pages(self):
        titles = [p.title for p in self.scan.page_list]
        self.assertEqual(titles[0], "Example Home & More")
        self.assertEqual(len(titles), 7)  # pages only, not the PDF or stylesheet
        self.assertEqual(self.scan.redirects["https://example.org/start"], "https://www.example.org/")
        self.assertEqual(self.scan.page_list[0].size, len(HOME))

    def test_home_follows_redirect(self):
        index = self.index()
        self.assertEqual(index["home"], "https://www.example.org/")
        self.assertIn("https://www.example.org/about", index["home_links"])

    def test_format_and_files(self):
        index = self.index()
        home = index["pages"][0]
        self.assertEqual(home["format"], "WACZ + Site")
        base = "https://github.com/me/r/releases/download/t/"
        self.assertEqual(home["files"], [{"text": "capture.wacz", "url": base + "capture.wacz"},
                                         {"text": "site-files.zip › www.example.org/index.html", "url": base + "site-files.zip"}])
        (doc,) = index["documents"]
        self.assertEqual((doc["format"], doc["type"], doc["name"]), ("WACZ + Site", "PDF", "plan.pdf"))
        self.assertIn({"text": "documents.zip › www.example.org/files/plan.pdf",
                       "url": "https://github.com/me/r/releases/download/t/documents.zip"}, doc["files"])
        self.assertEqual(pagelist.format_label(True, False), "WACZ")
        self.assertEqual(pagelist.format_label(False, True), "Site")
        self.assertEqual(pagelist.format_label(False, False), "documents.zip")

    def test_download_links(self):
        doc = self.scan.documents[0]
        index = self.index({id(doc): "doc-abc-plan.pdf"})
        self.assertEqual(index["documents"][0]["download_url"], "https://github.com/me/r/releases/download/t/doc-abc-plan.pdf")
        html = pagelist.render_page([index], "../../../")
        self.assertIn('<a class="download" href="https://github.com/me/r/releases/download/t/doc-abc-plan.pdf">Download PDF', html)
        # File names are links too; the document's own file comes first.
        self.assertIn('<a href="https://github.com/me/r/releases/download/t/doc-abc-plan.pdf"><code>doc-abc-plan.pdf</code></a>', html)
        self.assertIn('<a href="https://github.com/me/r/releases/download/t/capture.wacz"><code>capture.wacz</code></a>', html)

    def test_page_sections(self):
        html = pagelist.render_page([self.index()], "../../../")
        order = [html.index(s) for s in ("Home page (1)", "Linked from the home page (2)",
                                          "www.example.org/ (top level) (1)", "www.example.org/news/ (1)",
                                          "blog.example.org/ (top level) (1)",
                                          "Embedded from other websites: www.youtube.com/embed/ (1)",
                                          "Documents (1)", "From this website (1)")]
        self.assertEqual(order, sorted(order))
        self.assertIn("<strong>WACZ + Site</strong>", html)
        self.assertNotIn("<script>x</script>", html)  # page titles are escaped
        self.assertIsNone(EMOJI.search(html))

    def test_merge_parts(self):
        one, two = self.index(part=1), json.loads(json.dumps(self.index(part=2)))
        two["pages"].append({**two["pages"][1], "url": "https://www.example.org/late", "title": "Late"})
        two["release_url"] = "https://github.com/me/r/releases/tag/t2"
        merged = pagelist.merge_parts([two, one])
        self.assertEqual((merged["parts"], len(merged["pages"])), (2, 8))
        self.assertEqual(merged["home"], "https://www.example.org/")
        self.assertIn("part 2", pagelist.render_page([one, two], "../../../"))

    def test_asset_names(self):
        used = set()
        self.assertEqual(pagelist.asset_name("abcdef1234", "Monthly Summary_ July 2022.pdf", used),
                         "doc-abcdef12-Monthly-Summary_-July-2022.pdf")
        self.assertEqual(pagelist.asset_name("abcdef1234", "Monthly Summary_ July 2022.pdf", used),
                         "doc-abcdef12-2-Monthly-Summary_-July-2022.pdf")
        self.assertEqual(pagelist.asset_name("ff00", "https://x.org/media/1/download?attachment", used), "doc-ff00-download")

    def test_type_names(self):
        self.assertEqual(pagelist.type_name("application/pdf", "x"), "PDF")
        self.assertEqual(pagelist.type_name("application/octet-stream", "report.xlsx"), "Excel spreadsheet")
        self.assertEqual(pagelist.type_name("text/html", "https://x.org/"), "Web page")

    def test_write_page_lists(self):
        indexes = self.dir / "indexes"
        indexes.mkdir()
        (indexes / "a.json").write_text(json.dumps(self.index()))
        out = self.dir / "docs" / "captures"
        (out / "old" / "gone").mkdir(parents=True)
        written = write_page_lists(indexes, out, "../../../")
        self.assertEqual(written, {("example-org-start", "20260925T000000Z")})
        self.assertTrue((out / "example-org-start" / "20260925T000000Z" / "index.html").exists())
        self.assertFalse((out / "old").exists())  # pages for deleted releases are removed


class HomeTest(unittest.TestCase):
    def test_variants_and_fallback(self):
        urls = ["https://www.x.org/", "https://www.x.org/a"]
        self.assertEqual(pagelist.find_home("https://x.org", urls, {}), "https://www.x.org/")
        self.assertEqual(pagelist.find_home("https://other.org/", urls, {}), "https://www.x.org/")
        self.assertEqual(pagelist.find_home("https://x.org/old", ["https://x.org/new"], {"https://x.org/old": "https://x.org/new"}),
                         "https://x.org/new")
        self.assertEqual(pagelist.find_home("https://x.org/", [], {}), "")


if __name__ == "__main__":
    unittest.main()
