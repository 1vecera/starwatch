"""X collector: up to 30 posts from the accepted account."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..models import Account, CollectedItem
from ..steps.base import RunContext
from .base import Collector, Draft


def _iso(created_at: str) -> str:
    try:
        return datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y").isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        return str(created_at or "")


def _image(raw: dict[str, Any]) -> str:
    for media in (raw.get("extendedEntities") or {}).get("media") or []:
        url = media.get("media_url_https")
        if url:
            # The small rendition (680 px) is plenty for a lane and arrives faster.
            return f"{url}?name=small" if "pbs.twimg.com/media/" in url and "?" not in url else url
    return ""


class XCollector(Collector):
    id = "collect.x"
    label = "X"
    platform = "x"

    def run_input(self, account: Account) -> dict[str, Any]:
        return {"twitterHandles": [account.handle.lstrip("@")]}

    def display_name(self, raw: dict[str, Any], account: Account) -> str:
        author = raw.get("author") or {}
        if str(author.get("userName") or "").lower() != account.handle.lstrip("@").lower():
            return ""  # a repost shows the original author
        return str(author.get("name") or "")

    def project(self, raw: dict[str, Any], account: Account, collected_at: str) -> Draft | None:
        if raw.get("type") not in (None, "tweet"):
            return None
        native = str(raw.get("id") or "")
        url = str(raw.get("url") or "")
        if not native or not url:
            return None
        metrics = {
            "likes": raw.get("likeCount"), "reposts": raw.get("retweetCount"),
            "replies_count": raw.get("replyCount"), "quotes": raw.get("quoteCount"), "views": raw.get("viewCount"),
        }
        item = CollectedItem(
            id=f"x:{native}",
            platform="x",
            kind="post",
            url=url,
            account_url=account.url,
            published_at=_iso(str(raw.get("createdAt") or "")),
            text=str(raw.get("fullText") or raw.get("text") or ""),
            metrics={k: int(v) for k, v in metrics.items() if isinstance(v, (int, float))},
            collected_at=collected_at,
        )
        return Draft(item=item, image_url=_image(raw))

    def identity_basis(self, raw: dict[str, Any], ctx: RunContext) -> list[str]:
        author = raw.get("author") or {}
        kind = author.get("verifiedType")
        if kind:
            return [f"X {str(kind).lower()} badge"]
        if author.get("isVerified"):
            return ["verified badge"]
        return []
