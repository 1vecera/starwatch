"""Instagram collector: up to 30 posts from the accepted profile, images downloaded at collection.

Instagram's CDN links expire within hours and refuse hotlinking, so every picture is saved into the
run folder straight away. Comment previews (`latestComments`, `firstComment`) and tagged users are
not in the dataset fields Starwatch requests. Reels up to four minutes can be kept for transcription
when TikTok leaves video slots free.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..models import Account, CollectedItem
from ..steps.base import RunContext
from .identity import identity_board
from .base import Collector, Draft


class InstagramCollector(Collector):
    id = "collect.instagram"
    label = "Instagram"
    platform = "instagram"

    def run_input(self, account: Account) -> dict[str, Any]:
        return {"directUrls": [f"https://www.instagram.com/{account.handle.strip('/')}/"]}

    def display_name(self, raw: dict[str, Any], account: Account) -> str:
        if str(raw.get("ownerUsername") or "").lower() != account.handle.strip("/").lower():
            return ""
        return str(raw.get("ownerFullName") or "")

    def project(self, raw: dict[str, Any], account: Account, collected_at: str) -> Draft | None:
        short = str(raw.get("shortCode") or "")
        url = str(raw.get("url") or (f"https://www.instagram.com/p/{short}/" if short else ""))
        native = str(raw.get("id") or short)
        if not native or not url:
            return None
        if raw.get("ownerUsername") and account.handle and raw["ownerUsername"].lower() != account.handle.lower():
            return None  # a post of another profile; only the subject's own feed is collected
        is_video = raw.get("type") == "Video" or raw.get("productType") == "clips"
        metrics = {
            "likes": raw.get("likesCount"), "comments_count": raw.get("commentsCount"),
            "views": raw.get("videoPlayCount") or raw.get("videoViewCount"),
        }
        text = str(raw.get("caption") or "")
        item = CollectedItem(
            id=f"instagram:{native}",
            platform="instagram",
            kind="video" if is_video else "post",
            url=url,
            account_url=account.url,
            published_at=str(raw.get("timestamp") or ""),
            text=text,
            metrics={k: int(v) for k, v in metrics.items() if isinstance(v, (int, float)) and v >= 0},
            collected_at=collected_at,
        )
        return Draft(
            item=item,
            image_url=str(raw.get("displayUrl") or ""),
            video_url=str(raw.get("videoUrl") or "") if is_video else "",
            video_seconds=float(raw.get("videoDuration") or 0.0),
        )

    async def save_videos(self, ctx: RunContext, drafts: list[Draft], client: httpx.AsyncClient, token: str) -> int:
        board = identity_board(ctx)
        candidates = self.video_candidates(drafts)
        if board is None or not candidates:
            return 0
        slots = await board.videos.claim("instagram", len(candidates))
        saved = 0
        for draft in candidates:
            if saved >= slots:
                break
            if await self.keep_video(ctx, draft, draft.video_url, client, token):
                saved += 1
        return saved
