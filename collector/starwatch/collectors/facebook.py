"""Facebook collector: up to 30 posts from the accepted page, comments off.

Only the allowlisted dataset fields are fetched (`ACTORS["facebook"].fields`), so the Actor's
`topComments` never reach Starwatch; the post text, date, counts and first picture are kept.
"""

from __future__ import annotations

from typing import Any

from ..models import Account, CollectedItem
from .base import Collector, Draft


def _first_image(media: list[dict[str, Any]]) -> str:
    for entry in media or []:
        for key in ("photo_image", "image", "thumbnailImage"):
            uri = (entry.get(key) or {}).get("uri") if isinstance(entry.get(key), dict) else None
            if uri:
                return uri
        if entry.get("thumbnail"):
            return str(entry["thumbnail"])
    return ""


class FacebookCollector(Collector):
    id = "collect.facebook"
    label = "Facebook"
    platform = "facebook"

    def run_input(self, account: Account) -> dict[str, Any]:
        return {"startUrls": [{"url": account.url}]}

    def display_name(self, raw: dict[str, Any], account: Account) -> str:
        return str((raw.get("user") or {}).get("name") or "")  # collaborators' posts are outvoted

    def project(self, raw: dict[str, Any], account: Account, collected_at: str) -> Draft | None:
        post_id = str(raw.get("postId") or "")
        url = str(raw.get("url") or raw.get("topLevelUrl") or "")
        if not post_id or not url:
            return None
        metrics = {
            "likes": raw.get("likes"), "comments_count": raw.get("comments"),
            "shares": raw.get("shares"), "views": raw.get("viewsCount"),
        }
        item = CollectedItem(
            id=f"facebook:{post_id}",
            platform="facebook",
            kind="video" if raw.get("isVideo") else "post",
            url=url,
            account_url=account.url,
            published_at=str(raw.get("time") or ""),
            text=str(raw.get("text") or ""),
            metrics={k: int(v) for k, v in metrics.items() if isinstance(v, (int, float))},
            collected_at=collected_at,
        )
        return Draft(item=item, image_url=_first_image(raw.get("media") or []))
