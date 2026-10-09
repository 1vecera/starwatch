"""TikTok collector: up to 20 videos with covers, at most 3 video files for transcription.

Posts stream without TikTok's video add-on, which would hold every item back until its video is
saved. Covers come straight from TikTok's CDN. After the posts are in, the newest spoken-length
videos (up to the run's video budget) are fetched by URL in one small second run and saved locally.
Comments, follower lists and subtitles stay off.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..models import Account, CollectedItem
from ..steps.base import RunContext
from .actors import TIKTOK_VIDEOS
from .apify import ApifyRunFailed, run_actor
from .base import Collector, Draft
from .identity import _record_run, identity_board
from .subtitles import capture_asr, project_tracks


class TiktokCollector(Collector):
    id = "collect.tiktok"
    label = "TikTok"
    platform = "tiktok"
    noun = "videos"

    def run_input(self, account: Account) -> dict[str, Any]:
        return {"profiles": [account.handle.lstrip("@")]}

    def display_name(self, raw: dict[str, Any], account: Account) -> str:
        return str((raw.get("authorMeta") or {}).get("nickName") or "")

    def project(self, raw: dict[str, Any], account: Account, collected_at: str) -> Draft | None:
        native = str(raw.get("id") or "")
        url = str(raw.get("webVideoUrl") or "")
        if not native or not url:
            return None
        author = (raw.get("authorMeta") or {}).get("name")
        if author and account.handle and author.lower() != account.handle.lstrip("@").lower():
            return None
        meta = raw.get("videoMeta") or {}
        cover = meta.get("originalCoverUrl") or meta.get("coverUrl") or ""
        slides = raw.get("slideshowImageLinks") or []
        if raw.get("isSlideshow") and slides and isinstance(slides[0], dict):
            cover = slides[0].get("downloadLink") or slides[0].get("tiktokLink") or cover
        metrics = {
            "likes": raw.get("diggCount"), "comments_count": raw.get("commentCount"),
            "shares": raw.get("shareCount"), "views": raw.get("playCount"), "saves": raw.get("collectCount"),
        }
        item = CollectedItem(
            id=f"tiktok:{native}",
            platform="tiktok",
            kind="post" if raw.get("isSlideshow") else "video",
            url=url,
            account_url=account.url,
            published_at=str(raw.get("createTimeISO") or ""),
            text=str(raw.get("text") or ""),
            metrics={k: int(v) for k, v in metrics.items() if isinstance(v, (int, float))},
            collected_at=collected_at,
            subtitle_tracks=project_tracks(raw),
        )
        return Draft(
            item=item,
            image_url=str(cover),
            video_url="" if raw.get("isSlideshow") else url,
            video_seconds=float(meta.get("duration") or 0.0),
        )

    def identity_basis(self, raw: dict[str, Any], ctx: RunContext) -> list[str]:
        author = raw.get("authorMeta") or {}
        return ["verified badge"] if author.get("verified") else []

    async def save_videos(self, ctx: RunContext, drafts: list[Draft], client: httpx.AsyncClient, token: str) -> int:
        board = identity_board(ctx)
        candidates = self.video_candidates(drafts)
        if board is None:
            return 0
        slots = await board.videos.claim("tiktok", len(candidates))
        chosen = candidates[:slots]
        if not chosen:
            return 0
        await ctx.progress(self.id, len(drafts), f"saving {len(chosen)} videos for transcription")
        by_url = {d.item.url: d for d in chosen}
        files: dict[str, str] = {}

        async def on_items(items: list[dict[str, Any]]) -> None:
            for raw in items:
                media = raw.get("mediaUrls") or []
                if raw.get("webVideoUrl") in by_url:
                    item = by_url[raw["webVideoUrl"]].item
                    if not any(t.get("status") == "retained" for t in item.subtitle_tracks):
                        item.subtitle_tracks = project_tracks(raw)
                        await capture_asr(ctx, item, client)
                if raw.get("webVideoUrl") in by_url and media:
                    files[raw["webVideoUrl"]] = media[0]

        try:
            result = await run_actor(TIKTOK_VIDEOS, {"postURLs": list(by_url)}, token=token, on_items=on_items)
            ctx.costs.apify_usd += result.usage_usd
            await _record_run(ctx, f"{self.id}.videos", TIKTOK_VIDEOS.actor_id, result.run_id, result.status,
                              result.item_count, result.usage_usd)
        except ApifyRunFailed as failure:
            ctx.costs.apify_usd += failure.usage_usd
            await _record_run(ctx, f"{self.id}.videos", TIKTOK_VIDEOS.actor_id, failure.run_id,
                              failure.status or "FAILED", 0, failure.usage_usd)
            return 0
        saved = 0
        for url, file_url in files.items():
            if await self.keep_video(ctx, by_url[url], file_url, client, token):
                saved += 1
        return saved
