"""Write web/data/stats.js (window.SW_STATS): public aggregate numbers about the snapshot.

stats.js is one of the few data files the edge serves without sign-in, so the public About page
reads its coverage tables from here and never from real.js. Two optional sources:
  - the pinned production checkpoint manifest (collection totals), when it exists on this machine;
  - web/data/real.js (the exported snapshot), for per-platform and per-city coverage under "public".
Only aggregate counts are written: no names of people, no post text, no media paths.

Usage: uv run --offline python tools/export_stats.py [--real web/data/real.js] [--out web/data/stats.js]
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib

APP = pathlib.Path(__file__).resolve().parent.parent
MANIFEST_ROOT = pathlib.Path("/home/vecera/code/agents007-hackathon/tmp/production/read")
PLATFORMS = [("instagram", "Instagram"), ("facebook", "Facebook"), ("tiktok", "TikTok"), ("youtube", "YouTube"),
             ("x", "X"), ("news", "News"), ("web", "Web")]
COLLECTED = "8–9 October 2026"
VIDEO_TYPES = {"video", "reel"}


def manifest_totals() -> dict:
    """Headline collection totals from the production manifest, or {} when it is not on this machine."""
    try:
        cur = json.loads((MANIFEST_ROOT / "current.json").read_text())
        man = json.loads((MANIFEST_ROOT / cur["manifest"]).read_text())
    except (OSError, KeyError, ValueError):
        return {}
    c = man.get("counts", {})
    return {
        "checkpoint_id": cur["checkpoint_id"], "created_at": cur.get("created_at"),
        "collected_posts": c.get("asset"), "verified_posts": c.get("verified_assets"),
        "metric_values": c.get("metric"), "media_files": c.get("media_resource"), "sources": c.get("source"),
        "accounts_discovered": c.get("account"), "verified_accounts": c.get("verified_accounts"),
        "registered_entities": c.get("entity"), "cities": c.get("area"), "reviewed_statements": c.get("claim"),
        "topics": c.get("topic"), "web_pages": c.get("web_asset"), "publishers": c.get("publisher"),
        "portrait_coverage_entities": c.get("entity_photo_coverage"), "quarantined_records": c.get("quarantine"),
        "production_observations": c.get("production_observation"),
        "coverage_notes": man.get("coverage", {}), "privacy": man.get("privacy"),
    }


def load_raw(path: pathlib.Path) -> dict | None:
    """Parse `window.SW_RAW = {...};` without executing it."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return None
    raw = json.loads(text[start:end + 1])
    return raw if isinstance(raw, dict) and raw.get("assets") is not None else None


def public_coverage(raw: dict) -> dict:
    """Aggregate coverage per platform and per city, computed from the exported snapshot."""
    lists, cands, accounts, assets = raw.get("lists", []), raw.get("cands", []), raw.get("accounts", []), raw.get("assets", [])
    city_of = {x["id"]: x.get("city_id") for x in lists + cands}
    posts_by_city: dict[str, int] = {}
    for a in assets:
        cid = city_of.get(a.get("owner_entity_id"))
        if cid:
            posts_by_city[cid] = posts_by_city.get(cid, 0) + 1
    acc_by_city: dict[str, int] = {}
    for acc in accounts:
        cid = city_of.get(acc.get("entity_id"))
        if cid:
            acc_by_city[cid] = acc_by_city.get(cid, 0) + 1
    platforms = []
    for key, name in PLATFORMS:
        mine = [a for a in assets if a.get("platform") == key]
        n_acc = sum(1 for acc in accounts if acc.get("platform") == key)
        platforms.append({"platform": key, "name": name, "posts": len(mine), "accounts": n_acc,
                          "playable_videos": sum(1 for a in mine if a.get("video")),
                          "status": "observed" if mine else "accounts_only" if n_acc else "not_collected"})
    cities = []
    for c in sorted(raw.get("cities", []), key=lambda c: -posts_by_city.get(c["id"], 0)):
        ls = [x for x in lists if x.get("city_id") == c["id"]]
        cities.append({"id": c["id"], "name": c["name"], "lists": len(ls), "relevant_lists": sum(1 for x in ls if x.get("relevant")),
                       "candidacies": sum(1 for x in cands if x.get("city_id") == c["id"]),
                       "accounts": acc_by_city.get(c["id"], 0), "posts": posts_by_city.get(c["id"], 0)})
    published = sorted(a["published_at"] for a in assets if a.get("published_at"))
    observed = sorted(a["observed_at"] for a in assets if a.get("observed_at"))
    src = raw.get("source") or {}
    return {
        "snapshot": {"collected": COLLECTED, "checkpoint_id": src.get("checkpoint_id"), "exported_at": src.get("exported_at"),
                     "published_from": published[0] if published else None, "published_to": published[-1] if published else None,
                     "observed_from": observed[0] if observed else None, "observed_to": observed[-1] if observed else None},
        "totals": {"posts": len(assets), "accounts": len(accounts), "lists": len(lists),
                   "relevant_lists": sum(1 for x in lists if x.get("relevant")), "candidacies": len(cands),
                   "cities": len(raw.get("cities", [])), "playable_videos": sum(1 for a in assets if a.get("video")),
                   "video_posts": sum(1 for a in assets if str(a.get("type") or "").lower() in VIDEO_TYPES),
                   "posts_with_image": sum(1 for a in assets if a.get("image")),
                   "topic_labelled_posts": sum(1 for a in assets if a.get("topics")),
                   "topics": len(raw.get("topics", [])),
                   "lists_with_2022_result": sum(1 for x in lists if x.get("result2022")),
                   "candidates_with_2022_votes": sum(1 for x in cands if x.get("pref2022"))},
        "platforms": platforms,
        "cities": cities,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--real", type=pathlib.Path, default=APP / "web" / "data" / "real.js")
    ap.add_argument("--out", type=pathlib.Path, default=APP / "web" / "data" / "stats.js")
    args = ap.parse_args()
    stats = manifest_totals()
    stats["exported_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    raw = load_raw(args.real)
    if raw is not None:
        stats["public"] = public_coverage(raw)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.is_symlink():  # never write through a link into another checkout
        args.out.unlink()
    args.out.write_text("/* Public aggregate numbers about the Starwatch snapshot. Generated; local only. */\n"
                        "window.SW_STATS=" + json.dumps(stats, ensure_ascii=False) + ";\n", encoding="utf-8")
    pub = stats.get("public", {}).get("totals", {})
    print(json.dumps({"checkpoint_id": stats.get("checkpoint_id"), "posts": pub.get("posts"), "cities": pub.get("cities")}))


if __name__ == "__main__":
    main()
