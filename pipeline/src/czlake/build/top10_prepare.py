"""Prepare scoped official marts, identity-review candidates and held profile batches.

This pass only reuses local data. It never schedules paid research or substitutes
an arbitrary top-K for the independent prioritization worker's qualifying rule.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re

import pyarrow as pa

from .. import lakehouse as lh
from ..land import now_iso
from ..paths import DATA, DOCS, PROJECT
from ..scope import TOP_CITY_RANK
from ..textnorm import normkey


def prepare() -> dict:
    con = lh.duck()
    counts = {}
    for source, target in [("city_profile", "active_city_profile"), ("city_2026_contenders", "active_city_2026_contenders")]:
        table = lh.tbl(con.sql(f"select * from marts.{source} where population_rank<={TOP_CITY_RANK}"))
        lh.write("marts", target, table)
        counts[target] = table.num_rows
    active_candidates = lh.tbl(con.sql(f"""
        select c.*, b.candidacy_id, b.validity as ballot_validity, b.validity='A' as eligible_current_ballot
        from marts.city_2026_candidates c join core.candidacy b
          on b.election_id='kv2026' and b.unit_code=c.municipality_code
           and b.list_no=c.list_no and b.list_position=c.list_position
        where c.population_rank<={TOP_CITY_RANK}
    """))
    lh.write("marts", "active_city_2026_candidates", active_candidates)
    counts["active_city_2026_candidates"] = active_candidates.num_rows
    con.register("active_candidates", active_candidates)
    candidates = con.sql("""
        select c.person_id as entity_id, c.first_name || ' ' || c.last_name as entity_name,
               c.city, c.municipality_code, c.population_rank, c.list_no, c.list_name, c.list_position,
               a.account_id, a.handle, a.url as discovery_url, a.status as inherited_status, a.sources,
               a.match_basis, p.possible_duplicates
        from active_candidates c join core.account a using(person_id)
        join core.person p using(person_id)
        where c.eligible_current_ballot and a.platform='instagram' and a.status<>'rejected'
        order by c.population_rank, c.list_no, c.list_position, a.handle
    """).to_arrow_table().to_pylist()
    for row in candidates:
        row.update(entity_kind="person", identity_status="needs_profile_and_anchor_check",
                   candidate_basis="retained person-account evidence; not a new verification")
    org_hits = con.sql(f"""
        select entity_id, name as entity_name, city, municipality_code, population_rank, list_no,
               list_name, null::integer as list_position, handle, url as discovery_url, title, description,
               apify_run_id, rank
        from staging.local_discovery_hit where kind='lists' and population_rank<={TOP_CITY_RANK}
          and platform='instagram' and handle is not null
        order by population_rank, list_no, rank
    """).to_arrow_table().to_pylist()
    seen = set()
    for row in org_hits:
        key = (row["entity_id"], row["handle"].lower())
        if key in seen:
            continue
        seen.add(key)
        city = normkey(row["city"]) or ""
        title = normkey(row["title"]) or ""
        handle = (normkey(row["handle"]) or "").replace(" ", "")
        local_signal = bool(city) and (city in title or city.replace(" ", "") in handle)
        row.update(entity_kind="local_list", account_id=hashlib.md5(("instagram:" + row["handle"].lower()).encode()).hexdigest(),
                   inherited_status="unconfirmed", sources=f"apify:{row['apify_run_id']}#rank{row['rank']}",
                   match_basis="local-list search result; owner and locality require an anchor",
                   identity_status="needs_profile_and_anchor_check", possible_duplicates=None,
                   candidate_basis="city in profile title/handle" if local_signal else "locality unresolved; may be national or unrelated")
        row["local_signal"] = local_signal
        candidates.append(row)
    # Keep all associations while requesting a shared handle at most once.
    for row in candidates:
        row["handle"] = row["handle"].lower()
        row["profile_url"] = "https://www.instagram.com/" + row["handle"] + "/"
        row["platform"] = "instagram"
        row["observed_at"] = now_iso()
    lh.write("marts", "active_profile_candidates", pa.Table.from_pylist(candidates))
    eligible = [row for row in candidates if row["entity_kind"] == "person" or row["local_signal"]]
    handles = sorted({row["handle"] for row in eligible if re.fullmatch(r"[a-z0-9_.]+", row["handle"])})
    batches = []
    for start in range(0, len(handles), 50):
        chunk = handles[start:start + 50]
        batches.append({"actor": "apify/instagram-profile-scraper", "input": {"usernames": chunk, "includeAboutSection": False},
                        "profile_count": len(chunk), "estimated_usd": round(len(chunk) * 0.0023, 5),
                        "proposed_max_total_charge_usd": round(len(chunk) * 0.0023 * 1.2 + 0.01, 3),
                        "status": "held_proposal_requires_prioritized_target_intersection_and_spend_authorization"})
    cities = con.sql(f"select * from marts.city_profile where population_rank<={TOP_CITY_RANK} order by population_rank").to_arrow_table().to_pylist()
    summary = {"observed_at": now_iso(), "status": "preparation_only_paid_launches_held", "city_rank_limit": TOP_CITY_RANK,
               "population": sum(row["population"] for row in cities), "tables": counts,
               "distinct_candidate_persons": con.sql(f"select count(distinct person_id) from marts.city_2026_candidates where population_rank<={TOP_CITY_RANK}").fetchall()[0][0],
               "person_account_links": sum(row["entity_kind"] == "person" for row in candidates),
               "local_list_account_candidates": sum(row["entity_kind"] == "local_list" for row in candidates),
               "provisional_unique_profile_handles": len(handles), "profile_estimate_usd": round(len(handles) * 0.0023, 5),
                   "valid_candidacies": con.sql("select count(*) from active_candidates where eligible_current_ballot").fetchall()[0][0],
                   "person_cap": None, "selection_owner": "hos-rank; separate prioritize branch", "batches": batches}
    inputs = DATA / "inputs"
    inputs.mkdir(exist_ok=True)
    (DATA / "research_scope.json").write_text(json.dumps({"city_rank_limit": TOP_CITY_RANK, "cities": cities,
        "paid_launches_held": True, "larger_official_archive_preserved": True, "person_cap": None}, ensure_ascii=False, indent=2))
    (inputs / "top10_profile_first_proposal.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    columns = ["entity_kind", "entity_id", "entity_name", "city", "municipality_code", "population_rank", "list_no", "list_name",
               "list_position", "account_id", "handle", "profile_url", "discovery_url", "inherited_status", "identity_status",
               "sources", "match_basis", "candidate_basis", "possible_duplicates"]
    with (inputs / "top10_profile_candidates.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(candidates)
    lines = ["# Top-ten scope and held profile-first proposal", "", f"Observed {summary['observed_at']}. Daniel decided ten cities; no person-count cap or new spending is authorized. The larger official archive remains unchanged.", "",
             "| Rank | City | Population | Lists/leaders | Candidates |", "| ---: | --- | ---: | ---: | ---: |"]
    for row in cities:
        lines.append(f"| {row['population_rank']} | {row['city']} | {row['population']:,} | {row['n_lists_2026']} | {int(row['n_candidates_2026']):,} |")
    lines += ["", f"Total: **{summary['population']:,} people, {counts['active_city_2026_contenders']} lists/leaders, {counts['active_city_2026_candidates']:,} candidacy records, {summary['distinct_candidate_persons']:,} resolved candidate persons**. One resolved person has two candidacies; candidacy grain is preserved.", "",
              f"Cached Instagram review universe: {summary['person_account_links']} person-account associations and {summary['local_list_account_candidates']} local-list search candidates. Deduplicated provisional handles with a person association or a city-title/handle signal: **{len(handles)} profiles**, **${summary['profile_estimate_usd']:.5f}** at the validated profile price. These are identity-review candidates, not verified accounts or a final prioritized selection. National-party or unrelated pages with no local signal remain visible as unresolved and are excluded from provisional organization batches.", "",
              f"The active candidate mart retains all official records and adds `candidacy_id`, `ballot_validity`, and `eligible_current_ballot`: **{summary['valid_candidacies']:,} A / {counts['active_city_2026_candidates']-summary['valid_candidacies']} N**. Invalid candidacies remain in the archive and are excluded from profile proposals. Person keys are clusters, not independently verified identity: the duplicate key needs review before combining metrics.", "",
              "The local proposal JSON packs at most 50 profiles per Actor input; that is a technical batch size, not a person cap. About-account, comments, follower lists and paid model/transcription add-ons remain off. The observed latest-12 bundle is a shallow recent sample, with local date filtering and post-ID deduplication. All proposed batches are held. Before any paid run: intersect with hos-rank's concrete explained targets, adjudicate identity evidence, show the exact bounded input/cap, and obtain spending authorization.", "",
              "Artifacts: `data/research_scope.json`, `data/inputs/top10_profile_first_proposal.json`, `data/inputs/top10_profile_candidates.csv`; Iceberg `marts.active_city_profile`, `marts.active_city_2026_contenders`, `marts.active_city_2026_candidates`, `marts.active_profile_candidates`. Rebuild locally with `uv run python -m czlake.build.top10_prepare`. The command makes no network call.", "",
              "Ranking handoff: use 2026 city/list/position and candidacy identity as the active relevance gate. `marts.rank_official_composite` is the rejected additive baseline, never the new scheduling score. `share_2022_same_party` is an overlap proxy that picks the best historical member-party list, not verified coalition continuity. Municipal personal votes are multi-vote totals, not one-person-one-vote support. Office marts are election-term proxies and can miss resignations/deaths/role changes. Accepted SERP links are heuristics; curated Wikidata/scout provenance and person `possible_duplicates` must remain explicit. Missing/new-list history must retain its independent path. No local follower metrics have been bought yet; the cached national profile sample demonstrates pricing, not reach of these candidates. All evidence and public funding/newcomer discoveries must cite actual sources; occupation alone does not establish wealth or spending.", "",
              "Sources: [ČSÚ population CSV](https://data.csu.gov.cz/opendata/sady/OBY02A/distribuce/csv), reference 1 January 2026; [ČSÚ OBY02AT02](https://data.csu.gov.cz/datastat/data/VYBER/OBY02AT02); [KV2026 registry](https://volby.gov.cz/opendata/kv2026/KV2026reg20261007_csv.zip), 7 October 2026. See [cost-validation.md](cost-validation.md) for actual billed bundle examples.", ""]
    document = DOCS / "top10-batch-plan.md"
    previous = document.read_text() if document.exists() else ""
    section = previous.find("\n## ")
    document.write_text("\n".join(lines)+(previous[section:] if section >= 0 else ""))
    (PROJECT / "tmp" / "explore-top10-preparation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in summary.items() if key != "batches"}, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    prepare()
