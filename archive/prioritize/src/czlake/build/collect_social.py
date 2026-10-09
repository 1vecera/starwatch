"""M3 social collection through Apify, under the ledger cap.

Each collector picks accepted accounts from core.account (by person tier), runs one Actor, lands the
raw dataset, and appends normalised rows to staging.social_post and staging.social_profile.
Comments, commenter identities and follower lists are never requested and are dropped if present.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow as pa

from .. import lakehouse as lh
from ..apify_run import run_actor
from ..land import now_iso

SINCE = "2026-04-09"  # six months before 8 Oct 2026


def accounts(platform: str, where: str, exclude_collected: str | None = None, limit: int = 10000) -> list[tuple]:
    con = lh.duck()
    sql = f"""
      select a.account_id, a.person_id, a.handle, a.url, r.tier, r.display_name
      from core.account a join marts.ranked_set_v1 r using (person_id)
      where a.platform='{platform}' and a.status='accepted' and ({where})
      order by r.tier, r.best_city_rank nulls first, r.score_official desc nulls last
    """
    rows = con.sql(sql).fetchall()
    if exclude_collected:
        try:
            done = {r[0] for r in con.sql(f"select distinct handle from staging.social_profile where platform='{platform}' and collector='{exclude_collected}'").fetchall()}
        except Exception:  # noqa: BLE001
            done = set()
        rows = [r for r in rows if r[2] not in done]
    seen, out = set(), []
    for r in rows:  # one row per handle (several persons may share a party page)
        if r[2] in seen:
            continue
        seen.add(r[2])
        out.append(r)
    return out[:limit]


def _append(posts: list[dict], profiles: list[dict]) -> None:
    if posts:
        lh.write("staging", "social_post", pa.Table.from_pylist(posts), mode="append")
    if profiles:
        lh.write("staging", "social_profile", pa.Table.from_pylist(profiles), mode="append")


def _s(x):
    return None if x is None else str(x)


def instagram_profiles(where: str, max_usd: float | None = None, limit: int = 10000) -> dict:
    acc = accounts("instagram", where, exclude_collected="instagram-profile-scraper", limit=limit)
    if not acc:
        return {"skipped": "no accounts"}
    hmap = {a[2]: a for a in acc}
    inp = {"usernames": list(hmap), "includeAboutSection": False}
    res = run_actor("apify/instagram-profile-scraper", inp, max_usd or round(len(acc) * 0.0023 * 1.3 + 0.02, 3),
                    f"M3 Instagram profiles + latest posts for {len(acc)} accounts", landing="m3_instagram_profiles", timeout_s=3600)
    posts, profiles, fetched = [], [], now_iso()
    for p in res["items"]:
        u = (p.get("username") or "").lower()
        a = hmap.get(u)
        profiles.append({"platform": "instagram", "collector": "instagram-profile-scraper", "handle": u,
                         "account_id": a[0] if a else None, "person_id": a[1] if a else None,
                         "display_name": p.get("fullName"), "bio": p.get("biography"), "followers": p.get("followersCount"),
                         "following": p.get("followsCount"), "posts_count": p.get("postsCount"), "verified": p.get("verified"),
                         "external_url": p.get("externalUrl"), "category": p.get("businessCategoryName"),
                         "avatar_url": p.get("profilePicUrlHD") or p.get("profilePicUrl"), "observed_at": fetched,
                         "apify_run_id": res["run_id"], "profile_url": f"https://www.instagram.com/{u}/"})
        for x in p.get("latestPosts") or []:
            posts.append({"platform": "instagram", "collector": "instagram-profile-scraper", "post_id": f"instagram:{x.get('id')}",
                          "handle": u, "account_id": a[0] if a else None, "person_id": a[1] if a else None,
                          "url": x.get("url"), "published_at": x.get("timestamp"), "text": x.get("caption"),
                          "kind": (x.get("type") or "").lower(), "likes": x.get("likesCount"), "comments_count": x.get("commentsCount"),
                          "shares": None, "views": x.get("videoViewCount") or x.get("videoPlayCount"), "duration_s": x.get("videoDuration"),
                          "location": x.get("locationName"), "media_url": x.get("displayUrl"), "is_pinned": x.get("isPinned"),
                          "hashtags": json.dumps(x.get("hashtags") or [], ensure_ascii=False),
                          "mentions": json.dumps(x.get("mentions") or [], ensure_ascii=False),
                          "fetched_at": fetched, "apify_run_id": res["run_id"]})
    _append(posts, profiles)
    return {"run_id": res["run_id"], "usd": res["usage_total_usd"], "profiles": len(profiles), "posts": len(posts)}


def tiktok_profiles(where: str, per_profile: int = 50, max_usd: float | None = None, limit: int = 10000) -> dict:
    acc = accounts("tiktok", where, exclude_collected="tiktok-profile-scraper", limit=limit)
    if not acc:
        return {"skipped": "no accounts"}
    hmap = {a[2]: a for a in acc}
    inp = {"profiles": list(hmap), "resultsPerPage": per_profile, "profileSorting": "latest", "excludePinnedPosts": False,
           "profileScrapeSections": ["videos"], "shouldDownloadVideos": False, "shouldDownloadCovers": False,
           "commentsPerPost": 0, "maxFollowersPerProfile": 0, "maxFollowingPerProfile": 0}
    res = run_actor("clockworks/tiktok-profile-scraper", inp, max_usd or round(len(acc) * per_profile * 0.002 * 1.15 + 0.05, 3),
                    f"M3 TikTok latest {per_profile} videos for {len(acc)} accounts", landing="m3_tiktok", timeout_s=3600)
    posts, prof, fetched = [], {}, now_iso()
    for it in res["items"]:
        am = it.get("authorMeta") or {}
        u = (am.get("name") or "").lower()
        a = hmap.get(u)
        prof[u] = {"platform": "tiktok", "collector": "tiktok-profile-scraper", "handle": u, "account_id": a[0] if a else None,
                   "person_id": a[1] if a else None, "display_name": am.get("nickName"), "bio": am.get("signature"),
                   "followers": am.get("fans"), "following": am.get("following"), "posts_count": am.get("video"),
                   "verified": am.get("verified"), "external_url": am.get("bioLink"), "category": None,
                   "avatar_url": am.get("avatar"), "observed_at": fetched, "apify_run_id": res["run_id"],
                   "profile_url": f"https://www.tiktok.com/@{u}", "likes_total": am.get("heart")}
        vm = it.get("videoMeta") or {}
        subs = [s.get("language") + ":" + (s.get("source") or "") for s in vm.get("subtitleLinks") or []]
        posts.append({"platform": "tiktok", "collector": "tiktok-profile-scraper", "post_id": f"tiktok:{it.get('id')}", "handle": u,
                      "account_id": a[0] if a else None, "person_id": a[1] if a else None, "url": it.get("webVideoUrl"),
                      "published_at": it.get("createTimeISO"), "text": it.get("text"), "kind": "video",
                      "likes": it.get("diggCount"), "comments_count": it.get("commentCount"), "shares": it.get("shareCount"),
                      "views": it.get("playCount"), "duration_s": vm.get("duration"), "location": None,
                      "media_url": vm.get("coverUrl"), "is_pinned": it.get("isPinned"),
                      "hashtags": json.dumps([h.get("name") for h in it.get("hashtags") or []], ensure_ascii=False),
                      "mentions": json.dumps(it.get("mentions") or [], ensure_ascii=False),
                      "subtitle_tracks": ",".join(subs), "width": vm.get("width"), "height": vm.get("height"),
                      "fetched_at": fetched, "apify_run_id": res["run_id"]})
    _append(posts, list(prof.values()))
    from .tiktok_subs import fetch_for
    subs = fetch_for(Path(res["raw_path"]))
    return {"run_id": res["run_id"], "usd": res["usage_total_usd"], "profiles": len(prof), "posts": len(posts), "subtitles": subs}


def facebook_pages(where: str, max_usd: float | None = None, limit: int = 10000) -> dict:
    acc = accounts("facebook", where, exclude_collected="facebook-pages-scraper", limit=limit)
    acc = [a for a in acc if not a[2].startswith("profile.php")]
    if not acc:
        return {"skipped": "no accounts"}
    hmap = {a[2]: a for a in acc}
    inp = {"startUrls": [{"url": f"https://www.facebook.com/{h}"} for h in hmap]}
    res = run_actor("apify/facebook-pages-scraper", inp, max_usd or round(len(acc) * 0.0082 * 1.25 + 0.05, 3),
                    f"M3 Facebook page metrics for {len(acc)} pages", landing="m3_facebook_pages", timeout_s=3600)
    profiles, fetched = [], now_iso()
    for p in res["items"]:
        url = p.get("facebookUrl") or p.get("pageUrl") or p.get("url") or ""
        h = url.rstrip("/").split("/")[-1].lower() if url else None
        a = hmap.get(h) or next((v for k, v in hmap.items() if url and k in url.lower()), None)
        profiles.append({"platform": "facebook", "collector": "facebook-pages-scraper", "handle": a[2] if a else h,
                         "account_id": a[0] if a else None, "person_id": a[1] if a else None,
                         "display_name": p.get("title") or p.get("pageName"), "bio": p.get("intro") or p.get("info"),
                         "followers": p.get("followers"), "following": None, "posts_count": None,
                         "verified": p.get("verified") or p.get("isVerified"), "external_url": p.get("website"),
                         "category": ", ".join(p.get("categories") or []) if isinstance(p.get("categories"), list) else _s(p.get("categories")),
                         "avatar_url": p.get("profilePictureUrl") or p.get("profilePhoto"), "observed_at": fetched,
                         "apify_run_id": res["run_id"], "profile_url": url, "likes_total": p.get("likes"),
                         "page_created": _s(p.get("creation_date") or p.get("pageCreationDate"))})
    _append([], profiles)
    return {"run_id": res["run_id"], "usd": res["usage_total_usd"], "profiles": len(profiles)}


def facebook_posts(where: str, per_page: int = 60, since: str = SINCE, max_usd: float | None = None, limit: int = 10000) -> dict:
    acc = accounts("facebook", where, limit=limit)
    acc = [a for a in acc if not a[2].startswith("profile.php")]
    if not acc:
        return {"skipped": "no accounts"}
    hmap = {a[2]: a for a in acc}
    inp = {"startUrls": [{"url": f"https://www.facebook.com/{h}"} for h in hmap], "resultsLimit": per_page,
           "onlyPostsNewerThan": since, "captionText": False}
    res = run_actor("apify/facebook-posts-scraper", inp, max_usd or round(len(acc) * (per_page * 0.005 + 0.001) * 1.1, 3),
                    f"M3 Facebook posts since {since} (<= {per_page}/page) for {len(acc)} pages", landing="m3_facebook_posts", timeout_s=3600)
    posts, fetched = [], now_iso()
    for x in res["items"]:
        page = (x.get("facebookUrl") or x.get("pageUrl") or "").rstrip("/").split("/")[-1].lower()
        a = hmap.get(page) or next((v for k, v in hmap.items() if k in (x.get("facebookUrl") or x.get("url") or "").lower()), None)
        media = x.get("media") or []
        thumb = None
        if media and isinstance(media, list):
            m0 = media[0] or {}
            thumb = m0.get("thumbnail") or (m0.get("photo_image") or {}).get("uri") or m0.get("url")
        posts.append({"platform": "facebook", "collector": "facebook-posts-scraper", "post_id": f"facebook:{x.get('postId') or x.get('id')}",
                      "handle": a[2] if a else page, "account_id": a[0] if a else None, "person_id": a[1] if a else None,
                      "url": x.get("url") or x.get("topLevelUrl"), "published_at": x.get("time"), "text": x.get("text"),
                      "kind": "video" if x.get("isVideo") else ("photo" if media else "text"), "likes": x.get("likes"),
                      "comments_count": x.get("comments"), "shares": x.get("shares"), "views": x.get("viewsCount"),
                      "duration_s": None, "location": None, "media_url": thumb, "is_pinned": None,
                      "hashtags": None, "mentions": None, "fetched_at": fetched, "apify_run_id": res["run_id"]})
    _append(posts, [])
    return {"run_id": res["run_id"], "usd": res["usage_total_usd"], "posts": len(posts)}


def youtube_channels(where: str, per_channel: int = 30, since: str = SINCE, max_usd: float | None = None, limit: int = 10000) -> dict:
    acc = accounts("youtube", where, exclude_collected="youtube-channel-scraper", limit=limit)
    if not acc:
        return {"skipped": "no accounts"}
    hmap = {a[2]: a for a in acc}
    urls = []
    for h in hmap:
        urls.append({"url": f"https://www.youtube.com/{h}" if (h.startswith("@") or "/" in h) else f"https://www.youtube.com/channel/{h}"})
    inp = {"startUrls": urls, "maxResults": per_channel, "maxResultsShorts": per_channel, "maxResultStreams": 0, "oldestPostDate": since}
    res = run_actor("streamers/youtube-channel-scraper", inp, max_usd or round(len(acc) * per_channel * 2 * 0.001 * 1.2 + 0.05, 3),
                    f"M3 YouTube videos+shorts since {since} for {len(acc)} channels", landing="m3_youtube", timeout_s=3600)
    posts, prof, fetched = [], {}, now_iso()
    for v in res["items"]:
        cu = (v.get("channelUrl") or v.get("inputChannelUrl") or "")
        key = next((k for k in hmap if k.lower().strip("@") in cu.lower() or k.lower().strip("@") in (v.get("channelUsername") or "").lower()), None)
        a = hmap.get(key)
        ch = v.get("channelName")
        prof[cu] = {"platform": "youtube", "collector": "youtube-channel-scraper", "handle": key or cu, "account_id": a[0] if a else None,
                    "person_id": a[1] if a else None, "display_name": ch, "bio": v.get("channelDescription"),
                    "followers": v.get("numberOfSubscribers"), "following": None, "posts_count": v.get("channelTotalVideos"),
                    "verified": v.get("isChannelVerified"), "external_url": None, "category": None, "avatar_url": v.get("channelAvatarUrl"),
                    "observed_at": fetched, "apify_run_id": res["run_id"], "profile_url": cu}
        posts.append({"platform": "youtube", "collector": "youtube-channel-scraper", "post_id": f"youtube:{v.get('id')}",
                      "handle": key or cu, "account_id": a[0] if a else None, "person_id": a[1] if a else None, "url": v.get("url"),
                      "published_at": v.get("date"), "text": (v.get("title") or "") + ("\n" + v["text"] if v.get("text") else ""),
                      "kind": "short" if "/shorts/" in (v.get("url") or "") else "video", "likes": v.get("likes"),
                      "comments_count": v.get("commentsCount"), "shares": None, "views": v.get("viewCount"),
                      "duration_s": _s(v.get("duration")), "location": v.get("location"), "media_url": v.get("thumbnailUrl"),
                      "is_pinned": None, "hashtags": json.dumps(v.get("hashtags") or [], ensure_ascii=False), "mentions": None,
                      "fetched_at": fetched, "apify_run_id": res["run_id"]})
    _append(posts, list(prof.values()))
    return {"run_id": res["run_id"], "usd": res["usage_total_usd"], "profiles": len(prof), "posts": len(posts)}


def x_tweets(where: str, per_handle: int = 40, since: str = SINCE, max_usd: float | None = None, limit: int = 10000) -> dict:
    acc = accounts("x", where, exclude_collected="tweet-scraper", limit=limit)
    if not acc:
        return {"skipped": "no accounts"}
    hmap = {a[2]: a for a in acc}
    inp = {"twitterHandles": list(hmap), "maxItems": len(acc) * per_handle, "sort": "Latest", "start": since,
           "includeSearchTerms": False}
    res = run_actor("apidojo/tweet-scraper", inp, max_usd or round(len(acc) * per_handle * 0.0004 * 1.2 + 0.05, 3),
                    f"M3 X posts since {since} (~{per_handle}/handle) for {len(acc)} handles", landing="m3_x", timeout_s=3600)
    posts, prof, fetched = [], {}, now_iso()
    for t in res["items"]:
        au = t.get("author") or {}
        u = (au.get("userName") or "").lower()
        a = hmap.get(u)
        if u:
            prof[u] = {"platform": "x", "collector": "tweet-scraper", "handle": u, "account_id": a[0] if a else None,
                       "person_id": a[1] if a else None, "display_name": au.get("name"), "bio": au.get("description"),
                       "followers": au.get("followers"), "following": au.get("following"), "posts_count": au.get("statusesCount"),
                       "verified": au.get("isBlueVerified") or au.get("isVerified"), "external_url": None, "category": None,
                       "avatar_url": au.get("profilePicture"), "observed_at": fetched, "apify_run_id": res["run_id"],
                       "profile_url": f"https://x.com/{u}"}
        if t.get("type") not in (None, "tweet") or t.get("isRetweet"):
            kind = "repost"
        else:
            kind = "reply" if t.get("isReply") else ("quote" if t.get("isQuote") else "post")
        posts.append({"platform": "x", "collector": "tweet-scraper", "post_id": f"x:{t.get('id')}", "handle": u,
                      "account_id": a[0] if a else None, "person_id": a[1] if a else None, "url": t.get("url") or t.get("twitterUrl"),
                      "published_at": t.get("createdAt"), "text": t.get("text") or t.get("fullText"), "kind": kind,
                      "likes": t.get("likeCount"), "comments_count": t.get("replyCount"), "shares": t.get("retweetCount"),
                      "views": t.get("viewCount"), "duration_s": None, "location": None, "media_url": None, "is_pinned": None,
                      "hashtags": None, "mentions": None, "fetched_at": fetched, "apify_run_id": res["run_id"]})
    _append(posts, list(prof.values()))
    return {"run_id": res["run_id"], "usd": res["usage_total_usd"], "profiles": len(prof), "posts": len(posts)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("collector", choices=["instagram", "tiktok", "fbpages", "fbposts", "youtube", "x"])
    ap.add_argument("--where", default="tier=1")
    ap.add_argument("--limit", type=int, default=10000)
    ap.add_argument("--per", type=int)
    ap.add_argument("--max-usd", type=float)
    a = ap.parse_args()
    fn = {"instagram": instagram_profiles, "tiktok": tiktok_profiles, "fbpages": facebook_pages, "fbposts": facebook_posts,
          "youtube": youtube_channels, "x": x_tweets}[a.collector]
    kw = {"max_usd": a.max_usd, "limit": a.limit}
    if a.per and a.collector in ("tiktok",):
        kw["per_profile"] = a.per
    elif a.per and a.collector == "fbposts":
        kw["per_page"] = a.per
    elif a.per and a.collector == "youtube":
        kw["per_channel"] = a.per
    elif a.per and a.collector == "x":
        kw["per_handle"] = a.per
    print(json.dumps(fn(a.where, **kw), ensure_ascii=False))
