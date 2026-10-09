"""YouTube collector: up to 10 videos with thumbnails (6 newest videos and 4 newest Shorts)."""

from __future__ import annotations

from typing import Any

from ..models import Account, CollectedItem
from ..steps.base import RunContext
from .identity import domain_of, identity_board, same_site
from .base import Collector, Draft


def _seconds(duration: str) -> float:
    try:
        parts = [int(p) for p in str(duration).split(":")]
    except ValueError:
        return 0.0
    total = 0
    for part in parts:
        total = total * 60 + part
    return float(total)


class YoutubeCollector(Collector):
    id = "collect.youtube"
    label = "YouTube"
    platform = "youtube"
    noun = "videos"

    def run_input(self, account: Account) -> dict[str, Any]:
        return {"startUrls": [{"url": account.url}]}

    def display_name(self, raw: dict[str, Any], account: Account) -> str:
        return str(raw.get("channelName") or "")

    def project(self, raw: dict[str, Any], account: Account, collected_at: str) -> Draft | None:
        native = str(raw.get("id") or "")
        url = str(raw.get("url") or "")
        if not native or not url:
            return None
        title = str(raw.get("title") or "")
        description = str(raw.get("text") or "")
        metrics = {"views": raw.get("viewCount"), "likes": raw.get("likes"), "comments_count": raw.get("commentsCount")}
        item = CollectedItem(
            id=f"youtube:{native}",
            platform="youtube",
            kind="video",
            url=url,
            account_url=account.url,
            published_at=str(raw.get("date") or ""),
            text=f"{title}\n\n{description}".strip(),
            metrics={k: int(v) for k, v in metrics.items() if isinstance(v, (int, float))},
            collected_at=collected_at,
        )
        thumb = str(raw.get("thumbnailUrl") or f"https://i.ytimg.com/vi/{native}/hqdefault.jpg")
        return Draft(item=item, image_url=thumb, video_seconds=_seconds(raw.get("duration") or ""))

    def identity_basis(self, raw: dict[str, Any], ctx: RunContext) -> list[str]:
        board = identity_board(ctx)
        basis = []
        if raw.get("isChannelVerified"):
            basis.append("verified badge")
        if board and board.anchor.domain:
            links = raw.get("channelDescriptionLinks") or []
            if any(same_site(domain_of(str(link.get("url") or "")), board.anchor.domain) for link in links if isinstance(link, dict)):
                basis.append(f"channel links {board.anchor.domain}")
        return basis
