"""Serve the local Starwatch app with MIME types and single HTTP byte ranges for video seeking."""

from __future__ import annotations

import argparse
import os
import re
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, AnyStr, BinaryIO

if TYPE_CHECKING:
    from _typeshed import SupportsRead, SupportsWrite


class MediaHandler(SimpleHTTPRequestHandler):
    """Keep normal static-file behavior while bounding media transfers to the requested bytes."""

    extensions_map = {  # noqa: RUF012 -- override the stdlib handler's MIME map.
        **SimpleHTTPRequestHandler.extensions_map,
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".css": "text/css",
        ".svg": "image/svg+xml",
    }

    def send_head(self) -> BinaryIO | None:
        """Honor valid closed, open-ended and suffix ranges; retain standard redirects and caching."""
        self.byte_range = None
        path = Path(self.translate_path(self.path))
        requested = self.headers.get("Range")
        if not requested or not path.is_file():
            return super().send_head()
        try:
            stream = path.open("rb")
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return None
        stat = os.fstat(stream.fileno())
        modified = self.date_time_string(stat.st_mtime)
        # A mismatched validator asks for a full representation, not a partial response.
        if self.headers.get("If-Range") not in (None, modified):
            stream.close()
            return super().send_head()
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested.strip())
        if not match or not any(match.groups()):
            # Unsupported/malformed (including multipart) ranges may be ignored per HTTP.
            stream.close()
            return super().send_head()
        first, last = match.groups()
        size = stat.st_size
        if first:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        else:
            start = max(0, size - int(last))
            end = size - 1
        if start >= size or end < start:
            stream.close()
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        self.byte_range = (start, end)
        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Last-Modified", modified)
        self.end_headers()
        stream.seek(start)
        return stream

    def end_headers(self) -> None:
        """Advertise seeking support on both full and partial responses."""
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def copyfile(self, source: SupportsRead[AnyStr], outputfile: SupportsWrite[AnyStr]) -> None:
        """Stop at the range boundary, including when a browser closes an obsolete media request."""
        try:
            if self.byte_range is None:
                super().copyfile(source, outputfile)
                return
            remaining = self.byte_range[1] - self.byte_range[0] + 1
            while remaining and (chunk := source.read(min(1024 * 1024, remaining))):
                outputfile.write(chunk)
                remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main() -> None:
    """Bind only to loopback and serve the app's web directory by default."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "web")
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), partial(MediaHandler, directory=str(args.directory))) as server:
        print(f"Starwatch serving http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
