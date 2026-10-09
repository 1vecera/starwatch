"""Run with uv run python -m project_tracker --root /path/to/project."""

import argparse
import json
import mimetypes
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from project_tracker.model import Project
from project_tracker.records import ConflictError, ControlStore, ValidationError

WEB = Path(__file__).parent / "web"
ASSETS = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, root: Path, port: int):
        super().__init__(("127.0.0.1", port), Handler)
        self.project = Project(root)
        self.store = ControlStore(root, project=self.project)
        self.stop_outbox = threading.Event()
        self.note_lock = threading.Lock()
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.hosts = {f"127.0.0.1:{self.server_port}", f"localhost:{self.server_port}"}

    def start_outbox(self):
        def dispatch():
            first = True
            while not self.stop_outbox.is_set():
                try:
                    self.store.dispatch_pending(recover_interrupted=first)
                    first = False
                except (ValueError, OSError):
                    pass
                self.stop_outbox.wait(1)

        threading.Thread(target=dispatch, daemon=True, name="chief-outbox").start()

    def server_close(self):
        self.stop_outbox.set()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    server: DashboardServer

    def log_message(self, format: str, *args) -> None:
        # Do not log user notes or malicious URL content.
        pass

    def permitted(self, writing: bool = False) -> bool:
        origin = self.headers.get("Origin")
        allowed_origins = {self.server.origin, f"http://localhost:{self.server.server_port}"}
        allowed = (
            self.client_address[0] == "127.0.0.1"
            and self.headers.get("Host") in self.server.hosts
            and (origin in allowed_origins if writing else origin is None or origin in allowed_origins)
            and self.headers.get("Sec-Fetch-Site", "same-origin") not in ("cross-site", "same-site")
        )
        if not allowed:
            self.respond(403, {"error": "Local same-origin access required"})
        return allowed

    def respond(self, status: int, body, mime: str = "application/json") -> None:
        content = json.dumps(body, ensure_ascii=False).encode() if mime == "application/json" else body
        self.send_response(status)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
            ),
        )
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        if not self.permitted():
            return
        request = urlsplit(self.path)
        query = parse_qs(request.query)
        try:
            if request.path in ASSETS:
                file = WEB / ASSETS[request.path]
                self.respond(200, file.read_bytes(), mimetypes.guess_type(file.name)[0] or "text/plain")
            elif request.path.startswith("/assets/"):
                relative = request.path.removeprefix("/")
                if not re.fullmatch(r"assets/[A-Za-z0-9_.-]+\.(?:js|css|woff2?|svg|png)", relative):
                    raise ValueError("Invalid asset")
                file = WEB / relative
                if (
                    file.is_symlink()
                    or file.parent.is_symlink()
                    or not file.resolve().is_relative_to(WEB.resolve())
                    or file.stat().st_size > 8_000_000
                ):
                    raise ValueError("Invalid asset")
                self.respond(200, file.read_bytes(), mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            elif request.path == "/api/control":
                self.respond(200, self.server.store.snapshot())
            elif request.path == "/api/events":
                self.events()
            elif request.path == "/api/state":
                self.respond(200, self.server.project.snapshot())
            elif request.path == "/api/source":
                self.respond(200, self.server.project.source(query["id"][0]))
            elif request.path == "/api/screenshot":
                relative = self.server.project.screenshots()[query["id"][0]]
                file = self.server.project.bounded(relative, 12_000_000)
                self.respond(200, file.read_bytes(), "image/png")
            else:
                self.respond(404, {"error": "Not found"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, KeyError, OSError):
            self.respond(404, {"error": "Evidence unavailable or outside the allowlist"})

    def events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        previous = None
        heartbeat_at = time.monotonic()
        while not self.server.stop_outbox.is_set():
            state = self.server.store.snapshot()
            signature = state["revision"] + state["chief"]["connection"] + state["chief"]["status"]
            if signature != previous:
                self.wfile.write(("event: state\ndata: " + json.dumps(state, ensure_ascii=False) + "\n\n").encode())
                previous = signature
            elif time.monotonic() - heartbeat_at >= 5:
                self.wfile.write(b"event: heartbeat\ndata: {}\n\n")
                heartbeat_at = time.monotonic()
            self.wfile.flush()
            self.server.stop_outbox.wait(1)

    def do_POST(self) -> None:
        if not self.permitted(writing=True):
            return
        if self.path == "/api/control":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if (
                    not 1 <= length <= 64_000
                    or self.headers.get("Content-Type", "").split(";")[0] != "application/json"
                ):
                    raise ValidationError("Use a JSON mutation up to 64000 bytes")
                self.respond(200, self.server.store.mutate(json.loads(self.rfile.read(length)), require_revision=True))
            except ConflictError as error:
                self.respond(409, {"error": str(error), "code": "conflict", "state": self.server.store.snapshot()})
            except (ValueError, KeyError, TypeError, OSError) as error:
                self.respond(400, {"error": str(error), "code": getattr(error, "code", "validation")})
            return
        if self.path != "/api/notes":
            self.respond(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 12_000 or self.headers.get("Content-Type") != "application/json":
                self.respond(400, {"error": "Use JSON with a note of up to 2000 characters"})
                return
            payload = json.loads(self.rfile.read(length))
            note = payload["text"]
            if not isinstance(note, str) or not 1 <= len(note.strip()) <= 2000 or "\x00" in note:
                raise ValueError("Invalid note")
            entry = {"id": str(uuid.uuid4()), "at": datetime.now(timezone.utc).isoformat(), "text": note.strip()}
            with self.server.note_lock:
                directory = self.server.project.root / "tmp/project-tracker"
                if any(parent.is_symlink() for parent in (directory, directory.parent)):
                    raise ValueError("Inbox directory unavailable")
                directory.mkdir(parents=True, exist_ok=True)
                if directory.resolve() != self.server.project.root / "tmp/project-tracker":
                    raise ValueError("Inbox directory unavailable")
                path = directory / "inbox.jsonl"
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
                with os.fdopen(descriptor, "a") as output:
                    output.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    output.flush()
                    os.fsync(output.fileno())
            self.respond(201, {"id": entry["id"], "status": "Pending acknowledgement"})
        except (ValueError, KeyError, TypeError, OSError):
            self.respond(400, {"error": "Note not saved; check text or local inbox permissions"})


def main() -> None:
    parser = argparse.ArgumentParser(description="Private local Starwatch project tracker")
    parser.add_argument("--root", type=Path, required=True, help="Existing project root containing TODO.md")
    parser.add_argument("--port", type=int, default=8110)
    args = parser.parse_args()
    if not (args.root / "TODO.md").is_file():
        parser.error("--root must contain the project's TODO.md")
    server = DashboardServer(args.root, args.port)
    server.store.migrate()
    server.start_outbox()
    print(f"Starwatch project dashboard: {server.origin}", flush=True)
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
