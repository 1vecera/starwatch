"""The Apify Actor behind each platform, with the per-run caps from the build spec.

`max_items` and `max_charge_usd` are passed to Apify as run options, so the platform enforces them
even if an input field is wrong. `base_input` holds the input fields that keep runs small and keep
comments and follower lists off; each collector adds its target (URL or handle) on top.
Field names follow each Actor's input schema as of 8 October 2026; re-check a schema before relying
on a field that changes cost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import Platform


@dataclass(frozen=True)
class ActorSpec:
    platform: Platform
    actor_id: str
    max_items: int
    max_charge_usd: float
    base_input: dict[str, Any] = field(default_factory=dict)
    timeout_s: int = 300


ACTORS: dict[Platform, ActorSpec] = {
    "website": ActorSpec(
        "website",
        "apify/website-content-crawler",
        max_items=20,
        max_charge_usd=0.10,
        base_input={"maxCrawlDepth": 1, "maxCrawlPages": 20, "crawlerType": "cheerio"},
    ),
    "facebook": ActorSpec(
        "facebook",
        "apify/facebook-posts-scraper",
        max_items=30,
        max_charge_usd=0.20,
        base_input={"resultsLimit": 30},
    ),
    "instagram": ActorSpec(
        "instagram",
        "apify/instagram-scraper",
        max_items=30,
        max_charge_usd=0.12,
        base_input={"resultsType": "posts", "resultsLimit": 30, "addParentData": False},
    ),
    "tiktok": ActorSpec(
        "tiktok",
        "clockworks/tiktok-scraper",
        max_items=20,
        max_charge_usd=0.12,
        base_input={
            "resultsPerPage": 20,
            "commentsPerPost": 0,
            "shouldDownloadVideos": True,  # the Actor stores them; Starwatch transcribes at most 3
            "shouldDownloadCovers": True,
            "shouldDownloadSubtitles": False,
        },
    ),
    "youtube": ActorSpec(
        "youtube",
        "streamers/youtube-scraper",
        max_items=10,
        max_charge_usd=0.06,
        base_input={"maxResults": 10, "maxResultsShorts": 10, "maxResultStreams": 0},
    ),
    "x": ActorSpec(
        "x",
        "apidojo/twitter-scraper-lite",
        max_items=30,
        max_charge_usd=0.10,
        base_input={"maxItems": 30, "sort": "Latest"},
    ),
}

# Spec caps that are not Actor runs.
MAX_TIKTOK_VIDEO_DOWNLOADS = 3
MAX_TRANSCRIBED_VIDEOS = 5
