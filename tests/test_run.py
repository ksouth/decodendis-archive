import io
import tempfile
import unittest
from pathlib import Path

from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter

from archiver.config import normalise_site
from archiver.run import scan_collection


def write_warc(path: Path, records):
    with open(path, "wb") as fh:
        writer = WARCWriter(fh, gzip=True)
        for url, status, headers, body in records:
            http = StatusAndHeaders(status, headers, protocol="HTTP/1.1")
            writer.write_record(writer.create_warc_record(url, "response", payload=io.BytesIO(body), http_headers=http))


class ScanCollectionTest(unittest.TestCase):
    """The crawler splits a capture across several WARC files; scan_collection must combine everything."""

    def test_combines_every_warc(self):
        root = Path(tempfile.mkdtemp())
        (root / "archive").mkdir()
        (root / "tmp").mkdir()
        html = [("Content-Type", "text/html")]
        write_warc(root / "archive" / "a.warc.gz", [
            ("https://x.org/old", "301 Moved", [("Location", "https://x.org/")], b""),
            ("https://x.org/", "200 OK", html, b'<title>Home</title><a href="/b">b</a><a href="/f.pdf">f</a>'),
        ])
        write_warc(root / "archive" / "b.warc.gz", [
            ("https://x.org/b", "200 OK", html, b"<title>B</title>"),
            ("https://x.org/", "200 OK", html, b"<title>Home again</title>"),  # repeat capture: keep the first
            ("https://x.org/f.pdf", "200 OK", [("Content-Type", "application/pdf")], b"%PDF"),
        ])
        site = normalise_site({"url": "https://x.org/old", "site_files": True}, {})
        scan = scan_collection(root, root / "none.wacz", site, root / "tmp")
        self.assertEqual([(p.url, p.title) for p in scan.page_list], [("https://x.org/", "Home"), ("https://x.org/b", "B")])
        self.assertEqual(scan.page_links["https://x.org/"], ["https://x.org/b", "https://x.org/f.pdf"])
        self.assertEqual(scan.redirects, {"https://x.org/old": "https://x.org/"})
        self.assertEqual([d.url for d in scan.documents], ["https://x.org/f.pdf"])
        self.assertEqual(scan.documents[0].linked_from, "https://x.org/")
        self.assertEqual(len(scan.site_files), 4)


if __name__ == "__main__":
    unittest.main()
