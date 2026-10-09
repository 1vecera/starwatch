"""Shared plumbing: content-addressed cache, spend ledger with hard caps, deterministic output."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class BudgetExceeded(RuntimeError):
    """A paid call would push a service past its hard cap."""


class OfflineMiss(RuntimeError):
    """A cache entry is missing while running with --offline."""


def utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    data = value if isinstance(value, bytes) else stable_json(value).encode()
    return hashlib.sha256(data).hexdigest()


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


def atomic_write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_bytes(data.encode() if isinstance(data, str) else data)
    temporary.replace(path)


class Cache:
    """JSON records and blobs under ``root/<namespace>/<key[:2]>/``.

    Every network response is stored before it is used, so a second run with ``offline=True``
    rebuilds identical outputs without spending anything.
    """

    def __init__(self, root: Path, offline: bool = False):
        self.root = Path(root)
        self.offline = offline

    def path(self, namespace: str, key: str, suffix: str = ".json") -> Path:
        return self.root / namespace / key[:2] / f"{key}{suffix}"

    def get(self, namespace: str, key: str) -> dict | None:
        path = self.path(namespace, key)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def put(self, namespace: str, key: str, value: dict) -> None:
        atomic_write(self.path(namespace, key), json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True))

    def miss(self, what: str) -> None:
        if self.offline:
            raise OfflineMiss(f"not cached (offline): {what}")


class Ledger:
    """Append-only JSONL spend log with per-service hard caps.

    Totals include every earlier run that used the same cache directory, so the caps bound the
    whole collection effort, not a single invocation.
    """

    def __init__(self, path: Path, caps: dict[str, float]):
        self.path = Path(path)
        self.caps = dict(caps)
        self._lock = threading.Lock()
        self._totals: dict[str, float] = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    self._totals[row["service"]] = self._totals.get(row["service"], 0.0) + float(row["usd"])

    def total(self, service: str) -> float:
        with self._lock:
            return self._totals.get(service, 0.0)

    def totals(self) -> dict[str, float]:
        with self._lock:
            return {key: round(value, 4) for key, value in sorted(self._totals.items())}

    def check(self, service: str, upcoming: float = 0.0) -> None:
        cap = self.caps.get(service)
        if cap is None:
            raise BudgetExceeded(f"no cap configured for {service}")
        spent = self.total(service)
        if spent + upcoming > cap:
            raise BudgetExceeded(f"{service}: spent ${spent:.4f} + next ~${upcoming:.4f} exceeds cap ${cap:.2f}")

    def record(self, service: str, usd: float, detail: dict) -> None:
        row = {"at": utcnow(), "service": service, "usd": round(float(usd), 6), **detail}
        with self._lock:
            self._totals[service] = self._totals.get(service, 0.0) + float(usd)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as handle:
                handle.write(stable_json(row) + "\n")


def write_js(path: Path, variable: str, payload: dict) -> None:
    """Write ``window.<variable> = {...};`` with sorted keys so equal input gives equal bytes."""
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1)
    atomic_write(Path(path), f"window.{variable} = {body};\n")


def read_js(path: Path) -> dict:
    """Parse a ``window.X = {...};`` data file (the snapshot or an earlier output)."""
    text = Path(path).read_text()
    start = text.index("=") + 1
    end = text.rstrip().rstrip(";")
    return json.loads(end[start:])
