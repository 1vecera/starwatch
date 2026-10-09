"""The Apify Actor behind each platform, with the per-run caps from the build spec.

`max_items` and `max_charge_usd` are passed to Apify as run options, so the platform enforces them
even if an input field is wrong. `base_input` holds the input fields that keep runs small and keep
comments and follower lists off; each collector adds its target (URL or handle) on top.

`fields` is the allowlist of top-level dataset fields Starwatch reads. It is sent to Apify with every
dataset request, so comment previews (`topComments`, `latestComments`, `firstComment`), tagged users
and other people's data never reach this machine; the collectors then project what arrives into a
`CollectedItem`.

Field names follow each Actor's live input schema and observed output, checked on 8 October 2026.
`clockworks/tiktok-scraper` refuses a `maxTotalChargeUsd` below $0.50, so its cap sits at that
minimum while `maxItems` keeps the real cost near $0.08.
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
    fields: tuple[str, ...] = ()  # dataset fields to fetch; empty means all
    memory_mb: int | None = None  # run memory; None keeps the Actor's default
    abort_at_cap: bool = True  # stop the run once max_items arrived; False waits for it to finish
    idle_stop_s: float | None = None  # stop once results have arrived and none came for this long


# Comments, follower lists and transcripts off for every TikTok run.
_TIKTOK_OFF = {
    "commentsPerPost": 0,
    "topLevelCommentsPerPost": 0,
    "maxRepliesPerComment": 0,
    "maxFollowersPerProfile": 0,
    "maxFollowingPerProfile": 0,
    "downloadSubtitlesOptions": "NEVER_DOWNLOAD_SUBTITLES",
    "shouldDownloadAvatars": False,
    "shouldDownloadMusicCovers": False,
    "aiVideoDescription": False,
    "aiVideoSummary": False,
}

ACTORS: dict[Platform, ActorSpec] = {
    "website": ActorSpec(
        "website",
        "apify/website-content-crawler",
        max_items=15,
        max_charge_usd=0.10,
        base_input={
            "maxCrawlDepth": 1,
            "maxCrawlPages": 15,
            "maxResults": 15,
            "crawlerType": "cheerio",
            "proxyConfiguration": {"useApifyProxy": True},
            "requestTimeoutSecs": 20,
            "maxRequestRetries": 1,
            "saveMarkdown": False,
            "saveHtml": False,
        },
        timeout_s=75,  # a slow site keeps what it delivered instead of holding the run back
        fields=("url", "crawl", "metadata", "text"),
        memory_mb=1024,
    ),
    "facebook": ActorSpec(
        "facebook",
        "apify/facebook-posts-scraper",
        max_items=30,
        max_charge_usd=0.20,
        base_input={"resultsLimit": 30, "captionText": False},
        timeout_s=180,
        fields=(
            "postId", "url", "topLevelUrl", "time", "text", "user", "pageName", "facebookUrl",
            "likes", "comments", "shares", "viewsCount", "isVideo", "media",
        ),
    ),
    "instagram": ActorSpec(
        "instagram",
        "apify/instagram-scraper",
        max_items=30,
        max_charge_usd=0.12,
        base_input={"resultsType": "posts", "resultsLimit": 30, "addParentData": False},
        timeout_s=180,
        fields=(
            "id", "type", "shortCode", "caption", "url", "timestamp", "displayUrl", "videoUrl",
            "dimensionsWidth", "dimensionsHeight", "likesCount", "commentsCount", "videoViewCount",
            "videoPlayCount", "videoDuration", "locationName", "ownerUsername", "ownerFullName",
            "productType", "isPinned", "alt",
        ),
    ),
    "tiktok": ActorSpec(
        "tiktok",
        "clockworks/tiktok-scraper",
        max_items=20,
        max_charge_usd=0.50,  # the Actor's minimum; 20 results cost about $0.06
        base_input={
            "resultsPerPage": 20,
            "profileSorting": "latest",
            # The video add-on holds every item back until its video is saved (first item after
            # ~80 s instead of ~15 s), so posts stream without it and TIKTOK_VIDEOS fetches the few
            # videos transcription needs. Covers are saved by Starwatch straight from the CDN.
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": False,
            "shouldDownloadSlideshowImages": False,
            **_TIKTOK_OFF,
        },
        timeout_s=180,
        fields=(
            "id", "text", "createTimeISO", "webVideoUrl", "videoMeta", "mediaUrls", "diggCount",
            "shareCount", "playCount", "commentCount", "collectCount", "authorMeta", "isSlideshow",
            "slideshowImageLinks", "isPinned", "locationCreated",
        ),
    ),
    "youtube": ActorSpec(
        "youtube",
        "streamers/youtube-scraper",
        max_items=10,
        max_charge_usd=0.06,
        base_input={
            "maxResults": 6,
            "maxResultsShorts": 4,
            "maxResultStreams": 0,
            "sortVideosBy": "NEWEST",
            "transcriptionAndSubtitle": "NONE",
        },
        timeout_s=180,
        fields=(
            "id", "type", "title", "url", "thumbnailUrl", "viewCount", "likes", "date", "duration",
            "text", "channelName", "channelUrl", "channelUsername", "channelDescriptionLinks",
            "isChannelVerified", "numberOfSubscribers", "commentsCount",
        ),
    ),
    "x": ActorSpec(
        "x",
        "apidojo/twitter-scraper-lite",
        max_items=30,
        max_charge_usd=0.10,
        base_input={"maxItems": 30, "sort": "Latest"},
        timeout_s=150,
        fields=(
            "type", "id", "url", "text", "fullText", "createdAt", "likeCount", "retweetCount",
            "replyCount", "quoteCount", "viewCount", "author", "extendedEntities", "isRetweet",
            "isQuote", "isReply", "lang",
        ),
    ),
}

# The few TikTok videos kept for transcription, fetched by URL after the posts have streamed in.
TIKTOK_VIDEOS = ActorSpec(
    "tiktok",
    "clockworks/tiktok-scraper",
    max_items=3,
    max_charge_usd=0.50,  # the Actor's minimum; 3 videos cost about $0.013
    base_input={"shouldDownloadVideos": True, "shouldDownloadCovers": False, **_TIKTOK_OFF},
    timeout_s=150,
    fields=("id", "webVideoUrl", "mediaUrls", "videoMeta"),
    abort_at_cap=False,  # by URL the Actor pushes items first and saves the videos after them
)

# Identity resolution: name searches that surface the official account and its look-alikes.
# Only profile fields are read; no posts of the people found, no follower lists, no pictures.
SEARCHES: dict[Platform, ActorSpec] = {
    "instagram": ActorSpec(
        "instagram",
        "apify/instagram-scraper",
        max_items=6,
        max_charge_usd=0.03,
        base_input={"searchType": "user", "searchLimit": 6, "resultsType": "details", "resultsLimit": 1},
        timeout_s=60,
        idle_stop_s=12,
        fields=(
            "username", "fullName", "url", "biography", "externalUrl", "verified", "private",
            "businessCategoryName",
        ),
    ),
    "tiktok": ActorSpec(
        "tiktok",
        "clockworks/tiktok-scraper",
        max_items=6,
        max_charge_usd=0.50,  # the Actor's minimum; 6 profiles cost about $0.02
        base_input={"searchSection": "/user", "maxProfilesPerQuery": 6, "resultsPerPage": 1, **_TIKTOK_OFF},
        timeout_s=60,
        idle_stop_s=12,
        fields=("authorMeta",),
    ),
}

# Fallback when the anchor website refuses a direct request: one Apify crawl of the start page
# that keeps header and footer links, where official social links usually sit.
ANCHOR_CRAWL = ActorSpec(
    "website",
    "apify/website-content-crawler",
    max_items=3,
    max_charge_usd=0.05,
    base_input={
        "maxCrawlDepth": 0,
        "maxCrawlPages": 3,
        "crawlerType": "playwright:firefox",
        "proxyConfiguration": {"useApifyProxy": True},
        "removeElementsCssSelector": "script, style, noscript",
        "htmlTransformer": "none",
        "saveMarkdown": True,
    },
    timeout_s=90,
    fields=("url", "markdown", "metadata"),
    memory_mb=2048,
)

# Videos saved locally for transcription, filled in this platform order.
MAX_VIDEO_DOWNLOADS = 3
VIDEO_PLATFORMS: tuple[Platform, ...] = ("tiktok", "instagram")
MAX_VIDEO_SECONDS = 240
MAX_VIDEO_BYTES = 80 * 1024 * 1024
MAX_TIKTOK_VIDEO_DOWNLOADS = MAX_VIDEO_DOWNLOADS
MAX_TRANSCRIBED_VIDEOS = 5
