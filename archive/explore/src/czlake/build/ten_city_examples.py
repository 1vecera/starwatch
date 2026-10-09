"""Local ten-city examples and a separate official list research queue."""
from __future__ import annotations

import json

from ..land import now_iso
from ..paths import DATA, DOCS, PROJECT


def list_priority(record: dict) -> dict:
    """List evidence only: historical local share, alliance context, discovery."""
    evidence = record["evidence"]
    shares = {
        "exact_code_local_2022": evidence.get("local22_share"),
        "associated_national_alliance_2025": evidence.get("national_alliance_share"),
        "associated_city_alliance_2025": evidence.get("city_alliance_share"),
    }
    components = {
        "local_list_result": None if shares["exact_code_local_2022"] is None else min(2, shares["exact_code_local_2022"] / .10),
        "national_alliance_context": None if shares["associated_national_alliance_2025"] is None else min(2, shares["associated_national_alliance_2025"] / .05),
        "city_alliance_context": None if shares["associated_city_alliance_2025"] is None else min(2, shares["associated_city_alliance_2025"] / .10),
        "current_valid_list_discovery": 1.,
    }
    winner = max(components, key=lambda key: components[key] if components[key] is not None else -1)
    return {"score": components[winner], "winner": winner, "components": components, "shares": shares,
            "protected_discovery": not any(value is not None and value >= 1 for key, value in components.items() if key != "current_valid_list_discovery"),
            "sources": {"current_list": evidence["source_url"], "local_2022": evidence.get("local22_sources"), "alliance_2025": evidence.get("party_sources")},
            "limitation": "Separate preparation mapping, not a person score, constituent-party votes, coalition continuity or election forecast."}


def build() -> dict:
    refreshed = DATA / "evidence/top10_prioritization_refreshed.json"
    universe_path = refreshed if refreshed.exists() else PROJECT / "tmp/prioritization/universe.json"
    universe = json.loads(universe_path.read_text())
    batch = json.loads((DATA / "inputs/top10_small_ranked_profile_batch.json").read_text())
    first = {}
    for target in batch["targets"]:
        first.setdefault(target["city"], target)
    review_path = DATA / "evidence/top10_profile_review.json"
    review = json.loads(review_path.read_text()) if review_path.exists() else {"profiles": []}
    metrics = {r["handle"]: r for r in review["profiles"]}
    role_path = DATA / "evidence/top10_public_identity_review.json"
    public = json.loads(role_path.read_text()) if role_path.exists() else {"candidates": {}, "lists": {}}
    organization_path = DATA / "evidence/top10_organization_profile_review.json"
    organization_review = json.loads(organization_path.read_text()) if organization_path.exists() else {"profiles": []}
    organization_metrics = {p.get("list_key"): p for p in organization_review["profiles"]}
    receipt_path = DATA / "evidence/top10_collection_receipt.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    lists = []
    for record in universe:
        c = record["candidate"]
        if not c["eligible"] or c["position"] != 1:
            continue
        e = record["evidence"]
        lists.append({"key": f"kv2026:{c['city_code']}:{c['list_no']}", "city": record["city"], "city_rank": c["city_rank"],
                      "municipality_code": c["city_code"], "list_no": c["list_no"], "name": record["list_name"],
                      "leader": record["name"], "leader_position": 1, "current_source_date": "2026-10-07",
                      "observed_at": e["fetched_at"], "member_party_code": e["member_party_code"],
                      "priority": list_priority(record), "public_identity_review": public["lists"].get(f"kv2026:{c['city_code']}:{c['list_no']}"),
                      "social_metrics": organization_metrics.get(f"kv2026:{c['city_code']}:{c['list_no']}")})
    rows = []
    cities = sorted({(r["candidate"]["city_rank"], r["city"]) for r in universe})
    for rank, city in cities:
        selected = first.get(city)
        candidates = [r for r in universe if r["city"] == city and r["qualified"]]
        r = next((r for r in candidates if selected and r["candidate"]["key"] == selected["key"]), None)
        if r is None:
            r = min(candidates, key=lambda r: (-r["score"], r["candidate"]["position"], r["name"]))
        c, e = r["candidate"], r["evidence"]
        def share(p: dict, key: str) -> float:
            value = p["priority"]["shares"][key]
            return -1 if value is None else value
        party = min([p for p in lists if p["city"] == city], key=lambda p: (-p["priority"]["score"], -share(p, "exact_code_local_2022"), -share(p, "associated_city_alliance_2025"), int(p["list_no"])))
        sample = metrics.get(selected["handle"]) if selected else None
        rows.append({"city": city, "city_rank": rank, "candidate": {
            "name": r["name"], "key": c["key"], "person_id": r["person_id"], "eligibility_kind": c["eligibility_kind"],
            "list_name": r["list_name"], "list_no": c["list_no"], "position": c["position"], "validity": e["validity"],
            "occupation_as_registered": e["occupation"], "residence_as_registered": e["residence"],
            "identity_locality_source": e["source_url"], "source_date": "2026-10-07", "observed_at": e["fetched_at"],
            "score": r["score"], "winner": r["winner"], "reasons": r["reasons"], "components": r["components"],
            "historical_sources": e.get("historical_sources"), "party_sources": e.get("party_sources"), "protected": r["protected"],
            "mandate_sources": e.get("mandate_sources"), "party_context": {k: e.get(k) for k in ["local22_share", "national_alliance_share", "city_alliance_share"]},
            "cached_account": selected["identity_evidence"] if selected else None, "sample_review": sample,
            "public_identity_review": public["candidates"].get(c["key"]), "gaps": r["gaps"],
            "scheduled_because": "Protected independent leadership/history path filled before regular priority slots; cached identity anchor supports this bounded fetch." if selected and r["protected"] else "Max/OR research qualification plus reviewed cached profile anchor; city round-robin regular slot." if selected else "Official valid list leader and strong party context; free public identity research first. Social account gap remains.",
        }, "party_list": party, "organization_accounts": [p for p in organization_review["profiles"] if p.get("city") == city],
            "organization_account_gap": public.get("local_list_gaps", {}).get(city)})
    out = {"observed_at": now_iso(), "status": "local_draft_refreshed" if metrics else "local_cached_baseline",
           "qualification": {"valid_candidacies": sum(r["candidate"]["eligible"] and r["candidate"]["eligibility_kind"] == "current_candidacy" for r in universe), "qualified": sum(r["qualified"] for r in universe), "protected": sum(r["protected"] for r in universe), "reviewed_noncandidate_roles": sum(r["candidate"]["eligibility_kind"] == "reviewed_local_role" for r in universe), "independently_attributed_candidate_metrics": sum(r["candidate"]["followers"] is not None for r in universe)},
           "sample": {"selected_profiles": 18, "cities": 9, "protected_slots": 3, "overflow": 497, "ready_overflow": 22},
           "list_mapping": "max/OR of exact-code local22 share/.10, associated national25 alliance share/.05, associated city25 alliance share/.10 and valid-list discovery=1; each capped at 2. Unknowns stay null. Ties use local22, then city25 context, then list number. All 127 lists retained; 20% protected discovery and 5% missing-evidence allocations apply to future bounded schedules, independent of persons.",
           "organization_sample": {"profiles": len(organization_review["profiles"]), "cities": len({p['city'] for p in organization_review['profiles'] if p.get('city')}), "independently_anchored_accounts": sum(p.get("followers_attributed_to_entity") is not None for p in organization_review['profiles']), "unknown_list_account_associations": sum(p.get("followers_attributed_to_entity") is None for p in organization_review['profiles'])},
           "collection_receipt": receipt,
           "cities": rows, "lists": lists, "source_universe": str(universe_path)}
    destination = DATA / "evidence/ten_city_examples.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not (destination.parent / "ten_city_examples_baseline.json").exists():
        (destination.parent / "ten_city_examples_baseline.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    destination.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    text = ["# Ten-city candidate and separate list examples", "", f"Observed {out['observed_at']}; local draft. Ten official city examples; the first candidate social batch covers **nine cities**, with Ústí's personal social missing. Candidate qualification remains max/OR; all unknowns and full overflow remain. These examples illustrate the research queue, not electoral predictions.", "", "List priority is independently calculated from official list/alliance evidence: " + out["list_mapping"], "", "| City | Prioritized candidate / valid 2026 position | Winning signal / why scheduled | Separate list example / official basis | Public profile evidence |", "| --- | --- | --- | --- | --- |"]
    for row in rows:
        c, p = row["candidate"], row["party_list"]
        m = c["sample_review"]
        social = f"{m['handle']}: {m.get('followers')} observed handle followers; {'independent anchor confirmed' if m.get('followers_attributed_to_entity') is not None else 'entity attribution unknown'}; {m.get('in_window_posts', 0)} observed recent posts" if m else "profile pending" if c["cached_account"] else "personal social missing; public local identity reviewed" if c["public_identity_review"] else "social missing; public identity review first"
        shares = p["priority"]["shares"]
        basis = f"exact-code 2022 local {shares['exact_code_local_2022']:.2%}" if shares["exact_code_local_2022"] is not None else "prior associated alliance context; local list history unknown"
        text.append(f"| {row['city']} | {c['name']}, #{c['position']} on {c['list_name']} | {c['score']:.3f} / {c['winner']}; {'protected slot' if c['protected'] else 'regular city slot' if c['cached_account'] else 'identity research'} | {p['name']} (list {p['list_no']}); score {p['priority']['score']:.3f} / {p['priority']['winner']}; {basis} | {social} |")
    text += ["", "Current identity/locality, registered occupations and positions: [ČSÚ registry, 7 October 2026](https://volby.gov.cz/opendata/kv2026/KV2026reg20261007_csv.zip), cached 8 October. Registered occupation is a dated claim, not current-office verification. Historical [2022 local registry/results](https://volby.gov.cz/opendata/kv2022/KV2022reg20260328_csv.zip) and [2025 parliamentary registry](https://volby.gov.cz/opendata/ps2025/PS2025reg20251005_csv.zip) provide recorded results and party/alliance context. Exact URLs, cached observation dates, raw components, historical rows and account anchors are retained in data/evidence/ten_city_examples.json.", "", "No national, regional, district, youth or personal account becomes a city-list account through name similarity. Each local list requires its own public anchor and current city-list relationship; profile absence remains unknown. Candidate follower counts are global public counts, never local voters, votes or support. A profile's recent posts provide a variable shallow sample, not six-month completeness. Current office and substantive action remain unknown until independently reviewed. No real noncandidate role has been admitted.", ""]
    text += ["Organization accounts are a separate evidence pool from the ranked list examples above. Fifteen public profiles sampled in eight cities; eleven independently linked by current local political websites, four associations pending. Plzeň and České Budějovice lack measured city-list organization profiles. Counts below are observed globally at the stated public account, never candidate reach or local votes.", "", "| City | Organization account evidence / observed followers | Relationship to ranked list example |", "| --- | --- | --- |"]
    for row in rows:
        descriptions = []
        for p in row["organization_accounts"]:
            proof = p.get("identity_evidence")
            status = f"[local political anchor]({proof['source_url']})" if proof else "independent list anchor unknown"
            descriptions.append(f"[{p['handle']}]({p['profile_url']}): {p['followers']} ({status})")
        account_text = "; ".join(descriptions) if descriptions else row["organization_account_gap"] or "city-list account and metrics unknown"
        matched = row["party_list"]["social_metrics"]
        relation = "exact organization/list independently anchored" if matched and matched.get("followers_attributed_to_entity") is not None else "sampled handle matches list; independent anchor pending" if matched else "ranked example's account unknown; sampled organizations have separate list keys"
        text.append(f"| {row['city']} | {account_text} | {relation} |")
    text += ["", "Ústí candidate identity: [city council roster](https://www.usti.cz/cz/uredni-portal/sprava-mesta/mesto-jeho-organy/zastupitelstvo-mesta/) lists Radim Bzura; [SPOLU PRO ÚSTÍ](https://www.spoluprousti.cz/) confirms his current list leadership. His personal social account stays missing. [JEDNO ÚSTÍ's current candidate page](https://www.jednousti.cz/tomas-vohryzka-primator) independently identifies Tomáš Vohryzka; the coalition's account is separately attributed to the organization. No historical identity cluster was merged.", ""]
    if receipt:
        text += [f"Settled collection: first run $0.04140 for 18 public profiles / 204 in-window unique posts in nine cities; organization run $0.03450 for 15 public profiles / 178 in-window unique posts in eight cities. Combined 382 retained account/run observations represent 363 unique posts, including 19 shared IDs. Owner checks attribute 135 unique publications to independently anchored accounts: 34 candidate-account posts and 101 organization-account posts. Appearing in a profile bundle alone does not establish publication ownership; all associations and unknowns remain. No activity score was promoted. Total exploration bill **${receipt['settled_actual_usd']}**, reservations **${receipt['reserved_usd']}**, original cap $20, remaining headroom ${receipt['headroom_usd']}; no active owned run or extra paid engine.", "", "All 515 qualifiers / 65 protected remain; candidate sample overflow is 497, including 22 identity-ready deferred candidates. All 127 list keys and 112 organization-sample overflow keys remain. Candidate protected allocation filled 3/3; organization discovery allocation filled 7/7. Four candidate-account and eleven organization-account anchors are confirmed; fourteen candidate and four organization associations remain unknown. [Authorization, receipt and handoff](authorized-evidence.md) retain the exact inputs, scope and billing evidence.", ""]
    for row in rows:
        c, p = row["candidate"], row["party_list"]
        identity = c["public_identity_review"] or {}
        party_identity = p["public_identity_review"] or {}
        signal = ""
        if c["winner"] == "party_contender":
            signal = " Prior associated 2025 national/city alliance context: " + "/".join(f"{c['party_context'][key]:.2%}" if c['party_context'][key] is not None else "unknown" for key in ["national_alliance_share", "city_alliance_share"]) + "; contextual thresholds 5%/10%, capped at 2 for current top-three positions."
        elif c["winner"] == "local_votes":
            signal = " Historical local exposure: " + "; ".join(f"2022 {h['pref_votes']} recorded candidate votes, city rank {h['vote_rank']}, own-list lift {h['vote_lift']:.3f}" for h in c["historical_sources"] or [] if h.get("vote_lift") is not None) + "."
        elif c["winner"] == "office":
            signal = " Winning office channel is a recorded historical elected mandate, not verified continuing office."
        text += [f"**{row['city']}: {c['name']} and {p['name']}.** {c['scheduled_because']} Candidate locality: {c['residence_as_registered']}; registered role: {c['occupation_as_registered']}. All qualifying channels: {', '.join(c['reasons'])}.{signal} Current registry source {c['source_date']}, cached {c['observed_at']}. List leader {p['leader']} at #1 is separately established by that registry. Ranked list's account review: {party_identity.get('adjudication', 'unknown')}. Candidate public identity/account review: {identity.get('adjudication', 'unknown')}. Current-office and action score channels remain unknown; exact source observations and account gaps are in the machine record.", ""]
    (DOCS / "ten-city-examples.md").write_text("\n".join(text))
    return {"cities": len(rows), "lists": len(lists), "social_cities": len({t['city'] for t in batch['targets']}), "path": str(destination)}


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False))
