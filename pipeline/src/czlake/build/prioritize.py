"""Prepare explained top-ten city research priorities without lake writes or paid calls.

Run: uv run python -m czlake.build.prioritize --project /path/to/project
"""

from __future__ import annotations

import os
import argparse
import csv
import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote, urlparse

import duckdb

from ..priority import RULE_VERSION, Candidate, qualify, schedule

TABLES = (
    "core.municipality_top",
    "core.candidacy",
    "core.candidacy_person",
    "core.person",
    "core.account",
    "core.list_party",
    "core.result_municipality",
    "marts.city_2026_candidates",
    "marts.city_2026_contenders",
)


def open_snapshot(lake: Path, pinned: dict | None = None) -> tuple[duckdb.DuckDBPyConnection, dict]:
    """Pin catalog pointers in a read-only SQLite transaction; scan immutable local metadata."""
    con = duckdb.connect(
        config={
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
        }
    )
    con.sql("LOAD iceberg")  # Already installed; no INSTALL and no network fallback.
    with sqlite3.connect(f"{(lake / 'catalog.db').resolve().as_uri()}?mode=ro", uri=True) as catalog:
        catalog.execute("PRAGMA query_only=ON")
        pointers = {
            f"{ns}.{name}": location
            for ns, name, location in catalog.execute(
                "SELECT table_namespace, table_name, metadata_location FROM iceberg_tables"
            )
        }
    manifest = {}
    for table in TABLES:
        location = urlparse(Path(pinned[table]["metadata"]).as_uri() if pinned else pointers[table])
        if location.scheme != "file" or location.netloc:
            raise ValueError(f"Only local Iceberg metadata is allowed: {table}")
        path = Path(unquote(location.path)).resolve()
        if not path.is_relative_to(lake.resolve()):
            raise ValueError(f"Metadata escaped the lake: {table}")
        metadata = json.loads(path.read_text())
        manifest[table] = {
            "metadata": str(path),
            "snapshot_id": metadata["current-snapshot-id"],
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        if pinned and manifest[table] != pinned[table]:
            raise ValueError(f"Pinned metadata changed: {table}")
        namespace, _ = table.split(".")
        con.sql(f"CREATE SCHEMA IF NOT EXISTS {namespace}")
        con.sql(
            f"CREATE VIEW {table} AS SELECT * FROM iceberg_scan('{str(path).replace(chr(39), chr(39) * 2)}')"
        )
    return con, manifest


UNIVERSE_SQL = """
WITH top AS (SELECT * FROM core.municipality_top WHERE population_rank <= 10),
linked AS (SELECT c.*, p.person_id FROM core.candidacy c LEFT JOIN core.candidacy_person p USING(candidacy_id)),
current AS (
 SELECT c.*, t.name AS city, t.population, t.population_rank, p.possible_duplicates
 FROM linked c JOIN top t ON c.unit_code=t.municipality_code LEFT JOIN core.person p USING(person_id)
 WHERE c.election_id='kv2026' AND c.unit_type='city_council'
),
old_local AS (
 SELECT c.*, rank() OVER(PARTITION BY unit_code ORDER BY pref_votes DESC NULLS LAST) AS vote_rank,
        pref_votes / nullif(list_votes::DOUBLE / count(*) OVER(PARTITION BY unit_code,list_no),0) AS vote_lift
 FROM linked c JOIN top t ON c.unit_code=t.municipality_code
 WHERE election_id='kv2022' AND unit_type='city_council' AND validity='A'
),
history AS (
 SELECT person_id,unit_code, min(vote_rank) FILTER(WHERE pref_votes>0) AS local_vote_rank, max(vote_lift) AS local_vote_lift,
        bool_or(list_position=1) AS prior_leader, bool_or(elected) AS local_mandate,
        list(struct_pack(candidacy_id:=candidacy_id,source_url:=source_url,fetched_at:=fetched_at,
          list_no:=list_no,list_position:=list_position,pref_votes:=pref_votes,list_votes:=list_votes,
          vote_rank:=vote_rank,vote_lift:=vote_lift,elected:=elected) ORDER BY candidacy_id) AS historical_sources
 FROM old_local GROUP BY person_id,unit_code
),
mandates AS (
 SELECT person_id, true AS mandate, list(struct_pack(election_id:=election_id,unit_name:=unit_name,
        source_url:=source_url,fetched_at:=fetched_at) ORDER BY election_id,unit_name,source_url) AS mandate_sources
 FROM linked WHERE elected AND election_id IN('ps2025','ep2024','kz2024','se2022','se2024','se2025leden')
 GROUP BY person_id
),
local22 AS (
 SELECT unit_code,list_party_code,max(list_pct)/100 AS local22_share,
        list(DISTINCT source_url ORDER BY source_url) AS local22_sources
 FROM core.candidacy WHERE election_id='kv2022' AND unit_type='city_council'
   AND list_party_code NOT IN('0','80','90','99','') GROUP BY unit_code,list_party_code
),
ps_totals AS (
 SELECT list_no,sum(votes) AS votes FROM core.result_municipality WHERE election_id='ps2025' GROUP BY list_no
),
ps_national AS (SELECT list_no,votes/sum(votes) OVER() AS share FROM ps_totals),
ps_mapping AS (SELECT list_no,list_party_code,max(source_url) AS source_url FROM core.candidacy
              WHERE election_id='ps2025' GROUP BY list_no,list_party_code),
party AS (
 SELECT c.candidacy_id,max(n.share) AS national_alliance_share,max(r.share) AS city_alliance_share,
        list(DISTINCT struct_pack(current_member_party:=lp.party_code,prior_alliance_code:=previous.list_party_code,
             national_share:=n.share,city_share:=r.share,source_url:=pm.source_url)) AS party_sources
 FROM current c JOIN core.list_party lp ON lp.election_id='kv2026' AND lp.list_party_code=c.list_party_code
 JOIN core.list_party previous ON previous.election_id='ps2025' AND previous.party_code=lp.party_code
 JOIN ps_mapping pm ON pm.list_party_code=previous.list_party_code
 JOIN ps_national n ON n.list_no=pm.list_no
 LEFT JOIN core.result_municipality r ON r.election_id='ps2025' AND r.list_no=pm.list_no
      AND r.municipality_code=c.unit_code
 WHERE lp.party_code NOT IN('0','80','90','99','') GROUP BY c.candidacy_id
)
SELECT c.*, h.local_vote_rank,h.local_vote_lift,h.prior_leader,h.historical_sources,
       coalesce(h.local_mandate,false) OR coalesce(m.mandate,false) AS mandate_evidence, m.mandate_sources,
       l.local22_share,l.local22_sources,party.national_alliance_share,party.city_alliance_share,party.party_sources
FROM current c LEFT JOIN history h USING(person_id,unit_code) LEFT JOIN mandates m USING(person_id)
LEFT JOIN local22 l USING(unit_code,list_party_code) LEFT JOIN party USING(candidacy_id)
ORDER BY c.population_rank,try_cast(c.list_no AS INT),c.list_position,c.candidacy_id
"""


def read_cached_metrics(project: Path) -> tuple[list[dict], list[dict]]:
    """Project cached public profile counts only; never inspect follower lists or comments."""
    metrics, sources = [], []
    root = project / "data/lake/raw/apify"
    paths = {path for pattern in ("m1_*/*.json", "top10_authorized_profiles/*.json") for path in root.glob(pattern)}
    for path in sorted(paths):
        saved = json.loads(path.read_text())
        if saved["actor"] not in (
            "apify/instagram-profile-scraper",
            "clockworks/tiktok-profile-scraper",
        ):
            continue
        sources.append(
            {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "fetched_at": saved["fetched_at"],
            }
        )
        for item in saved["items"]:
            if saved["actor"] == "apify/instagram-profile-scraper":
                handle, followers, url = (
                    item["username"],
                    item.get("followersCount"),
                    item["url"],
                )
                private = item.get("private", item.get("isPrivate", False))
                platform = "instagram"
            else:
                author = item["authorMeta"]
                handle, followers, url = (
                    author["name"],
                    author.get("fans"),
                    author["profileUrl"],
                )
                private = author.get("privateAccount", False)
                platform = "tiktok"
            if followers is not None and followers >= 0 and not private:
                metrics.append(
                    {
                        "platform": platform,
                        "handle": handle.lower().strip("@/"),
                        "followers": followers,
                        "url": url,
                        "observed_at": saved["fetched_at"],
                        "source_path": str(path),
                    }
                )
    return metrics, sources


def reviewed_signals(records: list[dict], candidate_id: str | None, city_code: str, as_of: datetime) -> tuple:
    """Consume explicit identity/source adjudications; source counts alone never verify an action."""
    relevant = [
        r
        for r in records
        if r["candidacy_id"] == candidate_id
        and r["municipality_code"] == city_code
        and r["identity_confirmed"]
        and r["public"]
        and r["adjudication"] == "confirmed"
        and urlparse(r["source_url"]).scheme in ("http", "https")
        and r["excerpt"].strip()
        and (r["kind"] != "account_identity" or r["anchor_links_account"])
        and 0 <= (as_of - datetime.fromisoformat(r["observed_at"])).total_seconds() <= 30 * 86400
    ]
    # A contradiction on the same candidate/kind blocks that channel pending resolution.
    disputed = {
        r["kind"]
        for r in records
        if r["candidacy_id"] == candidate_id
        and r["municipality_code"] == city_code
        and r["adjudication"] == "conflicting"
    }
    role = [
        r
        for r in relevant
        if r["kind"] == "local_political_role"
        and r["official_role_source"]
        and datetime.fromisoformat(r["valid_from"]) <= as_of <= datetime.fromisoformat(r["valid_until"])
    ]
    actions = [
        r
        for r in relevant
        if r["kind"] == "local_public_action"
        and r["substantive_action_confirmed"]
        and 0 <= (as_of - datetime.fromisoformat(r["event_at"])).total_seconds() <= 365 * 86400
    ]
    activity = any(
        a["independent_origin"].strip()
        and b["independent_origin"].strip()
        and a["independent_origin"] != b["independent_origin"]
        for a in role
        for b in actions
    )
    office = any(
        r["kind"] == "current_office"
        and r["official_role_source"]
        and datetime.fromisoformat(r["valid_from"]) <= as_of <= datetime.fromisoformat(r["valid_until"])
        for r in relevant
    )
    activity = activity and not disputed.intersection(("local_public_action", "local_political_role"))
    office = office and "current_office" not in disputed
    # An account/office review, stale action or unresolved conflict does not
    # establish measured absence of activity. Withhold that channel as unknown.
    return True if activity else None, office, relevant, sorted(disputed)


def local_role_extensions(
    reviews: list[dict],
    cities: list[dict],
    as_of: datetime,
    existing: set,
    metrics: list[dict] | None = None,
    owners: dict | None = None,
) -> list[dict]:
    """Admit reviewed public political founders/leaders without harvesting owners or donors."""
    by_city = {r["municipality_code"]: r for r in cities}
    extensions = {}
    disputed = {
        (r["entity_id"], r["municipality_code"])
        for r in reviews
        if r["candidacy_id"] is None and r["adjudication"] == "conflicting"
    }
    for review in sorted(
        reviews,
        key=lambda r: (datetime.fromisoformat(r["observed_at"]), r["source_url"]),
        reverse=True,
    ):
        if review["candidacy_id"] is not None or review["kind"] != "local_political_role":
            continue
        pair = (review["entity_id"], review["municipality_code"])
        if pair in existing or pair in disputed or pair[1] not in by_city:
            continue
        if not (
            review["identity_confirmed"]
            and review["public"]
            and review["adjudication"] == "confirmed"
            and review["official_role_source"]
            and review["role_type"] in ("founder", "local_leader")
            and review["organization_kind"] == "local_political_organization"
            and review["excerpt"].strip()
            and review["organization_name"].strip()
            and urlparse(review["source_url"]).scheme in ("http", "https")
            and urlparse(review["identity_source_url"]).scheme in ("http", "https")
            and 0 <= (as_of - datetime.fromisoformat(review["observed_at"])).total_seconds() <= 30 * 86400
            and datetime.fromisoformat(review["valid_from"])
            <= as_of
            <= datetime.fromisoformat(review["valid_until"])
        ):
            continue
        city = by_city[pair[1]]
        key = "role_" + hashlib.sha256((pair[0] + ":" + pair[1]).encode()).hexdigest()[:16]
        # A role establishes discovery eligibility, but relevance needs its own
        # evidence. Filter by entity before handling same-city noncandidate reviews.
        related = sorted(
            (r for r in reviews if r.get("entity_id") == pair[0]),
            key=lambda r: json.dumps(r, sort_keys=True),
        )
        activity, office, sources, disputes = reviewed_signals(related, None, pair[1], as_of)
        role_accounts = [
            {
                "platform": r["platform"],
                "handle": r["handle"],
                "person_id": pair[0],
                "status": "reviewed",
            }
            for r in sources
            if r["kind"] == "account_identity" and "account_identity" not in disputes
        ]
        verified, measurements = reviewed_following(
            role_accounts, owners or {}, metrics or [], sources, as_of
        )
        candidate = Candidate(
            key,
            pair[1],
            city["population_rank"],
            "0",
            0,
            True,
            None,
            False,
            None,
            None,
            None,
            max((m["followers"] for m in measurements), default=None),
            city["population"],
            activity,
            False,
            office,
            True,
            "reviewed_local_role",
        )
        decision = qualify(candidate)
        record = {
            "candidate": asdict(candidate),
            "city": city["name"],
            "name": review["entity_name"],
            "person_id": pair[0],
            "list_name": review["organization_name"],
            "components": decision.components,
            "reasons": decision.reasons,
            "winner": decision.winner,
            "score": decision.score,
            "qualified": decision.qualified,
            "protected": decision.protected,
            "gaps": [
                "no current ballot candidacy; discovery via reviewed public local role",
                "leadership alone is discovery context; qualification needs an independent O/M/V/R/A signal",
                "finance is optional context, not a qualification factor",
            ],
            "evidence": {"eligibility_kind": "reviewed_local_role", "source": review},
            "accounts": role_accounts,
            "verified_accounts": verified,
            "metrics": measurements,
            "reviewed_sources": sources,
        }
        extensions.setdefault(key, record)
    return list(extensions.values())


def reviewed_following(
    person_accounts: list[dict],
    owners: dict,
    metrics: list[dict],
    reviews: list[dict],
    as_of: datetime,
) -> tuple[list, list]:
    """Attribute reach only after a fresh explicit anchor review, never from an inherited accepted label."""
    reviewed_handles = {
        (r["platform"], r["handle"].lower()) for r in reviews if r["kind"] == "account_identity"
    }
    verified = [
        a
        for a in person_accounts
        if a["status"] != "rejected"
        and (a["platform"], a["handle"].lower()) in reviewed_handles
        and owners.get((a["platform"], a["handle"].lower()), {a["person_id"]}) == {a["person_id"]}
    ]
    matching = [
        m
        for m in metrics
        if any(m["platform"] == a["platform"] and m["handle"] == a["handle"].lower() for a in verified)
        and 0 <= (as_of - datetime.fromisoformat(m["observed_at"])).total_seconds() <= 30 * 86400
    ]
    latest = {}
    for metric in sorted(
        matching,
        key=lambda m: (
            datetime.fromisoformat(m["observed_at"]),
            -m["followers"],
            m["source_path"],
        ),
    ):
        latest[(metric["platform"], metric["handle"])] = metric
    measurements = list(latest.values())
    for metric in measurements:
        metric["conflicting_counts"] = (
            len(
                {
                    m["followers"]
                    for m in matching
                    if (
                        m["platform"],
                        m["handle"],
                        datetime.fromisoformat(m["observed_at"]),
                    )
                    == (
                        metric["platform"],
                        metric["handle"],
                        datetime.fromisoformat(metric["observed_at"]),
                    )
                }
            )
            > 1
        )
    return verified, measurements


def prepare(
    project: Path,
    as_of: datetime,
    reviews: list[dict] | None = None,
    pinned: dict | None = None,
) -> tuple[list, list[dict], dict]:
    """Attach independent signals conservatively, preserving evidence and gaps per candidate."""
    con, manifest = open_snapshot(project / "data/lake", pinned)
    cities = (
        con.sql("SELECT * FROM core.municipality_top WHERE population_rank<=10 ORDER BY population_rank")
        .to_arrow_table()
        .to_pylist()
    )
    records = con.sql(UNIVERSE_SQL).to_arrow_table().to_pylist()
    mart_counts = con.sql("""SELECT count(*) FROM marts.city_2026_candidates WHERE population_rank<=10
                            UNION ALL SELECT count(*) FROM marts.city_2026_contenders WHERE population_rank<=10""").fetchall()
    if (
        len(records) != mart_counts[0][0]
        or len({(r["unit_code"], r["list_no"]) for r in records}) != mart_counts[1][0]
    ):
        raise ValueError(
            "Core current candidacies disagree with the retained top-ten marts; refresh evidence before ranking"
        )
    retained = (
        con.sql("SELECT * FROM core.account ORDER BY account_id,person_id").to_arrow_table().to_pylist()
    )
    metrics, metric_sources = read_cached_metrics(project)
    if as_of.tzinfo is None:
        raise ValueError("as_of requires an explicit time zone")
    owners: dict[tuple, set] = {}
    accounts: dict[str, list] = {}
    for account in retained:
        accounts.setdefault(account["person_id"], []).append(account)
        if account["status"] == "accepted":
            owners.setdefault((account["platform"], account["handle"].lower()), set()).add(
                account["person_id"]
            )
    decisions, explained = [], []
    for row in records:
        if row["party_sources"]:
            row["party_sources"].sort(key=lambda r: json.dumps(r, sort_keys=True))
        person_accounts = accounts.get(row["person_id"], [])
        activity, office, reviewed, disputes = reviewed_signals(
            reviews or [], row["candidacy_id"], row["unit_code"], as_of
        )
        verified, measurements = reviewed_following(
            person_accounts,
            owners,
            metrics,
            [] if "account_identity" in disputes else reviewed,
            as_of,
        )
        following = max((m["followers"] for m in measurements), default=None)
        strengths = [
            row["local22_share"] / 0.10 if row["local22_share"] is not None else None,
            row["national_alliance_share"] / 0.05 if row["national_alliance_share"] is not None else None,
            row["city_alliance_share"] / 0.10 if row["city_alliance_share"] is not None else None,
        ]
        strength = max((s for s in strengths if s is not None), default=None)
        candidate = Candidate(
            row["candidacy_id"],
            row["unit_code"],
            row["population_rank"],
            row["list_no"],
            row["list_position"],
            row["validity"] == "A",
            strength,
            row["mandate_evidence"],
            row["local_vote_rank"],
            row["local_vote_lift"],
            row["prior_leader"],
            following,
            row["population"],
            activity if reviewed else None,
            row["person_id"] is not None and row["possible_duplicates"] == 0,
            office,
        )
        decision = qualify(candidate)
        decisions.append(decision)
        gaps = []
        if not office:
            gaps.append("current office not verified; electoral mandates are historical research proxies")
        if not activity:
            gaps.append("public activity not adjudicated or qualifying action not established")
        if disputes:
            gaps.append("conflicting reviewed evidence withheld: " + ", ".join(disputes))
        if row["possible_duplicates"] or row["person_id"] is None:
            gaps.append(
                "historical identity unresolved; historical signals withheld and account requires explicit review"
            )
        if following is None:
            gaps.append("no fresh public metric on an independently anchored unique account")
        if strength is None:
            gaps.append("party history unknown; generic independent/SNK codes never matched")
        explained.append(
            {
                "candidate": asdict(candidate),
                "city": row["city"],
                "name": f"{row['first_name']} {row['last_name']}",
                "person_id": row["person_id"],
                "list_name": row["list_name"],
                "components": decision.components,
                "reasons": decision.reasons,
                "winner": decision.winner,
                "score": decision.score,
                "qualified": decision.qualified,
                "protected": decision.protected,
                "gaps": gaps,
                "evidence": row,
                "accounts": person_accounts,
                "verified_accounts": verified,
                "metrics": measurements,
                "reviewed_sources": reviewed,
            }
        )
    existing = {
        (r["person_id"], r["candidate"]["city_code"]) for r in explained if r["candidate"]["eligible"]
    }
    for extension in local_role_extensions(reviews or [], cities, as_of, existing, metrics, owners):
        decisions.append(qualify(Candidate(**extension["candidate"])))
        explained.append(extension)
    con.close()
    return (
        decisions,
        explained,
        {
            "tables": manifest,
            "metric_files": metric_sources,
            "as_of": as_of.isoformat(),
            "rule_version": RULE_VERSION,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(os.environ.get("CZLAKE_PROJECT") or Path(__file__).resolve().parents[4]))
    parser.add_argument("--as-of", default="2026-10-09T00:45:00+02:00")
    parser.add_argument(
        "--reviewed-evidence",
        type=Path,
        help="Local, explicitly adjudicated public office/activity evidence JSON",
    )
    parser.add_argument("--snapshot-manifest", type=Path, help="Replay previously pinned local metadata")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory under the project tmp directory",
    )
    args = parser.parse_args()
    reviews = json.loads(args.reviewed_evidence.read_text()) if args.reviewed_evidence else []
    pinned = json.loads(args.snapshot_manifest.read_text())["tables"] if args.snapshot_manifest else None
    decisions, explained, manifest = prepare(
        args.project, datetime.fromisoformat(args.as_of), reviews, pinned
    )
    if args.reviewed_evidence:
        manifest["reviewed_evidence"] = {
            "path": str(args.reviewed_evidence.resolve()),
            "sha256": hashlib.sha256(args.reviewed_evidence.read_bytes()).hexdigest(),
        }
    output = args.output_dir.resolve() if args.output_dir else args.project / "tmp/prioritization"
    if not output.resolve().is_relative_to((args.project / "tmp").resolve()):
        raise ValueError("Output must stay under project tmp; the lake is read-only")
    output.mkdir(parents=True, exist_ok=True)
    summary = []
    for city_rank in range(1, 11):
        members = [
            r
            for r in explained
            if r["candidate"]["city_rank"] == city_rank
            and r["candidate"]["eligibility_kind"] == "current_candidacy"
        ]
        extensions = [
            r
            for r in explained
            if r["candidate"]["city_rank"] == city_rank
            and r["candidate"]["eligibility_kind"] == "reviewed_local_role"
        ]
        summary.append(
            {
                "city": members[0]["city"],
                "city_rank": city_rank,
                "registrations": len(members),
                "valid": sum(r["candidate"]["eligible"] for r in members),
                "lists": len({r["candidate"]["list_no"] for r in members}),
                "qualified": sum(r["qualified"] for r in members),
                "protected": sum(r["protected"] for r in members),
                "reviewed_noncandidate_discoveries": len(extensions),
                "ambiguous": sum(not r["candidate"]["historical_identity_clear"] for r in members),
                "accepted_accounts": sum(
                    bool(r["accounts"]) and any(a["status"] == "accepted" for a in r["accounts"])
                    for r in members
                ),
                "verified_metric": sum(r["candidate"]["followers"] is not None for r in members),
            }
        )
    for name, content in (
        ("universe.json", explained),
        ("summary.json", summary),
        ("manifest.json", manifest),
    ):
        (output / name).write_text(json.dumps(content, ensure_ascii=False, indent=2, default=str) + "\n")
    by_key = {r["candidate"]["key"]: r for r in explained}
    ledger_path = args.project / "data/ledger.csv"
    state_path = args.project / "data/ledger_state.json"
    ledger = list(csv.DictReader(ledger_path.open()))
    state = json.loads(state_path.read_text())
    actual = sum((Decimal(r["usage_total_usd"]) for r in ledger), Decimal(0))
    reserved = sum((Decimal(str(r["max"])) for r in state["reservations"].values()), Decimal(0))
    remaining = max(Decimal(0), Decimal(20) - actual - reserved)
    budget_evidence = {
        "original_cap_usd": "20",
        "actual_usd": str(actual),
        "reserved_usd": str(reserved),
        "remaining_usd": str(remaining),
        "ledger_sha256": hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
        "state_sha256": hashlib.sha256(state_path.read_bytes()).hexdigest(),
        "hold_present": (args.project / "data/paid_launch_hold.json").exists(),
        "status": "held_preparation_only",
    }
    (output / "budget.json").write_text(json.dumps(budget_evidence, indent=2) + "\n")
    provisional_path = args.project / "data/inputs/top10_profile_candidates.csv"
    provisional = list(csv.DictReader(provisional_path.open()))
    qualified_candidates = {
        (
            r["person_id"],
            r["candidate"]["city_code"],
            r["candidate"]["list_no"],
            r["candidate"]["position"],
        )
        for r in explained
        if r["qualified"] and r["candidate"]["eligibility_kind"] == "current_candidacy"
    }
    qualified_lists = {
        (r["candidate"]["city_code"], r["candidate"]["list_no"])
        for r in explained
        if r["qualified"]
        and r["candidate"]["eligibility_kind"] == "current_candidacy"
        and r["candidate"]["position"] == 1
    }
    intersected = [
        r
        for r in provisional
        if (
            r["entity_kind"] == "person"
            and (
                r["entity_id"],
                r["municipality_code"],
                r["list_no"],
                int(r["list_position"]),
            )
            in qualified_candidates
        )
        or (
            r["entity_kind"] == "local_list"
            and (r["municipality_code"], r["list_no"]) in qualified_lists
            and "city in profile" in r["candidate_basis"]
        )
    ]
    handles = sorted({r["handle"].lower() for r in intersected})
    (output / "profile_intersection.json").write_text(
        json.dumps(
            {
                "status": "identity_review_only_no_paid_ready_targets",
                "candidate_links": sum(r["entity_kind"] == "person" for r in intersected),
                "local_list_candidates": sum(r["entity_kind"] == "local_list" for r in intersected),
                "deduplicated_handles": len(handles),
                "conditional_profile_price_usd": str(Decimal("0.0023") * len(handles)),
                "provisional_source": str(provisional_path),
                "sha256": hashlib.sha256(provisional_path.read_bytes()).hexdigest(),
                "handles": handles,
                "associations": intersected,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    scenarios = []
    for name, slots, budget, price in (
        ("official_only_5_per_city", 5, Decimal(0), Decimal(0)),
        ("profile_first_10_per_city", 10, Decimal(1), Decimal("0.00485")),
        ("profile_first_20_per_city", 20, Decimal(1), Decimal("0.00485")),
        ("all_qualifiers_plus_discovery", 100, Decimal(5), Decimal("0.00485")),
        ("facebook_10_posts_5_per_city", 5, Decimal(5), Decimal("0.04355")),
        (
            "facebook_10_posts_remaining_cap",
            100,
            remaining,
            Decimal("0.04355"),
        ),
        (
            "facebook_30_posts_remaining_cap",
            100,
            remaining,
            Decimal("0.12355"),
        ),
    ):
        budget = min(budget, remaining)
        plan = schedule(decisions, slots, budget, {d.candidate.key: price for d in decisions})
        scenario = {
            "name": name,
            "status": "held_preparation_only",
            "per_city_capacity": slots,
            "budget_upper_bound_usd": str(budget),
            "unit_upper_bound_usd": str(price),
            "estimated_cost_usd": str(plan.cost),
            "selected": len(plan.selected),
            "selected_qualified": sum(d.qualified for d in plan.selected),
            "selected_exploratory": len(plan.exploratory),
            "qualifying_overflow": len(plan.deferred),
            "protected_selected": plan.protected_slots_filled,
            "protected_slots_requested": plan.protected_slots_requested,
            "cities": {
                str(rank): sum(d.candidate.city_rank == rank for d in plan.selected) for rank in range(1, 11)
            },
        }
        scenarios.append(scenario)
        selection = [
            {
                **by_key[d.candidate.key],
                "selection_kind": "qualified" if d.qualified else "missing_evidence_exploration",
                "paid_ready": False,
                "estimated_upper_bound_usd": str(price),
            }
            for d in plan.selected
        ]
        (output / (name + ".json")).write_text(
            json.dumps(
                {
                    "scenario": scenario,
                    "selection": selection,
                    "qualifying_overflow": [d.candidate.key for d in plan.deferred],
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
            + "\n"
        )
    (output / "scenarios.json").write_text(json.dumps(scenarios, indent=2) + "\n")
    with (output / "summary.csv").open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("total qualified", sum(d.qualified for d in decisions))


if __name__ == "__main__":
    main()
