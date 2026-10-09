"""Stage cached audited samples, attributing only independently anchored entities."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow as pa

from .. import lakehouse as lh
from ..paths import DATA, PROJECT
from .collect_social import _append


def post_attribution(post: dict, profile: dict, people: dict) -> dict:
    confirmed = profile.get("followers_attributed_to_entity") is not None
    observed_entity = profile["requested_entity_key"] if confirmed else None
    owned = confirmed and post.get("owner_handle") == profile["handle"]
    person = people.get(profile["candidate_key"]) if owned and profile.get("candidate_key") else None
    return {"person_id": person, "entity_key": observed_entity if owned else None,
            "list_key": profile.get("list_key") if owned else None,
            "observed_profile_entity_key": observed_entity,
            "attribution_basis": "independently_anchored_account_is_post_owner" if owned else "observed_profile_association_only"}


def unique_posts(paths: list[Path], output: Path) -> dict:
    """Canonical IDs with every account/run observation preserved separately."""
    posts = {}
    for path in paths:
        review = json.loads(path.read_text())
        profiles = {p["handle"]: p for p in review["profiles"]}
        for post in review["posts"]:
            observation = post | post_attribution(post, profiles[post["handle"]], {})
            posts.setdefault(post["post_id"], []).append(observation)
    rows = [{"post_id": key, "owner_handles": sorted({p["owner_handle"] for p in observations if p.get("owner_handle")}),
             "owner_conflict": len({p["owner_handle"] for p in observations if p.get("owner_handle")}) > 1,
             "direct_entity_keys": sorted({p["entity_key"] for p in observations if p.get("entity_key")}),
             "observed_profile_entity_keys": sorted({p["observed_profile_entity_key"] for p in observations if p.get("observed_profile_entity_key")}),
             "observations": observations} for key, observations in sorted(posts.items())]
    result = {"unique_posts": len(rows), "retained_observations": sum(len(row["observations"]) for row in rows),
              "shared_post_ids": sum(len(row["observations"]) > 1 for row in rows),
              "owner_conflicts": sum(row["owner_conflict"] for row in rows),
              "independently_anchored_owned_unique_posts": sum(bool(row["direct_entity_keys"]) for row in rows),
              "posts": rows}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return {key: value for key, value in result.items() if key != "posts"}


def stage(paths: list[Path], refresh_reviewed_runs: bool = False) -> dict:
    records = json.loads((PROJECT / "tmp/prioritization/universe.json").read_text())
    people = {r["candidate"]["key"]: r["person_id"] for r in records}
    con = lh.duck()
    posts, profiles, result = [], [], []
    for path in paths:
        review = json.loads(path.read_text())
        run_id = review["run_id"]
        if any(row["run_id"] == run_id for row in result):
            raise ValueError("Each reviewed run must appear exactly once")
        by_handle = {p["handle"]: p for p in review["profiles"] if p.get("requested_entity_key")}
        wanted = {"social_profile": len(by_handle), "social_post": len(review["posts"])}
        landed = {}
        for table, count in wanted.items():
            exists = con.execute("select count(*) from information_schema.tables where table_schema='staging' and table_name=?", [table]).fetchall()[0][0]
            landed[table] = con.execute(f"select count(*) from staging.{table} where apify_run_id=?", [run_id]).fetchall()[0][0] if exists else 0
            if landed[table] not in (0, count):
                raise ValueError(f"Partial or incompatible landing for {run_id}/{table}; inspect before appending")
        for p in by_handle.values():
            if landed["social_profile"] and not refresh_reviewed_runs:
                continue
            confirmed = p.get("followers_attributed_to_entity") is not None
            person = people.get(p["candidate_key"]) if confirmed and p.get("candidate_key") else None
            profiles.append({"platform": "instagram", "collector": "instagram-profile-scraper", "handle": p["handle"],
                             "account_id": None, "person_id": person, "entity_kind": p["entity_kind"],
                             "entity_key": p["requested_entity_key"] if confirmed else None,
                             "requested_entity_key": p["requested_entity_key"], "list_key": p.get("list_key") if confirmed else None,
                             "identity_status": p["identity_status"], "display_name": p["display_name"], "bio": p["biography"],
                             "followers": p["followers"], "followers_attributed_to_entity": p.get("followers_attributed_to_entity"),
                             "public": p["public"], "external_url": p["external_url"], "observed_at": p["observed_at"],
                             "apify_run_id": run_id, "profile_url": p["profile_url"], "review_path": str(path)})
        for post in review["posts"]:
            if landed["social_post"] and not refresh_reviewed_runs:
                continue
            profile = by_handle[post["handle"]]
            posts.append(post | post_attribution(post, profile, people) | {
                                 "platform": "instagram", "collector": "instagram-profile-scraper", "account_id": None,
                                 "identity_status": profile["identity_status"], "review_path": str(path),
                                 "coverage": "bounded_recent_profile_bundle"})
        result.append({"run_id": run_id, "profiles": wanted["social_profile"], "posts": wanted["social_post"], "already_landed": landed})
    con.close()
    if refresh_reviewed_runs:
        run_ids = {row["run_id"] for row in result}
        for table, rows in [("social_post", posts), ("social_profile", profiles)]:
            fresh = lh._iceberg_safe(pa.Table.from_pylist(rows))
            if lh.catalog().table_exists(f"staging.{table}"):
                old = lh.read("staging", table)
                other = old.filter(pa.array([run_id not in run_ids for run_id in old["apify_run_id"].to_pylist()]))
                fresh = pa.concat_tables([fresh, other], promote_options="permissive")
            lh.write("staging", table, fresh)
    else:
        _append(posts, profiles)
    check = lh.duck()
    for row in result:
        for table, key in [("social_profile", "profiles"), ("social_post", "posts")]:
            observed = check.execute(f"select count(*) from staging.{table} where apify_run_id=?", [row["run_id"]]).fetchall()[0][0]
            if observed != row[key]:
                raise ValueError(f"Landing verification failed for {row['run_id']}/{table}")
    check.close()
    return {"projected_profiles": len(profiles), "projected_posts": len(posts), "refreshed_reviewed_runs": refresh_reviewed_runs, "runs": result}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reviews", nargs="*", type=Path, default=[DATA / "evidence/top10_profile_review.json", DATA / "evidence/top10_organization_profile_review.json"])
    parser.add_argument("--refresh-reviewed-runs", action="store_true", help="Replace only these exact run projections after identity/owner review, retaining all other rows")
    args = parser.parse_args()
    print(json.dumps(stage(args.reviews, args.refresh_reviewed_runs)))
    print(json.dumps(unique_posts(args.reviews, DATA / "evidence/top10_unique_posts.json")))
