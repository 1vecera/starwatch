"""The step interface every pipeline stage implements.

A step is a class with an `id`, a `label` and an async `run(ctx)`. It reads and writes the shared
`RunContext`, reports item arrivals through `ctx.item_arrived`, and returns a `StepResult`.

How the runner reports a step:
  returns StepResult          -> its status (default "done"), count and note
  raises NotImplementedError  -> "not_implemented"  (the default until a builder fills it in)
  raises MissingCredential    -> "skipped", naming the missing credential
  raises anything else        -> "failed", with the error message
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import httpx

from ..config import Settings
from ..events import ItemArrival, RunChannel
from ..models import (
    Account,
    Brief,
    CollectedItem,
    Costs,
    Coverage,
    Goal,
    Media,
    Platform,
    Rejected,
    RunMode,
    StepStatus,
    Transcript,
)
from ..store import RunStore

MAX_MEDIA_BYTES = 8 * 1024 * 1024


@dataclass
class StepResult:
    status: StepStatus = "done"
    count: int | None = None
    note: str = ""


@dataclass
class RunContext:
    """Everything a step may read or write during one run."""

    run_id: str
    subject: str
    anchor: str
    goal: Goal
    mode: RunMode
    started_at: str
    settings: Settings
    store: RunStore
    channel: RunChannel
    accounts: list[Account] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    items: list[CollectedItem] = field(default_factory=list)
    transcripts: list[Transcript] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Coverage] = field(default_factory=dict)
    costs: Costs = field(default_factory=Costs)
    brief: Brief | None = None

    @property
    def run_dir(self) -> Path:
        return self.store.run_dir(self.run_id)

    def credential(self, name: str) -> str:
        """The value of a credential, or MissingCredential (the step is then reported skipped)."""
        return self.settings.credential(name)

    def accounts_for(self, platform: Platform, *, accepted_only: bool = True) -> list[Account]:
        return [
            a for a in self.accounts
            if a.platform == platform and (a.status == "accepted" or not accepted_only)
        ]

    def save_json(self, name: str, obj: Any) -> Path:
        return self.store.write_json(self.run_id, name, obj)

    async def data(self, step_id: str, **data: Any) -> None:
        """Send structured step output to the screens (accounts found, claims kept/dropped, ...)."""
        await self.channel.emit("step.data", step=step_id, data=data)

    async def progress(self, step_id: str, count: int, note: str = "") -> None:
        """Update a running step's count without an item (pages crawled, minutes transcribed)."""
        await self.channel.emit("step.status", step=step_id, status="running", count=count, note=note)

    async def item_arrived(self, step_id: str, item: CollectedItem) -> None:
        """Store one collected item and send it to its lane. Download its media first."""
        self.items.append(item)
        thumb = next((m for m in item.media if m.kind == "image"), None) or (
            item.media[0] if item.media else None
        )
        await self.channel.emit(
            "step.item",
            step=step_id,
            count=sum(1 for i in self.items if i.platform == item.platform),
            item=ItemArrival(
                id=item.id,
                platform=item.platform,
                kind=item.kind,
                url=item.url,
                published_at=item.published_at,
                thumb=f"/runs/{self.run_id}/{thumb.path}" if thumb else None,
                media_kind=thumb.kind if thumb else None,
                width=thumb.width if thumb else None,
                height=thumb.height if thumb else None,
                text=item.text[:140],
            ),
        )

    async def download_media(
        self, url: str, name: str, *, kind: str = "image", client: httpx.AsyncClient | None = None
    ) -> Media | None:
        """Save an image, cover or video into runs/<id>/media/ now, because CDN links expire.

        `name` is a file stem such as "instagram-3412"; the extension comes from the content type.
        Returns None when the download fails, so one dead link never fails a collector.
        """
        owns_client = client is None
        client = client or httpx.AsyncClient(timeout=20, follow_redirects=True)
        try:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0 Starwatch"})
            response.raise_for_status()
            if len(response.content) > MAX_MEDIA_BYTES:
                return None
            content_type = response.headers.get("content-type", "").split(";")[0].strip()
            extension = mimetypes.guess_extension(content_type) or (".mp4" if kind == "video" else ".jpg")
            relative = f"media/{_safe_stem(name)}{extension}"
            (self.run_dir / relative).write_bytes(response.content)
            return Media(kind=kind, path=relative, source_url=url)  # type: ignore[arg-type]
        except httpx.HTTPError:
            return None
        finally:
            if owns_client:
                await client.aclose()


def _safe_stem(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name)[:120]


class Step:
    """Base class. Subclasses set `id` and `label` and override `run`."""

    id: ClassVar[str]
    label: ClassVar[str]
    group: ClassVar[str] = "downstream"  # identity | collect | downstream; places it on S1
    actor: ClassVar[str | None] = None  # Apify Actor ID shown on the lane
    platform: ClassVar[Platform | None] = None

    async def run(self, ctx: RunContext) -> StepResult:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "group": self.group,
            "actor": self.actor,
            "platform": self.platform,
        }

