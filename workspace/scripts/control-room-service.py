"""Keep a localhost control-room server independent of agent panes."""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def identity(pid: int) -> dict:
    """Use process start time as well as argv/cwd to reject recycled PIDs."""
    process = Path("/proc") / str(pid)
    fields = (process / "stat").read_text().rsplit(")", 1)[1].split()
    return {
        "pid": pid,
        "start_time": fields[19],
        "argv": (process / "cmdline").read_bytes().decode().split("\0")[:-1],
        "cwd": os.readlink(process / "cwd"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "status", "stop"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8110)
    args = parser.parse_args()
    root = args.root.resolve()
    checkout = Path(__file__).resolve().parents[1]
    scratch = root / "tmp/control-room"
    scratch.mkdir(parents=True, exist_ok=True)
    record = scratch / f"service-{args.port}.json"
    if args.action in ("status", "stop"):
        try:
            saved = json.loads(record.read_text())
        except FileNotFoundError:
            print(json.dumps({"status": "not-started", "port": args.port}))
            return
        try:
            current = identity(saved["pid"])
        except FileNotFoundError:
            print(json.dumps({"status": "stopped", "pid": saved["pid"]}))
            return
        if current != saved["identity"]:
            raise SystemExit("Recorded process identity changed; refusing to control it.")
        if args.action == "stop":
            try:
                os.kill(saved["pid"], signal.SIGTERM)
            except ProcessLookupError:
                print(json.dumps({"status": "stopped", "pid": saved["pid"]}))
                return
            print(json.dumps({"status": "stopping", "pid": saved["pid"]}))
        else:
            print(json.dumps({"status": "running", "url": saved["url"], "identity": current}))
        return
    if not (root / "TODO.md").is_file():
        raise SystemExit("--root must contain TODO.md")
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", args.port))
    python = checkout / ".venv/bin/python"
    if not python.is_file():
        raise SystemExit("Run uv sync in this checkout before starting the service.")
    argv = [str(python), "-m", "project_tracker", "--root", str(root), "--port", str(args.port)]
    log = scratch / f"service-{args.port}.log"
    with log.open("ab") as output:
        child = subprocess.Popen(
            argv, cwd=checkout, stdin=subprocess.DEVNULL, stdout=output, stderr=output, start_new_session=True
        )
    url = f"http://127.0.0.1:{args.port}/"
    try:
        for _ in range(100):
            if child.poll() is not None:
                raise RuntimeError(f"Server exited; inspect {log}")
            try:
                with urllib.request.urlopen(url + "api/control", timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError(f"Server did not become healthy; inspect {log}")
        details = {
            "pid": child.pid,
            "identity": identity(child.pid),
            "url": url,
            "checkout": str(checkout),
            "log": str(log),
        }
        temporary = record.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(details, indent=2) + "\n")
        temporary.replace(record)
        print(json.dumps({"status": "running", **details}))
    except BaseException:
        child.terminate()
        child.wait(timeout=5)
        raise


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
