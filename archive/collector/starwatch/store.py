"""Run storage: one SQLite index plus one folder per run.

data/
  starwatch.sqlite3          index of runs (what S1 lists, what S4 compares against)
  runs/<run_id>/
    manifest.json            input, goal, mode, status, step states, coverage, costs
    events.jsonl             the SSE event log, replayable
    items.json               CollectedItem list (collectors)
    transcripts.json         Transcript list (transcribe)
    brief.json               Brief (plan and write)
    media/                   images, covers and thumbnails downloaded at collection time
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from .events import dumps, now_iso

PRAGUE = ZoneInfo("Europe/Prague")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    subject TEXT NOT NULL,
    anchor TEXT NOT NULL,
    goal_preset TEXT NOT NULL,
    goal_text TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL CHECK (mode IN ('live', 'cached')),
    status TEXT NOT NULL
);
"""


def new_run_id() -> str:
    """Sortable and readable: 20261009-034112-a1b2 (Prague time)."""
    return datetime.now(PRAGUE).strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)


class RunStore:
    def __init__(self, data_dir: Path, *, recover_running: bool = False):
        self.runs_dir = data_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(data_dir / "starwatch.sqlite3", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(_SCHEMA)
            # A run still marked running belonged to a server that stopped mid-run.
            if recover_running:
                self._db.execute("UPDATE runs SET status = 'interrupted' WHERE status = 'running'")
            self._db.commit()

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def create(self, *, subject: str, anchor: str, goal_preset: str, goal_text: str, mode: str) -> str:
        run_id = new_run_id()
        (self.run_dir(run_id) / "media").mkdir(parents=True)
        with self._lock:
            self._db.execute(
                "INSERT INTO runs (id, created_at, subject, anchor, goal_preset, goal_text, mode, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'running')",
                (run_id, now_iso(), subject, anchor, goal_preset, goal_text, mode),
            )
            self._db.commit()
        return run_id

    def finish(self, run_id: str, status: str) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE runs SET status = ?, finished_at = ? WHERE id = ?",
                (status, now_iso(), run_id),
            )
            self._db.commit()

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # --- run folder files ---

    def write_json(self, run_id: str, name: str, obj: Any) -> Path:
        if isinstance(obj, BaseModel):
            obj = obj.model_dump(mode="json")
        elif isinstance(obj, list):
            obj = [o.model_dump(mode="json") if isinstance(o, BaseModel) else o for o in obj]
        path = self.run_dir(run_id) / name
        tmp = path.with_suffix(".tmp")
        tmp.write_text(dumps(obj), encoding="utf-8")
        tmp.replace(path)
        return path

    def read_json(self, run_id: str, name: str) -> Any | None:
        path = self.run_dir(run_id) / name
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
