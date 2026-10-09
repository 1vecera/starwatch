"""Website collector: the anchor website, crawled to depth 1 for up to 20 pages of text.

Each page becomes an item with its title and readable text. A page's social preview image
(og:image) becomes its thumbnail; the lane shows a picture only the first time it appears, so a
site-wide default image is not repeated.
"""

from __future__ import annotations

import hashlib
from typing import Any

from ..models import Account, CollectedItem
from .base import Collector, Draft


def _og(metadata: dict[str, Any], prop: str) -> str:
    for entry in metadata.get("openGraph") or []:
        if isinstance(entry, dict) and entry.get("property") == prop and entry.get("content"):
            return str(entry["content"])
    return ""


class WebsiteCollector(Collector):
    id = "collect.website"
    label = "Website"
    platform = "website"
    noun = "pages"

    def run_input(self, account: Account) -> dict[str, Any]:
        return {"startUrls": [{"url": account.url}]}

    def project(self, raw: dict[str, Any], account: Account, collected_at: str) -> Draft | None:
        url = str(raw.get("url") or (raw.get("crawl") or {}).get("loadedUrl") or "")
        text = str(raw.get("text") or "").strip()
        if not url or not text:
            return None
        metadata = raw.get("metadata") or {}
        title = str(metadata.get("title") or "").strip()
        published = _og(metadata, "article:published_time") or str(metadata.get("datePublished") or "")
        item = CollectedItem(
            id="website:" + hashlib.sha1(url.encode()).hexdigest()[:16],
            platform="website",
            kind="page",
            url=url,
            account_url=account.url,
            published_at=published,
            text=(f"{title}\n\n{text}" if title and not text.startswith(title) else text)[:20000],
            collected_at=collected_at,
        )
        return Draft(item=item, image_url=_og(metadata, "og:image"))
