"""Verify actual HTTP bytes and status codes used by browser media playback and seeking."""

from __future__ import annotations

import http.client
import tempfile
import threading
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

from serve import MediaHandler


class RangeServerTest(unittest.TestCase):
    """Exercise full files, browser byte ranges and validators against a real loopback server."""

    def setUp(self) -> None:
        scratch = Path(__file__).resolve().parents[4] / "tmp/sol-media"
        scratch.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=scratch)
        self.body = bytes(range(256)) * 8
        root = Path(self.directory.name)
        (root / "clip.mp4").write_bytes(self.body)
        (root / "empty.mp4").touch()
        (root / "index.html").write_text("<title>Starwatch</title>")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(MediaHandler, directory=str(root)))
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)

    def tearDown(self) -> None:
        self.connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()
        self.directory.cleanup()

    def request(self, path: str = "/clip.mp4", headers: dict[str, str] | None = None, method: str = "GET"):
        """Read the complete response so byte count, headers and status can be checked together."""
        self.connection.request(method, path, headers=headers or {})
        response = self.connection.getresponse()
        return response.status, {name.lower(): value for name, value in response.getheaders()}, response.read()

    def test_full_get_and_head_have_mime_length_and_accept_ranges(self) -> None:
        for method in ("GET", "HEAD"):
            with self.subTest(method=method):
                status, headers, body = self.request(method=method)
                self.assertEqual(status, 200)
                self.assertEqual(headers["content-type"], "video/mp4")
                self.assertEqual(headers["content-length"], str(len(self.body)))
                self.assertEqual(headers["accept-ranges"], "bytes")
                self.assertEqual(body, self.body if method == "GET" else b"")

    def test_closed_open_suffix_and_clamped_ranges_return_exact_bytes(self) -> None:
        for value, start, end in (
            ("bytes=13-105", 13, 105),
            ("bytes=2000-", 2000, 2047),
            ("bytes=-37", 2011, 2047),
            ("bytes=2040-9999", 2040, 2047),
            ("bytes=-9999", 0, 2047),
        ):
            with self.subTest(value=value):
                status, headers, body = self.request(headers={"Range": value})
                self.assertEqual(status, 206)
                self.assertEqual(headers["content-range"], f"bytes {start}-{end}/2048")
                self.assertEqual(headers["content-length"], str(end - start + 1))
                self.assertEqual(body, self.body[start : end + 1])
        status, headers, body = self.request(headers={"Range": "bytes=13-105"}, method="HEAD")
        self.assertEqual((status, headers["content-length"], body), (206, "93", b""))

    def test_unsatisfiable_ranges_and_empty_file_return_416_without_body(self) -> None:
        for value, path, size in (
            ("bytes=2048-", "/clip.mp4", 2048),
            ("bytes=100-20", "/clip.mp4", 2048),
            ("bytes=-0", "/clip.mp4", 2048),
            ("bytes=0-", "/empty.mp4", 0),
        ):
            with self.subTest(value=value, path=path):
                status, headers, body = self.request(path, {"Range": value})
                self.assertEqual(status, 416)
                self.assertEqual(headers["content-range"], f"bytes */{size}")
                self.assertEqual((headers["content-length"], body), ("0", b""))

    def test_malformed_multipart_and_stale_validator_fall_back_to_full_file(self) -> None:
        for headers in (
            {"Range": "bytes=0-1,5-6"},
            {"Range": "bytes=-"},
            {"Range": "garbage"},
            {"Range": "bytes=0-1", "If-Range": "Wed, 01 Jan 2020 00:00:00 GMT"},
        ):
            with self.subTest(headers=headers):
                status, _, body = self.request(headers=headers)
                self.assertEqual((status, body), (200, self.body))
        _, headers, _ = self.request(method="HEAD")
        status, _, body = self.request(headers={"Range": "bytes=0-1", "If-Range": headers["last-modified"]})
        self.assertEqual((status, body), (206, self.body[:2]))

    def test_normal_page_and_missing_file_still_work(self) -> None:
        status, headers, body = self.request("/")
        self.assertEqual((status, body), (200, b"<title>Starwatch</title>"))
        self.assertEqual(headers["content-type"], "text/html")
        self.assertEqual(self.request("/missing.mp4", {"Range": "bytes=0-1"})[0], 404)


if __name__ == "__main__":
    unittest.main()
