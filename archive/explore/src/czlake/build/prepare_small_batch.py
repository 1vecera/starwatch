"""Prepare one held, ranked Instagram-profile sample from cached public evidence.

Qualification is retained separately from account availability and this small
technical sample. No API calls, account promotion or ranking-lake writes occur.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal

from .. import apify_run
from .. import lakehouse as lh
from ..land import now_iso
from ..paths import DATA, DOCS, PROJECT
from ..priority import Candidate, qualify, schedule
from ..textnorm import normkey
from .discover_accounts import completed_people

PROFILE_PRICE = Decimal("0.0023")
SAMPLE_BUDGET = Decimal("0.046")  # At most twenty profiles; not a qualification cap.
RUN_CAP = Decimal("0.07")
CITY_CONTEXT = {
    "Praha": ("prah",), "Brno": ("brn",), "Ostrava": ("ostrav",),
    "Plzeň": ("plzen",), "Liberec": ("liberec", "liberci", "libereck"),
    "Olomouc": ("olomouc",), "České Budějovice": ("budejovic",),
    "Hradec Králové": ("hradec", "hradeck",), "Pardubice": ("pardubic",),
    "Ústí nad Labem": ("usti nad labem", "usteck"),
}


def identity_evidence(profile: dict, owners: dict, hits: list[dict]) -> dict | None:
    """Choose cached identity evidence; never mistake query context for an anchor."""
    handle = profile["handle"].lower()
    if (profile["possible_duplicates"] != 0 or profile["inherited_status"] != "accepted"
            or owners.get(handle, set()) != {profile["entity_id"]}
            or not re.fullmatch(r"[a-z0-9_.]+", handle)):
        return None
    sources = set((profile["sources"] or "").split(","))
    if sources.intersection({"wikidata", "offices"}):
        qids = re.findall(r"\bQ[0-9]+\b", profile["match_basis"] or "")
        return {"kind": "curated_cached_anchor", "basis": profile["match_basis"],
                "source_urls": ["https://www.wikidata.org/wiki/" + qid for qid in qids],
                "profile_url": profile["profile_url"],
                "limitation": "Retained anchor; profile ownership and current public status still need confirmation."}
    name = normkey(profile["entity_name"]) or ""
    for hit in hits:
        if hit["person_id"] != profile["entity_id"] or (hit["handle"] or "").lower() != handle:
            continue
        title = normkey(hit["title"]) or ""
        text = title + " " + (normkey(hit["description"]) or "")
        if name and name in text and any(city in text for city in CITY_CONTEXT[profile["city"]]):
            return {"kind": "cached_profile_name_and_local_context", "profile_url": profile["profile_url"],
                    "source_url": hit["url"], "title": hit["title"], "description": hit["description"],
                    "apify_run_id": hit["apify_run_id"], "result_rank": hit["rank"],
                    "limitation": "Cached SERP profile evidence; unverified ownership, office and follower counts."}
    return None


def prepare() -> dict:
    path = PROJECT / "tmp/prioritization/universe.json"
    snapshot = path.read_bytes()
    records = json.loads(snapshot)
    decisions = {r["candidate"]["key"]: qualify(Candidate(**r["candidate"])) for r in records}
    if any(d.qualified != r["qualified"] or d.protected != r["protected"] or abs(d.score - r["score"]) > 1e-10
           for r in records for d in [decisions[r["candidate"]["key"]]]):
        raise ValueError("Saved ranking decisions differ from the integrated reference")
    con = lh.duck()
    official = {r[0] for r in con.sql("select candidacy_id from marts.active_city_2026_candidates where eligible_current_ballot").fetchall()}
    if any(r["candidate"]["key"] not in official for r in records
           if r["qualified"] and r["candidate"]["eligibility_kind"] == "current_candidacy"):
        raise ValueError("Ranking is outside current eligible official candidacies")
    profiles = con.sql("select * from marts.active_profile_candidates where entity_kind='person'").to_arrow_table().to_pylist()
    owners = {}
    for handle, person in con.sql("select lower(handle),person_id from core.account where platform='instagram' and status='accepted'").fetchall():
        owners.setdefault(handle, set()).add(person)
    hits = con.sql("select * from staging.serp_social_hits where platform='instagram' order by apify_run_id,rank,url").to_arrow_table().to_pylist()
    evidence, accounts = {}, {}
    for profile in sorted(profiles, key=lambda p: (p["entity_id"], p["handle"])):
        anchor = identity_evidence(profile, owners, hits)
        if anchor:
            key = profile["entity_id"]
            tier = 0 if anchor["kind"] == "curated_cached_anchor" else 1
            if key not in accounts or (tier, profile["handle"]) < accounts[key][0]:
                accounts[key] = ((tier, profile["handle"]), profile)
                evidence[key] = anchor
    ready = [r for r in records if r["qualified"] and r["person_id"] in accounts]
    selected = schedule([decisions[r["candidate"]["key"]] for r in ready], per_city=2,
                        budget=SAMPLE_BUDGET, costs={r["candidate"]["key"]: PROFILE_PRICE for r in ready})
    by_key = {r["candidate"]["key"]: r for r in records}
    cards = []
    for decision in selected.selected:
        r = by_key[decision.candidate.key]
        profile = accounts[r["person_id"]][1]
        cards.append({"name": r["name"], "city": r["city"], "person_id": r["person_id"],
                      "eligibility_kind": decision.candidate.eligibility_kind, "key": decision.candidate.key,
                      "handle": profile["handle"], "profile_url": profile["profile_url"],
                      "list_name": r["list_name"], "position": decision.candidate.position,
                      "score": decision.score, "winning_reason": decision.winner, "reasons": decision.reasons,
                      "components": decision.components, "protected": decision.protected,
                      "identity_evidence": evidence[r["person_id"]], "official_evidence": r["evidence"],
                      "identity_status": "profile_confirmation_pending", "gaps": r["gaps"]})
    handles = list(dict.fromkeys(card["handle"] for card in cards))
    if len(handles) > 20:
        raise ValueError("Small technical sample exceeded twenty profiles")
    spend = sum((Decimal(row["usage_total_usd"] or "0") for row in apify_run.ledger_rows()), Decimal(0))
    reserved = sum((Decimal(str(r["max"])) for r in apify_run._state()["reservations"].values()), Decimal(0))
    headroom = Decimal(str(apify_run.CAP_USD)) - spend - reserved
    if RUN_CAP > headroom:
        raise ValueError("Proposed cap exceeds inherited cumulative headroom")
    qualified = [r for r in records if r["qualified"]]
    completed = completed_people(con)
    qualifying_persons = {r["person_id"] for r in qualified
                          if r["candidate"]["eligibility_kind"] == "current_candidacy"}
    keys = {card["key"] for card in cards}
    output = {"observed_at": now_iso(), "status": "held_preparation_only_no_spend_authorization",
              "ranking_sha256": hashlib.sha256(snapshot).hexdigest(), "city_scope": "population_rank<=10",
              "qualified_candidacies": sum(r["candidate"]["eligibility_kind"] == "current_candidacy" for r in qualified),
              "qualified_local_roles": sum(r["candidate"]["eligibility_kind"] == "reviewed_local_role" for r in qualified),
              "qualified_total": len(qualified), "cached_identity_ready": len(ready),
              "qualified_person_queries_completed": len(qualifying_persons & completed),
              "qualified_person_queries_remaining": len(qualifying_persons - completed),
              "identity_or_account_gap": len(qualified)-len(ready), "selected_entities": len(cards),
              "selected_profiles": len(handles), "qualification_overflow": len(qualified)-len(cards),
              "ready_overflow": len(ready)-len(cards), "protected_slots_requested": selected.protected_slots_requested,
              "protected_slots_filled": selected.protected_slots_filled, "selection_per_city_proposal": 2,
              "estimated_usd": str(PROFILE_PRICE*len(handles)), "max_total_charge_usd_proposal": str(RUN_CAP),
              "spent_usd": str(spend), "reserved_usd": str(reserved), "headroom_usd": str(headroom),
              "headroom_after_proposed_cap_usd": str(headroom-RUN_CAP),
              "hold_present": (DATA/"paid_launch_hold.json").exists(), "actor_runs": 1 if handles else 0,
              "discovery_queries_for_this_batch": 0, "new_paid_model_calls": 0,
              "wall_time_allowance": "1–3 minutes plus queue/retry time; observed 9-profile run took 22.429 seconds, 2 profiles 15.665 seconds",
              "input": {"usernames": handles, "includeAboutSection": False},
              "actor": "apify/instagram-profile-scraper", "targets": cards,
              "overflow_keys": [r["candidate"]["key"] for r in qualified if r["candidate"]["key"] not in keys]}
    target = DATA/"inputs/top10_small_ranked_profile_batch.json"
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2))
    document = DOCS/"top10-batch-plan.md"
    note = ["", f"## Small ranked profile-first batch — {output['observed_at']}", "",
            f"**Held proposal:** {len(handles)} profiles in one Actor run, estimated **${output['estimated_usd']}**, proposed hard run cap **${RUN_CAP}**. Exact input and complete source cards: `data/inputs/top10_small_ranked_profile_batch.json`.", "",
            f"Qualification stays {len(qualified)} entities ({output['qualified_candidacies']} ballot candidacies, {output['qualified_local_roles']} reviewed noncandidate local roles). Cached identity-ready pool {len(ready)}; account/identity gaps {output['identity_or_account_gap']}; technical sample {len(cards)} entities; ready overflow {output['ready_overflow']}; full qualification overflow {output['qualification_overflow']}. At most two selections per city is this small sample's proposed capacity, not Daniel's research/person cap. Protected slots requested/filled {selected.protected_slots_requested}/{selected.protected_slots_filled}; cities lacking an anchored protected account remain gaps, not exclusions from qualification.", "",
            f"Inherited cumulative cap: ${spend} actual + ${reserved} reserved; ${headroom} headroom under $20. The proposed cap would leave ${headroom-RUN_CAP}; no reservation or charge was created. Paid hold is still present. About-account and paid post/model add-ons stay off; latestPosts are bundled recent samples, not guaranteed twelve posts or complete six-month histories. Local dates and post IDs must be filtered/deduplicated after identity confirmation.", "",
            "Timing allowance: 1–3 minutes for one small profile run, plus unbounded queue/retry time. Prior 9- and 2-profile runs took 22.429 and 15.665 seconds; this is observed small-run latency, not a linear throughput guarantee. Both prior caps ($0.05/$0.02) were accepted, so the $0.07 proposal is consistent with profile-Actor evidence. The Google Actor's $0.50 minimum cap does not apply to these observed profile runs.", "",
            "Curated anchors and exact-name/local-context profile results are cached evidence for fetching the profile. They are not fresh verification of ownership, office or follower counts. Ambiguous clusters, shared accepted handles, name-only results and unconfirmed links are deferred. No follower count from a search snippet enters qualification. Public-local roles stay distinct from ballot candidacies; no private donor/business-owner/fame route is admitted.", "",
            "| City | Person | Handle | Score / winning reason | Protected | Cached identity evidence |",
            "| --- | --- | --- | --- | --- | --- |"]
    for card in cards:
        note.append(f"| {card['city']} | {card['name']} | `{card['handle']}` | {card['score']:.3f} / {card['winning_reason']} | {'yes' if card['protected'] else 'no'} | {card['identity_evidence']['kind']} |")
    previous = document.read_text()
    start = previous.find("\n## Small ranked profile-first batch")
    following = previous.find("\n## ", start + 1) if start >= 0 else -1
    document.write_text((previous[:start] if start >= 0 else previous)+"\n".join(note)+"\n"
                        +(previous[following:] if following >= 0 else ""))
    print(json.dumps({key: value for key,value in output.items() if key not in {"targets","overflow_keys"}},ensure_ascii=False))
    return output


if __name__ == "__main__":
    prepare()
