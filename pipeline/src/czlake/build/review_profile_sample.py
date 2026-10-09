"""Audit an explicitly bounded cached profile run before attributing any metrics."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from ..land import now_iso
from ..paths import DATA
from ..textnorm import normkey
from .prepare_small_batch import CITY_CONTEXT


def review(raw_path: Path, batch_path: Path, output: Path) -> dict:
    raw, batch = json.loads(raw_path.read_text()), json.loads(batch_path.read_text())
    targets = {t["handle"]: t for t in batch["targets"]}
    expected = batch.get("input", {}).get("usernames") or list(targets)
    seen, profiles, posts = set(), [], {}
    since = datetime.fromisoformat("2026-04-09T00:00:00+02:00")
    until = datetime.fromisoformat("2026-10-09T00:00:00+02:00")
    for item in raw["items"]:
        handle = (item.get("username") or "").lower()
        target = targets.get(handle)
        if target is None:
            profiles.append({"handle": handle, "identity_status": "unexpected_or_error_result", "followers": None, "error": item.get("error"), "in_window_posts": 0})
            continue
        if handle in seen:
            raise ValueError("Duplicate returned profile")
        seen.add(handle)
        name = normkey(target["name"]) or ""
        display = normkey(item.get("fullName") or "") or ""
        bio = normkey(item.get("biography") or "") or ""
        matches_name = bool(name and name in display)
        matches_city = any(city in display + " " + bio for city in CITY_CONTEXT[target["city"]])
        public = item.get("private") is False and not item.get("error")
        # Self-description corroborates the cached proposal, but an independent
        # anchor linking this account is still required for ranking attribution.
        status = "public_name_and_local_role_corroborated_anchor_pending" if matches_name and matches_city and public else "public_name_only_anchor_pending" if matches_name and public else "conflicted_or_unavailable"
        retained = []
        for post in (item.get("latestPosts") or []) if public else []:
            if not post.get("id") or not post.get("timestamp"):
                continue
            date = datetime.fromisoformat(post["timestamp"])
            if not since <= date < until:
                continue
            key = f"instagram:{post['id']}"
            owner = (post.get("ownerUsername") or "").lower() or None
            relation = "observed_profile_is_owner" if owner == handle else "other_owner" if owner else "owner_unknown"
            # A profile bundle may include collaborative or tagged posts owned
            # by another account. Preserve each observation without calling it
            # a publication by the requested person or organization.
            posts[(key, handle)] = {"post_id": key, "handle": handle, "observed_profile_handle": handle,
                          "owner_handle": owner, "publication_relation": relation,
                          "entity_key": None, "requested_entity_key": target["key"],
                          "entity_kind": target.get("eligibility_kind", "current_candidacy"),
                          "published_at": post["timestamp"], "url": post.get("url"), "text": post.get("caption"),
                          "kind": post.get("type"), "likes": post.get("likesCount"), "comments_count": post.get("commentsCount"),
                          "views": post.get("videoViewCount"), "apify_run_id": raw["run_id"], "fetched_at": raw["fetched_at"]}
            retained.append(key)
        kind = target.get("eligibility_kind", "current_candidacy")
        profiles.append({"handle": handle, "name": target["name"], "city": target["city"], "requested_entity_key": target["key"],
                         "candidate_key": target["key"] if kind == "current_candidacy" else None,
                         "list_key": target["key"] if kind == "local_list" else None,
                         "entity_kind": target.get("eligibility_kind", "current_candidacy"), "identity_status": status,
                         "display_name": item.get("fullName"), "biography": item.get("biography"), "external_url": item.get("externalUrl"),
                         "public": public, "followers": item.get("followersCount") if public else None,
                         "followers_attributed_to_entity": None, "independent_anchor_required": True,
                         "profile_url": item.get("url"), "observed_at": raw["fetched_at"], "apify_run_id": raw["run_id"],
                         "latest_posts_returned": len(item.get("latestPosts") or []), "in_window_posts": len(set(retained)),
                         "post_ids": sorted(set(retained)), "protected": target.get("protected", False),
                         "source_path": str(raw_path), "cached_anchor": target.get("identity_evidence")})
    result = {"observed_at": now_iso(), "run_id": raw["run_id"], "requested_handles": expected,
              "returned_profiles": len(seen), "missing_handles": sorted(set(expected) - seen), "profiles": profiles,
              "posts": sorted(posts.values(), key=lambda p: (p["handle"], p["published_at"], p["post_id"])),
              "unique_in_window_posts": len({p["post_id"] for p in posts.values()}),
              "retained_post_observations": len(posts),
              "owner_relations": {relation: sum(p["publication_relation"] == relation for p in posts.values())
                                  for relation in ["observed_profile_is_owner", "other_owner", "owner_unknown"]},
              "social_cities": len({p["city"] for p in profiles if p.get("city")}),
              "window": [since.isoformat(), until.isoformat()], "complete_six_month_history": False,
              "ranking_attribution": "independent public account anchors pending; no account promotion or entity attribution"}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return {k: result[k] for k in ["run_id", "returned_profiles", "missing_handles", "unique_in_window_posts", "social_cities"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("raw", type=Path)
    parser.add_argument("--batch", type=Path, default=DATA / "inputs/top10_small_ranked_profile_batch.json")
    parser.add_argument("--output", type=Path, default=DATA / "evidence/top10_profile_review.json")
    args = parser.parse_args()
    print(json.dumps(review(args.raw, args.batch, args.output)))
