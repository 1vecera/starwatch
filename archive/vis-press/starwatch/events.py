"""Server-sent progress events.

Every run has one ordered event log. It lives in memory while the run is active and is appended to
`runs/<run_id>/events.jsonl`, so a screen that connects late, reconnects, or opens a finished run
replays the same sequence. Screens build themselves from these events alone.

Event types:
  run.started   data = {"plan": [step descriptors], "input": {...}, "mode", "goal", "step_pause_s"}
  step.status   step, status, count, note           (queued/running/done/failed/skipped/not_implemented)
  step.item     step, item = ItemArrival            (one collected item reaching its lane)
  step.data     step, data = {...}                  (structured output: accounts, rejected, claim counts)
  run.finished  status, data = {"coverage": [...], "costs": {...}}
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

EventType = Literal["run.started", "step.status", "step.item", "step.data", "run.finished"]


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ItemArrival(BaseModel):
    """What a lane needs to show one arriving item. `thumb` is a local URL, never a CDN link."""

    id: str
    platform: str
    kind: str
    url: str
    published_at: str = ""
    thumb: str | None = None  # e.g. /runs/<run_id>/media/instagram-123.jpg
    media_kind: Literal["image", "video"] | None = None
    width: int | None = None
    height: int | None = None
    text: str = ""  # first 140 characters, escaped by the screen


class Event(BaseModel):
    seq: int
    ts: str
    type: EventType
    run_id: str
    step: str | None = None
    status: str | None = None
    count: int | None = None
    note: str = ""
    item: ItemArrival | None = None
    data: dict[str, Any] | None = None

    def sse(self) -> str:
        return f"id: {self.seq}\ndata: {self.model_dump_json(exclude_none=True)}\n\n"


class RunChannel:
    """Ordered, replayable event log for one run."""

    def __init__(self, run_id: str, log_path: Path):
        self.run_id = run_id
        self.log_path = log_path
        self.events: list[Event] = []
        self.closed = False
        self._changed = asyncio.Condition()

    @classmethod
    def from_log(cls, run_id: str, log_path: Path) -> RunChannel:
        """A finished or interrupted run, replayed from disk."""
        channel = cls(run_id, log_path)
        if log_path.exists():
            for line in log_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    channel.events.append(Event.model_validate_json(line))
        channel.closed = True
        return channel

    async def emit(self, type: EventType, **fields: Any) -> Event:
        event = Event(seq=len(self.events) + 1, ts=now_iso(), type=type, run_id=self.run_id, **fields)
        self.events.append(event)
        with self.log_path.open("a", encoding="utf-8") as log:
            log.write(event.model_dump_json(exclude_none=True) + "\n")
        if type == "run.finished":
            self.closed = True
        async with self._changed:
            self._changed.notify_all()
        return event

    async def subscribe(self, after: int = 0, keepalive_s: float = 15.0) -> AsyncIterator[str]:
        """Yield SSE frames for events with seq > after, until the run has finished."""
        sent = after
        while True:
            while sent < len(self.events):
                sent += 1
                yield self.events[sent - 1].sse()
            if self.closed:
                return
            async with self._changed:
                try:
                    await asyncio.wait_for(
                        self._changed.wait_for(lambda: len(self.events) > sent or self.closed),
                        timeout=keepalive_s,
                    )
                except TimeoutError:
                    yield ": keepalive\n\n"


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)
