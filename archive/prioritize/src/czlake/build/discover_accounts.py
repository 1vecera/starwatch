"""Account discovery through Apify Google Search: one query per person restricted to social sites.

Lands the SERP items under raw/apify/serp_accounts/, then stages staging.serp_social_hits with one
row per (person, result), the platform and handle parsed from the URL. Identity is decided later
(core.account) by matching name, city/party and profile text; nothing here is accepted blindly.
"""
from __future__ import annotations

import json
import re
import sys
from urllib.parse import urlparse

import pyarrow as pa

from .. import lakehouse as lh
from ..apify_run import run_actor
from ..paths import RAW

SITES = "(site:facebook.com OR site:instagram.com OR site:tiktok.com OR site:youtube.com OR site:x.com OR site:twitter.com)"
PRICE = 0.0025


def plat_handle(url: str) -> tuple[str | None, str | None]:
    u = urlparse(url)
    host = u.netloc.lower().removeprefix("www.").removeprefix("m.").removeprefix("cs-cz.").removeprefix("cs.")
    parts = [p for p in u.path.split("/") if p]
    if not parts:
        return None, None
    if host.endswith("facebook.com"):
        if parts[0] in ("people",) and len(parts) > 1:
            return "facebook", parts[1]
        if parts[0] in ("groups", "events", "watch", "photo", "photos", "story.php", "permalink.php", "share", "reel", "videos", "hashtag"):
            return "facebook_other", parts[0]
        if parts[0] == "profile.php":
            return "facebook", "profile.php?" + (u.query or "")
        return "facebook", parts[0]
    if host.endswith("instagram.com"):
        if parts[0] in ("p", "reel", "reels", "explore", "stories", "tv"):
            return "instagram_post", parts[1] if len(parts) > 1 else None
        return "instagram", parts[0]
    if host.endswith("tiktok.com"):
        if parts[0].startswith("@"):
            return "tiktok", parts[0][1:]
        return "tiktok_other", parts[0]
    if host.endswith("youtube.com"):
        if parts[0].startswith("@"):
            return "youtube", parts[0]
        if parts[0] in ("channel", "c", "user") and len(parts) > 1:
            return "youtube", f"{parts[0]}/{parts[1]}"
        return "youtube_other", parts[0]
    if host in ("x.com", "twitter.com") or host.endswith(".x.com") or host.endswith("twitter.com"):
        if parts[0] in ("search", "hashtag", "i", "home"):
            return "x_other", parts[0]
        return "x", parts[0]
    return None, None


def queries_for(limit_sql: str) -> list[tuple[str, str]]:
    con = lh.duck()
    rows = con.sql(f"""
      select person_id, first_name, last_name, tier, a_city, reasons from marts.ranked_set_v1 where {limit_sql}
      order by tier, best_city_rank nulls first, score_official desc nulls last
    """).fetchall()
    out = []
    for pid, fn, ln, tier, city, reasons in rows:
        ctx = city or ""
        if tier == 1:
            ctx = "poslanec" if "MP 2025" in reasons else ("senátor" if "Senator" in reasons else "europoslanec")
        out.append((pid, f'"{fn} {ln}" {ctx} {SITES}'.replace("  ", " ")))
    return out


def run(limit_sql: str, batch: int = 200, tag: str = "serp_accounts") -> dict:
    con = lh.duck()
    done = set()
    try:
        done = {r[0] for r in con.sql("select distinct person_id from staging.serp_social_hits").fetchall()}
    except Exception:  # noqa: BLE001
        pass
    qs = [(p, q) for p, q in queries_for(limit_sql) if p not in done]
    total_rows = 0
    for i in range(0, len(qs), batch):
        chunk = qs[i:i + batch]
        qmap = {q: p for p, q in chunk}
        inp = {"queries": "\n".join(q for _, q in chunk), "maxPagesPerQuery": 1, "countryCode": "cz",
               "searchLanguage": "cs", "languageCode": "cs", "mobileResults": False, "saveHtml": False,
               "saveHtmlToKeyValueStore": False, "includeUnfilteredResults": False}
        res = run_actor("apify/google-search-scraper", inp, max(0.5, round(len(chunk) * PRICE * 1.3 + 0.01, 3)),
                        f"account discovery: Google SERP for {len(chunk)} ranked politicians", landing=tag, timeout_s=1800)
        rows = []
        for page in res["items"]:
            term = (page.get("searchQuery") or {}).get("term")
            pid = qmap.get(term)
            for rank, o in enumerate(page.get("organicResults") or [], 1):
                plat, handle = plat_handle(o.get("url", ""))
                rows.append({"person_id": pid, "query": term, "rank": rank, "url": o.get("url"), "title": o.get("title"),
                             "description": o.get("description"), "platform": plat, "handle": handle,
                             "apify_run_id": res["run_id"], "fetched_at": lh.stamp()})
        if rows:
            lh.write("staging", "serp_social_hits", pa.Table.from_pylist(rows), mode="append")
            total_rows += len(rows)
        print(json.dumps({"batch": i // batch, "queries": len(chunk), "rows": len(rows), "usd": res["usage_total_usd"]}), flush=True)
    return {"queries": len(qs), "rows": total_rows}


if __name__ == "__main__":
    where = sys.argv[1] if len(sys.argv) > 1 else "tier=1 or (tier=2 and best_city_rank<=30)"
    print(run(where))
