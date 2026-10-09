"""Versioned, offline relevance-v2 comparison and held collection handoff.

Reads the collector's final cached evidence; never imports a collector or writes
the lake/data evidence. Run with --project /path/to/project.
"""

from __future__ import annotations

import os
import argparse
import hashlib
import json
from dataclasses import asdict, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from ..priority import RULE_VERSION, Candidate, qualify, schedule, stable_key
from .prioritize import reviewed_signals

INPUTS = (
    "data/evidence/top10_prioritization_refreshed.json",
    "data/evidence/top10_prioritization_refreshed_manifest.json",
    "data/evidence/ten_city_examples.json",
    "data/evidence/top10_profile_review.json",
    "data/evidence/top10_organization_profile_review.json",
    "data/evidence/top10_public_identity_review.json",
    "data/evidence/top10_collection_receipt.json",
    "data/inputs/top10_small_ranked_profile_batch.json",
    "tmp/explore/source-audit/live-actor-prices.json",
    "tmp/explore/source-audit/next-probes.json",
)
FIELDS = ("components", "reasons", "winner", "score", "qualified", "protected")
LEADERSHIP = {"prior_leader", "list_leader"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def state(row: dict) -> dict:
    return {k: row[k] for k in FIELDS}


def recompute(rows: list[dict], as_of: datetime | None = None) -> tuple[list[dict], dict]:
    """Rescore unchanged accepted inputs; expose every changed reason/component."""
    if len({r["candidate"]["key"] for r in rows}) != len(rows):
        raise ValueError("Duplicate candidacy/role keys")
    revised, changes = [], {"retained": [], "removed": [], "added": [], "changed": []}
    for row in rows:
        candidate = Candidate(**row["candidate"])
        if as_of is not None:
            activity, office, reviews, disputes = reviewed_signals(
                row["reviewed_sources"],
                candidate.key if candidate.eligibility_kind == "current_candidacy" else None,
                candidate.city_code,
                as_of,
            )
            handles = {
                (r["platform"], r["handle"].lower()) for r in reviews if r["kind"] == "account_identity"
            }
            handles &= {(a["platform"], a["handle"].lower()) for a in row["verified_accounts"]}
            measurements = [
                m
                for m in row["metrics"]
                if fresh(m["observed_at"], as_of)
                and (m["platform"], m["handle"].lower()) in handles
                and "account_identity" not in disputes
            ]
            candidate = replace(
                candidate,
                followers=max((m["followers"] for m in measurements), default=None),
                activity_verified=activity,
                current_office_verified=office,
            )
        evidence = row["evidence"]
        if candidate.eligibility_kind == "current_candidacy" and (
            evidence["election_id"] != "kv2026"
            or evidence["unit_type"] != "city_council"
            or evidence["unit_code"] != candidate.city_code
        ):
            raise ValueError("Expected exact current city-council candidacy grain")
        if candidate.eligibility_kind == "current_candidacy" and candidate.eligible != (
            evidence["validity"] == "A"
        ):
            raise ValueError("Candidacy validity and eligibility disagree")
        decision = qualify(candidate)
        new = {k: getattr(decision, k) for k in FIELDS}
        new["reasons"] = list(new["reasons"])
        outcome = (
            "retained"
            if row["qualified"] and decision.qualified
            else "removed"
            if row["qualified"]
            else "added"
            if decision.qualified
            else "unqualified"
        )
        why = (
            "Independent strong signal retained: " + ", ".join(decision.reasons)
            if decision.qualified
            else "Current or historical leadership was the only qualifying evidence; leadership now opens discovery only."
            if row["qualified"]
            else "No admissible observed channel reaches one; missing evidence remains unknown."
        )
        result = {
            **row,
            **new,
            "candidate": asdict(candidate),
            "old_candidate": row["candidate"],
            "rule_version": RULE_VERSION,
            "old": state(row),
            "change_kind": outcome,
            "change_explanation": why,
            "leadership_context": {
                "current_position": candidate.position,
                "prior_leader": candidate.prior_leader,
                "reviewed_local_role": candidate.local_role_verified,
            },
        }
        revised.append(result)
        if outcome in changes:
            changes[outcome].append(candidate.key)
        if state(row) != new:
            changes["changed"].append(
                {
                    "key": candidate.key,
                    "city": row["city"],
                    "name": row["name"],
                    "old": state(row),
                    "new": new,
                    "why": why,
                    "changed_components": {
                        k: {
                            "old": row["components"][k],
                            "new": new["components"][k],
                            "why": "Leadership disabled as relevance; retained as discovery context."
                            if k in LEADERSHIP
                            else "Evidence freshness/identity gate at the declared as-of.",
                        }
                        for k in new["components"]
                        if row["components"][k] != new["components"][k]
                    },
                    "removed_reasons": sorted(set(row["reasons"]) - set(new["reasons"])),
                }
            )
    return revised, changes


def fresh(timestamp: str, as_of: datetime) -> bool:
    return 0 <= (as_of - datetime.fromisoformat(timestamp)).total_seconds() <= 30 * 86400


def rank_lists(lists: list[dict], candidates: list[dict], as_of: datetime) -> list[dict]:
    """Rank organization evidence independently; valid-list discovery is a queue."""
    cities = {r["candidate"]["city_code"]: r["candidate"]["population"] for r in candidates}
    valid_lists = {
        (r["candidate"]["city_code"], r["candidate"]["list_no"])
        for r in candidates
        if r["candidate"]["eligible"] and r["candidate"]["eligibility_kind"] == "current_candidacy"
    }
    result = []
    for row in lists:
        if row["key"] != f"kv2026:{row['municipality_code']}:{row['list_no']}":
            raise ValueError("Local-list key and current city/list grain disagree")
        eligible = (row["municipality_code"], row["list_no"]) in valid_lists
        old = row["priority"]
        components = {k: v for k, v in old["components"].items() if k != "current_valid_list_discovery"}
        measurement = row.get("social_metrics") or {}
        anchor = measurement.get("identity_evidence") or {}
        anchor_url = urlparse(anchor.get("source_url") or "")
        verified = bool(
            eligible
            and measurement.get("public")
            and anchor.get("adjudication") == "confirmed"
            and anchor.get("identity_confirmed")
            and anchor.get("anchor_links_account")
            and anchor.get("public")
            and anchor_url.scheme in ("https", "http")
            and anchor_url.hostname
            and not (anchor_url.username or anchor_url.password)
            and anchor.get("excerpt", "").strip()
            # Some final confirmed review cards predate explicit scope/list_no
            # fields. Their collector-reviewed exact local-list key and attributed
            # metric retain that provenance; an explicit broader scope still fails.
            and anchor.get("scope", "city_political_organization") == "city_political_organization"
            and anchor.get("list_no", row["list_no"]) == row["list_no"]
            and measurement.get("list_key") == row["key"]
            and measurement.get("entity_kind") == "local_list"
            and anchor.get("handle") == measurement.get("handle")
            and fresh(anchor["observed_at"], as_of)
            and fresh(measurement["observed_at"], as_of)
            and measurement.get("followers_attributed_to_entity") == measurement.get("followers")
        )
        followers = measurement.get("followers") if verified else None
        if followers is not None and (not isinstance(followers, int) or followers < 0):
            raise ValueError("Invalid organization follower observation")
        components["organization_reach"] = (
            min(
                2.0,
                max(
                    followers / 10_000,
                    followers / (0.1 * cities[row["municipality_code"]]),
                ),
            )
            if followers is not None
            else None
        )
        # Profile bundles/programme links alone are not action adjudications.
        # Only explicit reviews on this exact organization/city can open that route.
        activity_reviews = [
            r
            for r in row.get("reviewed_sources", [])
            if r.get("entity_id") == row["key"] and r.get("entity_kind") == "local_list"
        ]
        activity, _, activity_sources, _ = reviewed_signals(
            activity_reviews,
            None,
            row["municipality_code"],
            as_of,
        )
        components["organization_activity"] = float(activity) if activity is not None else None
        score = max((v for v in components.values() if v is not None), default=0.0)
        reasons = [k for k, v in components.items() if v is not None and v >= 1]
        result.append(
            {
                **row,
                "old_priority": old,
                "rule_version": RULE_VERSION,
                "priority": {
                    "score": score,
                    "components": components,
                    "reasons": reasons,
                    "winner": next((k for k, v in components.items() if v == score), None) if score else None,
                    "sources": old["sources"],
                    "shares": old["shares"],
                },
                "discovery_eligible": eligible,
                "qualified": eligible and score >= 1,
                "verified_account": verified,
                "reviewed_activity_sources": activity_sources,
                "protected": eligible
                and score >= 1
                and any(
                    components[k] is not None and components[k] >= 1
                    for k in ("organization_reach", "organization_activity")
                )
                and all(
                    v is None or v < 1
                    for k, v in components.items()
                    if k not in ("organization_reach", "organization_activity")
                ),
                "explanation": "Valid current local list retained for discovery; paid relevance requires its own electoral/reach/action evidence. Person scores are never transferred.",
            }
        )
    return result


def select_thirty(rows: list[dict]) -> dict:
    qualified = [qualify(Candidate(**r["candidate"])) for r in rows if r["qualified"]]
    plan = schedule(qualified, 30, Decimal(0), {d.candidate.key: Decimal(0) for d in qualified})
    # Discovery is an additional review allocation, never counted as meaningful qualification.
    all_decisions = [qualify(Candidate(**r["candidate"])) for r in rows]
    discovery = schedule(
        all_decisions,
        30,
        Decimal(0),
        {d.candidate.key: Decimal(0) for d in all_decisions},
    )
    return {
        "status": "proposal_not_collected",
        "qualified_keys": [d.candidate.key for d in plan.selected],
        "qualifying_overflow": [d.candidate.key for d in plan.deferred],
        "protected_requested": plan.protected_slots_requested,
        "protected_filled": plan.protected_slots_filled,
        "additional_discovery_keys": [d.candidate.key for d in discovery.exploratory],
        "per_city": {str(i): sum(d.candidate.city_rank == i for d in plan.selected) for i in range(1, 11)},
    }


def confirmed_card(row: dict, profile: dict, anchor: dict) -> dict:
    return {
        "key": row["candidate"]["key"] if "candidate" in row else row["key"],
        "entity_kind": "current_candidacy" if "candidate" in row else "local_list",
        "city": row["city"],
        "name": row["name"],
        "platform": "instagram",
        "handle": profile["handle"],
        "profile_url": profile["profile_url"],
        "anchor_url": anchor["source_url"],
        "observed_at": profile["observed_at"],
        "source_path": profile["source_path"],
        "reuse": "fresh cached profile and attributable owned posts; no repeat profile purchase",
    }


def collection_manifest(
    rows: list[dict], lists: list[dict], selection: dict, sources: dict, as_of: datetime
) -> dict:
    by_key = {r["candidate"]["key"]: r for r in rows}
    sampled = sources["data/evidence/top10_profile_review.json"]["profiles"]
    identity = sources["data/evidence/top10_public_identity_review.json"]
    confirmed = []
    for profile in sampled:
        row = by_key[profile["candidate_key"]]
        anchor = identity["candidates"].get(profile["candidate_key"], {})
        if (
            row["qualified"]
            and row["verified_accounts"]
            and row["metrics"]
            and fresh(profile["observed_at"], as_of)
            and anchor.get("adjudication") == "confirmed"
        ):
            confirmed.append(confirmed_card(row, profile, anchor))
    for row in lists:
        if row["qualified"] and row["verified_account"]:
            measurement = row["social_metrics"]
            confirmed.append(confirmed_card(row, measurement, measurement["identity_evidence"]))
    confirmed.sort(key=lambda r: (r["entity_kind"], r["city"], r["key"]))
    handles = sorted({r["handle"] for r in confirmed})
    confirmed_keys = {r["key"] for r in confirmed}
    cities, discovery_targets = [], []
    for rank in range(1, 11):
        qualified = [r for r in rows if r["qualified"] and r["candidate"]["city_rank"] == rank]
        qualified.sort(key=lambda r: stable_key(qualify(Candidate(**r["candidate"]))))
        selected = [
            by_key[k] for k in selection["qualified_keys"] if by_key[k]["candidate"]["city_rank"] == rank
        ]
        deferred = [
            {
                "key": r["candidate"]["key"],
                "name": r["name"],
                "city": r["city"],
                "official_source": r["evidence"]["source_url"],
                "cached_provisional_handles": sorted(
                    {
                        a["handle"]
                        for a in r["accounts"]
                        if a["platform"] == "instagram" and a["status"] != "rejected"
                    }
                ),
                "maximum_public_anchor_pages": 2,
                "attribution": "unknown_until_independent_exact_account_anchor",
            }
            for r in selected
            if r["candidate"]["key"] not in confirmed_keys
        ]
        discovery_targets.extend(deferred[:2])
        cities.append(
            {
                "city": qualified[0]["city"],
                "city_rank": rank,
                "qualified_keys": [r["candidate"]["key"] for r in qualified],
                "initial_qualified_review_keys": [r["candidate"]["key"] for r in selected],
                "deferred_identity": deferred,
                "protected_keys": [r["candidate"]["key"] for r in qualified if r["protected"]],
            }
        )
    for target in discovery_targets:
        target["query"] = f"{target['name']} {target['city']} politik kandidát instagram"
        target["query_status"] = "check_exact_cached_query_completion_first; at_most_one_new_SERP_if_missing"
    # Already audited exact Facebook input, restricted to a v2-qualified organization.
    probe = next(
        p
        for p in sources["tmp/explore/source-audit/next-probes.json"]["probes"]
        if p["name"] == "optional_two_city_organization_facebook_sample"
    )
    facebook = {
        **probe,
        "name": "qualified_spolu_usti_facebook_proof",
        "input": {
            **probe["input"],
            "startUrls": [{"url": "https://www.facebook.com/spoluprousti"}],
        },
        "expected_usd": "0.0210",
        "hard_ceiling_usd": "0.04",
        "run_options": {
            **probe["run_options"],
            "maxItems": 5,
            "maxTotalChargeUsd": 0.04,
        },
        "events": {"post": 5, "actor-start": 1, "filter-applied": 0},
    }
    if not any(
        r["qualified"] and (r.get("social_metrics") or {}).get("handle") == "spoluprousti" for r in lists
    ):
        raise ValueError("The exact Facebook probe needs a separately qualified current local organization")
    # Match hos-explore/apify_run.input_digest; whitespace is part of a SHA-256.
    facebook["input_sha256"] = hashlib.sha256(
        json.dumps(facebook["input"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "rule_version": RULE_VERSION,
        "status": "proposal_only_no_authorization_or_reservation",
        "per_city": cities,
        "confirmed_cached_reuse_targets": confirmed,
        "unknown_handle_discovery_targets": discovery_targets,
        "additional_exploration_keys": selection["additional_discovery_keys"],
        "deduplicated_confirmed_instagram_handles": handles,
        "exact_runnable_confirmed_probe": facebook,
        "conditional_stages": [
            {
                "stage": "public_identity_review",
                "targets": "all initial 300 qualified review records; cached/official anchors first",
                "max_pages_per_unconfirmed_person": 2,
                "provider_cost_usd": "0",
            },
            {
                "stage": "bounded_missing_handle_discovery",
                "max_new_queries": len(discovery_targets),
                "exact_queries": [r["query"] for r in discovery_targets],
                "platform_order": ["instagram", "facebook"],
                "max_pages_per_query": 1,
                "expected_upper_usd": str(
                    Decimal(len(discovery_targets)) * Decimal("0.0025") + Decimal("0.00005")
                ),
                "proposed_ceiling_usd": "0.08",
                "price_needs_refresh": True,
                "gate": "deduplicate exact cached query; no broad retries; stopped missing stays missing",
            },
            {
                "stage": "new_independently_anchored_profiles",
                "max_profiles": len(discovery_targets),
                "actor": "apify/instagram-profile-scraper",
                "includeAboutSection": False,
                "expected_upper_usd": str(Decimal(len(discovery_targets)) * Decimal("0.0023")),
                "proposed_ceiling_usd": "0.06",
                "exact_handles": [],
                "gate": "populate a new exact manifest only after public identity review; fresh cached profiles reused",
            },
            {
                "stage": "optional_deeper_confirmed_instagram_posts",
                "handles": handles,
                "max_posts_per_handle": 20,
                "max_total_results": 20 * len(handles),
                "actor": "apify/instagram-scraper",
                "expected_upper_usd": str(Decimal(20 * len(handles)) * Decimal("0.0023")),
                "proposed_ceiling_usd": "0.55",
                "gate": "schema/live-price validation and separately approved exact input; charge overlapping results conservatively; skip if cached posts suffice",
            },
            {
                "stage": "media_proof_after_owner_review",
                "max_images": 4,
                "max_image_bytes_each": 2_000_000,
                "max_videos": 2,
                "max_video_bytes_each": 20_000_000,
                "maximum_total_bytes": 48_000_000,
                "transcription": False,
                "provider_cost_usd": "0",
                "gate": "reuse cached audit images first; exact fresh URL+public owner+hash; no claim/speaker promotion",
            },
        ],
        "accounting": {
            "overnight_cap_usd": "120",
            "settled_explore_usd": "2.83650",
            "explore_reservations_usd": "0",
            "other_lane_settled_and_reserved_usd": None,
            "remaining_night_cap_usd": None,
            "maximum_proposed_incremental_reservations_usd": "0.73",
            "reservation_created": False,
            "price_source": "tmp/explore/source-audit/live-actor-prices.json",
            "price_observed_at": "2026-10-09; must refresh effective event prices before launch",
        },
        "stop_conditions": [
            "No launch without collector-owned exact authorization and root-reconciled cumulative settled+reserved accounting.",
            "Durable per-run reservation and idempotent input authorization before launch; ambiguous launch is recovered, never repeated blindly.",
            "Stop at each item/charge/time/byte ceiling, private or mismatched owner/local role, stale anchor, ambiguous identity, missing/expired media, or conflicting evidence.",
            "No additional platforms, comments, follower lists, about-account, date-filter, transcription, model calls or subscriptions.",
            "Retain all qualification/discovery overflow; no complete 7/14/30-day or six-month history claim from latest/bounded posts.",
            "Deduplicate platform/handle and platform/post-ID; preserve observed profile, actual publisher, requested entity, about/depicts/speaker as separate edges.",
        ],
        "historical_collection": {
            "candidate_profiles": 18,
            "organization_profiles": 15,
            "receipt": "data/evidence/top10_collection_receipt.json",
            "selection_rule": "v1; never relabel as v2 selected",
        },
    }


def public_url(value: str | None) -> str | None:
    if not value:
        return None
    url = urlparse(value)
    return (
        value
        if url.scheme in ("https", "http")
        and url.hostname
        and not (url.username or url.password or url.query or url.fragment)
        else None
    )


def render_viewer(
    rows: list[dict],
    lists: list[dict],
    summary: list[dict],
    selection: dict,
    sampled: list[dict],
) -> str:
    sampled_keys = {p["candidate_key"] for p in sampled}
    profiles = {p["candidate_key"]: p for p in sampled}
    selected = set(selection["qualified_keys"])
    payload = {
        "summary": summary,
        "candidates": [
            {
                "key": r["candidate"]["key"],
                "city": r["city"],
                "cityRank": r["candidate"]["city_rank"],
                "name": r["name"],
                "list": r["list_name"],
                "position": r["candidate"]["position"],
                "old": r["old"],
                **state(r),
                "change": r["change_kind"],
                "why": r["change_explanation"],
                "eligible": r["candidate"]["eligible"],
                "kind": r["candidate"]["eligibility_kind"],
                "collected": r["candidate"]["key"] in sampled_keys,
                "selected": r["candidate"]["key"] in selected,
                "historyClear": r["candidate"]["historical_identity_clear"],
                "followers": r["candidate"]["followers"],
                "sampledProfile": {
                    "handle": profiles[r["candidate"]["key"]]["handle"],
                    "observedFollowers": profiles[r["candidate"]["key"]]["followers"],
                    "observedAt": profiles[r["candidate"]["key"]]["observed_at"],
                }
                if r["candidate"]["key"] in profiles
                else None,
                "source": public_url(r["evidence"].get("source_url")),
                "historicalSources": sorted(
                    {
                        url
                        for s in (r["evidence"].get("historical_sources") or [])
                        + (r["evidence"].get("mandate_sources") or [])
                        if (url := public_url(s.get("source_url"))) is not None
                    }
                ),
                "anchors": [public_url(s.get("source_url")) for s in r["reviewed_sources"]],
                "gaps": r["gaps"],
            }
            for r in rows
        ],
        "lists": [
            {
                "key": r["key"],
                "city": r["city"],
                "cityRank": r["city_rank"],
                "name": r["name"],
                "qualified": r["qualified"],
                "score": r["priority"]["score"],
                "oldScore": r["old_priority"]["score"],
                "oldComponents": r["old_priority"]["components"],
                "components": r["priority"]["components"],
                "reasons": r["priority"]["reasons"],
                "verified": r["verified_account"],
                "source": public_url(r["priority"]["sources"]["current_list"]),
            }
            for r in lists
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return Path(__file__).with_name("relevance_viewer.html").read_text().replace("/*__DATA__*/", encoded)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(os.environ.get("CZLAKE_PROJECT") or Path(__file__).resolve().parents[4]))
    parser.add_argument("--as-of", default="2026-10-09T03:00:00+02:00")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    root = args.project.resolve()
    output = (args.output_dir or root / "tmp/prioritization/relevance-v2").resolve()
    if not output.is_relative_to(root / "tmp") or output.is_relative_to(root / "tmp/explore"):
        raise ValueError("Use a separate project tmp output; source evidence/open viewer is read-only")
    as_of = datetime.fromisoformat(args.as_of)
    if as_of.tzinfo is None:
        raise ValueError("Timezone-aware as-of required")
    hashes = {p: digest(root / p) for p in INPUTS}
    sources = {p: json.loads((root / p).read_text()) for p in INPUTS}
    rows, changes = recompute(sources[INPUTS[0]], as_of)
    lists = rank_lists(sources["data/evidence/ten_city_examples.json"]["lists"], rows, as_of)
    summary = []
    for rank in range(1, 11):
        members = [r for r in rows if r["candidate"]["city_rank"] == rank]
        summary.append(
            {
                "city": members[0]["city"],
                "city_rank": rank,
                "valid": sum(r["candidate"]["eligible"] for r in members),
                "old_qualified": sum(r["old"]["qualified"] for r in members),
                "current_leader_ablation": sum(
                    r["old"]["qualified"] and bool(set(r["old"]["reasons"]) - {"list_leader"})
                    for r in members
                ),
                "new_qualified": sum(r["qualified"] for r in members),
                "removed": sum(r["change_kind"] == "removed" for r in members),
                "added": sum(r["change_kind"] == "added" for r in members),
                "old_protected": sum(r["old"]["protected"] for r in members),
                "new_protected": sum(r["protected"] for r in members),
                "strict_electoral_only": sum(
                    r["candidate"]["eligible"]
                    and any(
                        r["components"][k] is not None and r["components"][k] >= 1
                        for k in ("office", "party_contender", "local_votes")
                    )
                    for r in members
                ),
                "qualified_lists": sum(r["qualified"] and r["city_rank"] == rank for r in lists),
            }
        )
    selection = select_thirty(rows)
    if any(r["new_qualified"] < 30 for r in summary) or any(v < 30 for v in selection["per_city"].values()):
        raise ValueError("Real city shortfall; do not lower thresholds or pad with discovery")
    proposal = collection_manifest(rows, lists, selection, sources, as_of)
    rule = {
        "version": RULE_VERSION,
        "status": "revised_proposal_not_deployed",
        "formula": "eligible AND max(O,M,V,R,A)>=1; capped at 2",
        "disabled_qualification_channels": ["prior_leader", "list_leader"],
        "channels": {
            "O": "max(1.5*reviewed_current_office,identity_clear_elected_mandate); election terms are historical verification leads",
            "M": "positions1-3 only: max(exact_local22_share/.10,associated_national25_alliance_share/.05,associated_city25_alliance_share/.10); overlap is context, not coalition continuity",
            "V": "identity-clear same-city max(3/2022_rank,own_list_vote_lift/1.25); whole-list voting limits interpretation",
            "R": "max(F/10000,F/(.10*city_population)); one fresh public independently anchored unique account; max platforms, never sum",
            "A": "reviewed current local role and independently originated substantive same-city action within365days; review<=30days; finance optional",
        },
        "newcomer_assumption": "Retain independently evidenced public reach/local action; optional clarification pending. Strict electoral-only comparison is not adopted.",
        "leadership": "current/prior leadership or founder role alone establishes discovery context, never qualification/protection",
        "protected": "qualified AND M<1/unknown AND (R>=1 OR A>=1 OR non-main-list leader/reviewed founder with an independent strong signal)",
        "list_relevance": "independent max(local22/.10,national25-associated-alliance/.05,city25-associated-alliance/.10,reviewed organization reach,reviewed organization activity)>=1; valid-list discovery alone is a queue",
        "as_of": args.as_of,
        "sources_sha256": hashes,
        "implementation_sha256": {
            str(p.relative_to(Path(__file__).parents[1])): digest(p)
            for p in (
                Path(__file__),
                Path(__file__).with_name("relevance_viewer.html"),
                Path(__file__).with_name("prioritize.py"),
                Path(__file__).parents[1] / "priority.py",
            )
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, value in {
        "rule": rule,
        "universe": rows,
        "lists": lists,
        "changes": changes,
        "summary": summary,
        "selection": selection,
        "collection-manifest": proposal,
    }.items():
        (output / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    (output / "index.html").write_text(
        render_viewer(
            rows,
            lists,
            summary,
            selection,
            sources["data/evidence/top10_profile_review.json"]["profiles"],
        )
    )
    if hashes != {p: digest(root / p) for p in INPUTS}:
        raise ValueError("Source changed while recomputing; outputs must be reviewed/replayed")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
