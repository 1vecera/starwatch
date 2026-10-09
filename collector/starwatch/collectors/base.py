"""Base class for the per-platform collectors.

A collector waits for identity to settle its platform, runs its Actor through `run_actor` (which
applies the caps in `actors.py` and reads only the allowlisted dataset fields), projects each raw
item into a `Draft`, saves the item's image or cover into the run's media folder, and calls
`ctx.item_arrived` so the item reaches its lane on S1 as soon as its picture is on disk.

Every outcome becomes a coverage row with its reason: no account (`not_found`), an Actor that
fails without items (`unavailable`, after one retry), an Actor that returns nothing (`not_found`).
A run stopped at its timeout keeps the items it delivered.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, ClassVar

import httpx

from ..events import now_iso
from ..models import Account, CollectedItem, Coverage
from ..steps.base import RunContext, Step, StepResult
from .actors import ACTORS, MAX_VIDEO_SECONDS, ActorSpec
from .apify import ActorRunResult, ApifyRunFailed, StopRun, run_actor
from .identity import LABELS, _record_run, identity_board, name_match
from .media import BROWSER_UA, download_video, with_size
from .subtitles import capture_asr

log = logging.getLogger("starwatch.collect")

DOWNLOADS_PER_LANE = 6


@dataclass
class Draft:
    """A projected item before its media is saved."""

    item: CollectedItem
    image_url: str = ""
    video_url: str = ""
    video_seconds: float = 0.0


class Collector(Step):
    group: ClassVar[str] = "collect"
    noun: ClassVar[str] = "posts"

    @property
    def spec(self) -> ActorSpec:
        assert self.platform is not None
        return ACTORS[self.platform]

    def describe(self) -> dict:
        return {**super().describe(), "actor": self.spec.actor_id, "max_items": self.spec.max_items}

    # Each platform fills these two in. -------------------------------------------------------
    def run_input(self, account: Account) -> dict[str, Any]:
        raise NotImplementedError

    def project(self, raw: dict[str, Any], account: Account, collected_at: str) -> Draft | None:
        raise NotImplementedError

    def display_name(self, raw: dict[str, Any], account: Account) -> str:
        """The account's display name as the item shows it, for the name check. Empty: no check."""
        return ""

    def identity_basis(self, raw: dict[str, Any], ctx: RunContext) -> list[str]:
        """Match basis an item reveals about the account (a badge, a link back to the anchor)."""
        return []

    async def save_videos(self, ctx: RunContext, drafts: list[Draft], client: httpx.AsyncClient, token: str) -> int:
        """Save videos for transcription. Platforms with videos override; the default saves none."""
        return 0

    # The shared flow. ---------------------------------------------------------------------------
    async def run(self, ctx: RunContext) -> StepResult:
        token = ctx.credential("APIFY_TOKEN")
        assert self.platform is not None
        board = identity_board(ctx)
        try:
            if board is not None:
                account, reason = await board.account_for(self.platform)
            else:
                accounts = ctx.accounts_for(self.platform)
                account, reason = (accounts[0], "") if accounts else (None, "identity resolved no account")
            if account is None:
                ctx.coverage[self.platform] = Coverage(platform=self.platform, status="not_found", note=reason)
                return StepResult("skipped", count=0, note=reason)
            return await self._collect(ctx, account, token)
        finally:
            if board is not None:
                board.videos.decided(self.platform)
                board.lanes[self.platform].set()

    async def _collect(self, ctx: RunContext, account: Account, token: str) -> StepResult:
        assert self.platform is not None
        board = identity_board(ctx)
        drafts: list[Draft] = []
        landing: set[asyncio.Task] = set()
        seen: set[str] = set()
        images: set[str] = set()
        limit = asyncio.Semaphore(DOWNLOADS_PER_LANE)
        basis_seen = False
        name_checked = False
        stopped: list[str] = [""]

        async with httpx.AsyncClient(
            timeout=20, follow_redirects=True, headers={"User-Agent": BROWSER_UA}
        ) as client:

            async def land(draft: Draft) -> None:
                media = []
                if draft.item.subtitle_tracks:
                    await capture_asr(ctx, draft.item, client)
                if draft.image_url:
                    async with limit:
                        saved = await ctx.download_media(
                            draft.image_url, _stem(draft.item.id), kind="image", client=client
                        )
                    if saved:
                        media.append(with_size(saved, ctx.run_dir))
                draft.item.media = media
                await ctx.item_arrived(self.id, draft.item)

            async def on_items(raw_items: list[dict[str, Any]]) -> None:
                nonlocal basis_seen, name_checked
                if not name_checked:
                    name_checked = True
                    mismatch = self._name_mismatch(ctx, account, raw_items)
                    if mismatch:
                        stopped[0] = mismatch
                        if board is not None:
                            board.reject_linked(self.platform, mismatch)  # type: ignore[arg-type]
                            await board.publish()
                        raise StopRun(f"stopped: {mismatch}")
                collected_at = now_iso()
                for raw in raw_items:
                    await ctx.record_profile(self.id, account, raw, collected_at)
                    try:
                        draft = self.project(raw, account, collected_at)
                    except Exception:
                        log.exception("%s: could not project an item", self.id)
                        continue
                    if draft is None or draft.item.id in seen:
                        continue
                    seen.add(draft.item.id)
                    if draft.image_url in images:
                        draft.image_url = ""  # a picture shared by several items is shown once
                    elif draft.image_url:
                        images.add(draft.image_url)
                    drafts.append(draft)
                    task = asyncio.create_task(land(draft))
                    landing.add(task)
                    task.add_done_callback(landing.discard)
                    if board is not None and not basis_seen:
                        basis = self.identity_basis(raw, ctx)
                        if basis:
                            basis_seen = True
                            board.enrich(self.platform, *basis)  # type: ignore[arg-type]
                            await board.publish()

            result: ActorRunResult | None = None
            failure: ApifyRunFailed | None = None
            for attempt in range(2):
                try:
                    result = await run_actor(self.spec, self.run_input(account), token=token, on_items=on_items)
                    failure = None
                    break
                except ApifyRunFailed as error:
                    failure = error
                    ctx.costs.apify_usd += error.usage_usd
                    await _record_run(ctx, self.id, self.spec.actor_id, error.run_id, error.status or "FAILED",
                                      0, error.usage_usd)
                    if drafts or attempt == 1 or not error.run_id:
                        break  # no retry for items already shown, a second failure or a refused start
                    await ctx.progress(self.id, 0, f"Actor run failed, retrying once: {error}"[:160])

            if landing:
                await asyncio.gather(*list(landing), return_exceptions=True)

            if result is not None:
                ctx.costs.apify_usd += result.usage_usd
                await _record_run(ctx, self.id, self.spec.actor_id, result.run_id, result.status,
                                  result.item_count, result.usage_usd)
                await ctx.data(self.id, apify_run={
                    "actor": self.spec.actor_id, "run_id": result.run_id, "status": result.status,
                    "items": result.item_count, "usage_usd": round(result.usage_usd, 4),
                    "seconds": result.duration_s, "console_url": result.console_url,
                })

            count = sum(1 for i in ctx.items if i.platform == self.platform)
            videos = 0
            if count and board is not None:
                try:
                    videos = await self.save_videos(ctx, drafts, client, token)
                except Exception:
                    log.exception("%s: saving videos failed", self.id)

        handle = account.handle or account.url
        if stopped[0]:
            reason = f"not collected: {stopped[0]}"
            ctx.coverage[self.platform] = Coverage(platform=self.platform, status="not_found", note=reason)
            return StepResult("skipped", count=0, note=reason)
        if failure is not None and count == 0:
            reason = f"{self.spec.actor_id} failed for {handle}: {failure}"[:300]
            ctx.coverage[self.platform] = Coverage(platform=self.platform, status="unavailable", note=reason)
            return StepResult("failed", count=0, note=reason)
        if count == 0:
            reason = f"{self.spec.actor_id} returned no {self.noun} for {handle}"
            ctx.coverage[self.platform] = Coverage(platform=self.platform, status="not_found", note=reason)
            return StepResult("done", count=0, note=reason)

        parts = [f"{count} {self.noun} from {handle}"]
        if videos:
            parts.append(f"{videos} video{'s' if videos > 1 else ''} saved for transcription")
        if result is not None:
            if "(" in result.status:
                parts.append(result.status.split("(", 1)[1].rstrip(")"))
            parts.append(f"Apify ${result.usage_usd:.3f}")
        note = " · ".join(parts)
        ctx.coverage[self.platform] = Coverage(platform=self.platform, status="collected", items=count, note=note)
        return StepResult("done", count=count, note=note)

    def _name_mismatch(self, ctx: RunContext, account: Account, raw_items: list[dict[str, Any]]) -> str:
        """A reason when the first items show an account named for someone else (a party page,
        a government office), checked once per lane; empty when the name fits or is not shown."""
        names = [n for n in (self.display_name(r, account).strip() for r in raw_items) if n]
        if not names:
            return ""
        shown = max(set(names), key=names.count)
        if name_match(ctx.subject, shown, account.handle):
            return ""
        board = identity_board(ctx)
        where = board.anchor.label if board else "the anchor"
        return f"{where} links it, but the account is named “{shown}”, not {ctx.subject}"

    # Video helpers for the platforms that have them. -------------------------------------------
    @staticmethod
    def video_candidates(drafts: list[Draft]) -> list[Draft]:
        """Newest first, spoken-clip length, with a video URL."""
        eligible = [
            d for d in drafts
            if d.video_url and 3 <= (d.video_seconds or 0) <= MAX_VIDEO_SECONDS
        ]
        return sorted(eligible, key=lambda d: d.item.published_at, reverse=True)

    async def keep_video(self, ctx: RunContext, draft: Draft, url: str, client: httpx.AsyncClient, token: str) -> bool:
        media = await download_video(client, url, ctx.run_dir, _stem(draft.item.id) + "-video", apify_token=token)
        if media is None:
            return False
        draft.item.media.append(media)
        return True


def _stem(item_id: str) -> str:
    return item_id.replace(":", "-")


def label(platform: str) -> str:
    return LABELS.get(platform, platform)
