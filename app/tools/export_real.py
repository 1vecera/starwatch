"""Export a pinned, read-only production checkpoint into the local Starwatch app.

Run: uv run --with duckdb python tools/export_real.py
Only observed previews and explicitly catalogued Commons logos are downloaded. Data/media are never committed.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import os
import re
import runpy
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import duckdb

CITY_COORDS = {
    "Praha": (14.423, 50.087),
    "Brno": (16.610, 49.200),
    "Ostrava": (18.250, 49.830),
    "Plzeň": (13.378, 49.747),
    "Olomouc": (17.251, 49.594),
    "České Budějovice": (14.474, 48.975),
    "Hradec Králové": (15.833, 50.209),
    "Liberec": (15.056, 50.767),
    "Pardubice": (15.779, 50.034),
    "Ústí nad Labem": (14.041, 50.661),
}
ASSET_TYPES = {
    "image": "post",
    "sidecar": "post",
    "photo": "post",
    "carousel": "post",
    "post": "post",
    "video": "video",
    "reel": "reel",
    "reels": "reel",
    "article": "article",
    "page": "page",
}
REVIEWED = {"independently_reviewed", "admitted"}
PLATFORMS = ("instagram", "facebook", "tiktok", "youtube", "x", "news", "web")
# Exact Commons file titles, selected from each file's party-specific description.
PARTY_LOGOS = {
    "ano": ("ANO 2011", "ANO Logo.svg", r"\bano 2011\b", r"(?:^|[+,;/])\s*ano\s*(?=$|[+,;/])"),
    "ods": ("ODS", "Logo of ODS (2015).svg", r"\b(?:ods|obcanska demokraticka strana)\b", r"\bods\b"),
    "stan": ("STAN", "STAN logo.svg", r"\b(?:stan|starostove a nezavisli)\b", r"\bstan\b"),
    "pirati": (
        "Piráti",
        "Czech Pirate Party logo 2017.svg",
        r"\b(?:pirati|piratu|piraty|piratska strana)\b",
        r"\bpirati\b",
    ),
    "kdu": ("KDU-ČSL", "KDU-ČSL Lidovci.svg", r"\b(?:kdu[- ]?csl|lidovci|lidovcu)\b", r"\bkdu(?:[- ]?csl)?\b"),
    "top09": ("TOP 09", "TOP09 Logo.svg", r"\btop\s*09\b", r"\btop\s*09\b"),
    "spd": ("SPD", "SPD Czechia logo (2026).svg", r"\b(?:spd|svoboda a prima demokracie)\b", r"\bspd\b"),
    "socdem": (
        "SOCDEM",
        "Logo of the Social Democracy (Czech Republic).svg",
        r"\b(?:socdem|socialni demokracie)\b",
        r"\bsocdem\b",
    ),
    "kscm": ("KSČM", "Logo KSČM.svg", r"\b(?:kscm|komunistick[ae] stran[ay] cech a moravy)\b", r"kscm"),
    "zeleni": ("Zelení", "LogoStranyZelenych05 22.svg", r"\b(?:zeleni|zelenych)\b", r"\b(?:zeleni|zelen|zel\.)"),
    "motoriste": ("Motoristé sobě", "Motoristé sobě logo.svg", r"\bmotoriste\b", r"\bauto\b"),
    "pro": (
        "PRO",
        "Právo Respekt Odbornost.svg",
        r"\bpro pravo respekt odbornost\b",
        r"(?:^|[+,;/])\s*pro\s*(?=$|[+,;/])",
    ),
    "prisaha": ("Přísaha", "Přísaha.svg", r"\bprisah[ay]\b", r"\bprisah[a]?\b"),
}
MAX_IMAGE_BYTES = 32 * 1024 * 1024
Record = dict[str, Any]


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_bytes())


def atomic_write(path: Path, content: bytes) -> None:
    """Keep readers on the previous complete artifact until replacement is ready."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def pinned_checkpoint(read_root: Path) -> tuple[Record, Path, list[Record]]:
    """Read the atomic pointer once and verify immutable checkpoint bytes before use."""
    pointer = read_json(read_root / "current.json")
    paths = []
    for field in ("manifest", "database"):
        path = (read_root / pointer[field]).resolve()
        if not path.is_relative_to(read_root / "checkpoints") or any(
            part.startswith(".building-") for part in path.parts
        ):
            raise ValueError("Pointer does not reference a published checkpoint")
        paths.append(path)
    manifest_path, database = paths
    content = manifest_path.read_bytes()
    if sha256(content) != pointer["manifest_sha256"]:
        raise ValueError("Checkpoint manifest hash mismatch")
    manifest = json.loads(content)
    for field in ("checkpoint_id", "created_at", "schema_version"):
        if pointer[field] != manifest[field]:
            raise ValueError(f"Pointer/manifest disagree: {field}")
    if database.parent != manifest_path.parent:
        raise ValueError("Database and manifest belong to different checkpoints")
    for name in (database.name, "coverage.json"):
        file_bytes = (database.parent / name).read_bytes()
        if sha256(file_bytes) != manifest["files"][name]["sha256"]:
            raise ValueError(f"Checkpoint file hash mismatch: {name}")
    return pointer, database, read_json(database.parent / "coverage.json")


def rows(connection: duckdb.DuckDBPyConnection, query: str, parameters: list[Any] | None = None) -> list[Record]:
    cursor = connection.execute(query, parameters)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def exact_name(value: str) -> str:
    """Keep accents and every name token; normalize only Unicode, case and whitespace."""
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def age_consistent(current_age: Any, prior_age: Any) -> bool:
    """Intersect exact birth-date intervals for the two municipal election dates."""
    if not isinstance(current_age, int) or not isinstance(prior_age, int):
        return False
    if not 18 <= current_age <= 120 or not 18 <= prior_age <= 120:
        return False
    current_day, prior_day = date(2026, 10, 9), date(2022, 9, 23)
    current_lo = current_day.replace(year=current_day.year - current_age - 1)
    current_hi = current_day.replace(year=current_day.year - current_age)
    prior_lo = prior_day.replace(year=prior_day.year - prior_age - 1)
    prior_hi = prior_day.replace(year=prior_day.year - prior_age)
    return max(current_lo, prior_lo) < min(current_hi, prior_hi)


def party_composition(value: str | None) -> tuple[int, ...] | None:
    if not value:
        return None
    try:
        return tuple(sorted(int(code) for code in value.split(",")))
    except ValueError:
        return None


def apply_election_results(
    raw: Record, current_lists: list[Record], prior_lists: list[Record], prior_candidates: list[Record]
) -> Counter[str]:
    """Require unique official-code list matches and mutually unique exact-name/age person matches."""
    counts: Counter[str] = Counter()
    current_by_ballot = defaultdict(list)
    prior_by_party = defaultdict(list)
    prior_by_name = defaultdict(list)
    for item in current_lists:
        current_by_ballot[(item["city_id"], item["number"])].append(item)
    for item in prior_lists:
        # Independent/SNK category codes identify a type, not a continuing party or alliance.
        if item["party_code"] not in {None, 0, 80, 90, 99}:
            prior_by_party[(item["city_id"], item["party_code"])].append(item)
    for item in prior_candidates:
        prior_by_name[(item["city_id"], exact_name(item["name"]))].append(item)
    for entity in raw["lists"]:
        entity["result2022"] = None
        current = current_by_ballot[(entity["city_id"], entity["number"])]
        if len(current) != 1 or exact_name(current[0]["name"]) != exact_name(entity["name"]):
            counts["list_current_registry_missing_or_conflicting"] += 1
            continue
        party = current[0]
        matches = prior_by_party[(entity["city_id"], party["party_code"])]
        if len(matches) != 1:
            counts["list_no_unique_prior_code"] += 1
            continue
        prior = matches[0]
        # The same party code must also retain the official constituent-party composition.
        composition = party_composition(party["composition"])
        if composition is None or composition != party_composition(prior["composition"]):
            counts["list_composition_changed_or_unknown"] += 1
            continue
        if (
            not isinstance(prior["votes"], int)
            or prior["votes"] < 0
            or not isinstance(prior["seats"], int)
            or prior["seats"] < 0
            or prior["pct"] is None
            or not math.isfinite(prior["pct"])
            or not 0 <= prior["pct"] <= 100
            or not (prior["source_url"] or "").startswith("https://volby.gov.cz/opendata/kv2022/")
        ):
            counts["list_invalid_prior_result"] += 1
            continue
        entity["result2022"] = {
            "votes": prior["votes"],
            "pct": prior["pct"],
            "seats": prior["seats"],
            "party_match": str(prior["party_code"]),
            "source_url": prior["source_url"],
        }
    possible = {}
    claimants: Counter[tuple[str, int, int]] = Counter()
    for candidate in raw["cands"]:
        candidate["pref2022"] = None
        matches = [
            prior
            for prior in prior_by_name[(candidate["city_id"], exact_name(candidate["name"]))]
            if age_consistent(candidate.get("age"), prior["age"])
        ]
        possible[candidate["id"]] = matches
        for prior in matches:
            claimants[(prior["city_id"], prior["number"], prior["position"])] += 1
    for candidate in raw["cands"]:
        matches = possible[candidate["id"]]
        if len(matches) != 1:
            counts["candidate_ambiguous" if matches else "candidate_no_exact_name_age_match"] += 1
            continue
        prior = matches[0]
        if claimants[(prior["city_id"], prior["number"], prior["position"])] != 1:
            counts["candidate_ambiguous"] += 1
            continue
        if (
            not isinstance(prior["votes"], int)
            or prior["votes"] < 0
            or not isinstance(prior["rank_in_list"], int)
            or prior["rank_in_list"] < 1
            or not isinstance(prior["elected"], bool)
            or not prior["list_name"]
            or not (prior["source_url"] or "").startswith("https://volby.gov.cz/opendata/kv2022/")
        ):
            counts["candidate_invalid_prior_result"] += 1
            continue
        candidate["pref2022"] = {
            "votes": prior["votes"],
            "rank_in_list": prior["rank_in_list"],
            "elected": prior["elected"],
            "list_name_2022": prior["list_name"],
            "source_url": prior["source_url"],
        }
    counts["mapped_lists"] = sum(entity["result2022"] is not None for entity in raw["lists"])
    counts["unmapped_lists"] = len(raw["lists"]) - counts["mapped_lists"]
    counts["mapped_candidates"] = sum(candidate["pref2022"] is not None for candidate in raw["cands"])
    counts["unmapped_candidates"] = len(raw["cands"]) - counts["mapped_candidates"]
    return counts


def export_election_results(raw: Record, project: Path) -> Counter[str]:
    """Read current Iceberg snapshots through the read-only local catalog; never install extensions."""
    tables = ("volby_kv2026_reg_kvros", "volby_kv2022_reg_kvros", "volby_kv2022_reg_kvrk")
    locations, snapshots = {}, []
    catalog = project / "data/lake/catalog.db"
    with sqlite3.connect(catalog.as_uri() + "?mode=ro", uri=True) as connection:
        connection.execute("BEGIN")
        for table in tables:
            found = connection.execute(
                "SELECT metadata_location FROM iceberg_tables WHERE catalog_name='czlake' "
                "AND table_namespace='staging' AND table_name=?",
                [table],
            ).fetchall()
            if len(found) != 1:
                raise ValueError("Election lake snapshot missing or ambiguous")
            parsed = urlsplit(found[0][0])
            path = Path(unquote(parsed.path)).resolve()
            if (
                parsed.scheme != "file"
                or parsed.netloc
                or not path.is_relative_to(project / "data/lake/warehouse/staging" / table / "metadata")
            ):
                raise ValueError("Election lake snapshot is not local")
            content = path.read_bytes()
            metadata = json.loads(content)
            locations[table] = str(path)
            snapshots.append(
                {"table": table, "snapshot_id": metadata["current-snapshot-id"], "metadata_sha256": sha256(content)}
            )
    cities = [city["id"] for city in raw["cities"]]
    with duckdb.connect(
        config={"autoinstall_known_extensions": False, "autoload_known_extensions": False}
    ) as connection:
        connection.execute("LOAD iceberg")
        connection.execute("SET allowed_directories = ?", [[str(project / "data/lake") + "/"]])
        connection.execute("SET enable_external_access=false")
        list_columns = (
            "KODZASTUP AS city_id,try_cast(OSTRANA AS INTEGER) AS number,"
            "try_cast(VSTRANA AS INTEGER) AS party_code,NAZEVCELK AS name,SLOZENI AS composition"
        )
        current_lists = rows(
            connection,
            "SELECT DISTINCT " + list_columns + " FROM iceberg_scan(?) WHERE KODZASTUP=ANY(?) AND COBVODU='1'",
            [locations[tables[0]], cities],
        )
        prior_lists = rows(
            connection,
            "SELECT DISTINCT " + list_columns + ",try_cast(HLASY_STR AS BIGINT) AS votes,"
            "try_cast(replace(PROCHLSTR,',','.') AS DOUBLE) AS pct,"
            "try_cast(MAND_STR AS INTEGER) AS seats,source_url FROM iceberg_scan(?) "
            "WHERE KODZASTUP=ANY(?) AND COBVODU='1' AND DATUMVOLEB='20220923'",
            [locations[tables[1]], cities],
        )
        prior_candidates = rows(
            connection,
            "WITH c AS (SELECT DISTINCT KODZASTUP AS city_id,try_cast(OSTRANA AS INTEGER) AS number,"
            "try_cast(PORCISLO AS INTEGER) AS position,JMENO || ' ' || PRIJMENI AS name,"
            "try_cast(VEK AS INTEGER) AS age,try_cast(POCHLASU AS BIGINT) AS votes,"
            "CASE WHEN MANDAT='A' THEN true WHEN MANDAT='N' THEN false END AS elected,source_url "
            "FROM iceberg_scan(?) WHERE KODZASTUP=ANY(?) AND COBVODU='1' "
            "AND DATUMVOLEB='20220923' AND PLATNOST='A') "
            "SELECT *,rank() OVER(PARTITION BY city_id,number ORDER BY votes DESC NULLS LAST) AS rank_in_list FROM c",
            [locations[tables[2]], cities],
        )
    names = defaultdict(list)
    for entity in prior_lists:
        names[(entity["city_id"], entity["number"])].append(entity["name"])
    for candidate in prior_candidates:
        matches = names[(candidate["city_id"], candidate["number"])]
        candidate["list_name"] = matches[0] if len(matches) == 1 else None
    counts = apply_election_results(raw, current_lists, prior_lists, prior_candidates)
    counts["prior_lists_read"] = len(prior_lists)
    counts["prior_candidates_read"] = len(prior_candidates)
    raw["source"]["election_results2022"] = {
        "list_match": "same municipality, unique official party/alliance code and unchanged composition",
        "candidate_match": "same municipality, exact name and overlapping birth-date intervals; mutually unique",
        "rank_in_list": "descending candidate votes among valid 2022 candidacies; equal votes share rank",
        "pct_unit": "percent (0 to 100), as reported by ČSÚ",
        "snapshots": snapshots,
    }
    return counts


def official_fields(
    connection: duckdb.DuckDBPyConnection, candidates: list[Record], lists: list[Record], gaps: Counter[str]
) -> None:
    """Recover only official scalar fields from the exact hash-bound entity sources."""
    sources = {row["source_id"]: row for row in rows(connection, "SELECT * FROM source")}
    loaded = {}
    short_names: dict[str, set[str]] = defaultdict(set)
    for entity in candidates + lists:
        source_id = entity["source_id"]
        if source_id not in loaded:
            source = sources[source_id]
            try:
                content = Path(source["path"]).read_bytes()
                if sha256(content) != source["sha256"]:
                    raise ValueError("Changed source")
                loaded[source_id] = json.loads(content)
            except (OSError, ValueError):
                loaded[source_id] = None
                gaps["official_source_unavailable_or_changed"] += 1
        document = loaded[source_id]
        if document is None:
            continue
        index = int(entity["source_pointer"].removeprefix("/"))
        record = document[index]
        if entity["kind"] == "current_candidacy":
            if record["candidate"]["key"] != entity["entity_id"] or record["evidence"]["validity"] != "A":
                raise ValueError("Official candidacy source pointer mismatch")
            evidence = record["evidence"]
            entity["age"] = evidence["age"]
            entity["occupation"] = evidence["occupation"]
            if evidence["list_abbr"]:
                short_names[entity["list_id"]].add(evidence["list_abbr"])
        else:
            if record["key"] != entity["entity_id"]:
                raise ValueError("Official list source pointer mismatch")
            entity["number"] = int(record["list_no"])
    for entity in lists:
        abbreviations = short_names[entity["entity_id"]]
        entity["short"] = next(iter(abbreviations)) if len(abbreviations) == 1 else None
        if entity["short"] is None:
            gaps["list_short_name_unknown_or_conflicting"] += 1


def latest_snapshots(observations: list[Record], metrics: list[Record], grain: str) -> dict[str, Record]:
    """Deduplicate the newest dated snapshot; missing/conflicting counts remain null."""
    grouped = defaultdict(list)
    by_observation = defaultdict(list)
    for metric in metrics:
        by_observation[metric["observation_id"]].append(metric)
    for observation in observations:
        grouped[observation[grain]].append(observation)
    snapshots = {}
    for key, items in grouped.items():
        dated = [
            (datetime.fromisoformat(item["observed_at"].replace("Z", "+00:00")), item)
            for item in items
            if item["observed_at"]
        ]
        if not dated:
            snapshots[key] = {"observed_at": None}
            continue
        newest = max(at for at, _ in dated)
        values = defaultdict(set)
        for at, observation in dated:
            if at != newest:
                continue
            for metric in by_observation[observation["observation_id"]]:
                name = "comments" if metric["name"] == "comments_count" else metric["name"]
                value = metric["value"]
                metric_at = metric["observed_at"]
                if (
                    metric_at is None
                    or datetime.fromisoformat(metric_at.replace("Z", "+00:00")) != at
                    or metric["unit"] != "count"
                    or value is None
                    or not math.isfinite(value)
                    or value < 0
                    or not float(value).is_integer()
                ):
                    value = None
                else:
                    value = int(value)
                values[name].add(value)
        snapshots[key] = {
            "observed_at": newest.isoformat(),
            **{name: next(iter(counts)) if len(counts) == 1 else None for name, counts in values.items()},
        }
    return snapshots


def export_graph(
    connection: duckdb.DuckDBPyConnection, pointer: Record, coverage: list[Record], gaps: Counter[str]
) -> tuple[Record, dict[str, list[str]]]:
    """Export the full registered universe, admitting attribution only through reviewed relations."""
    tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    candidates = rows(
        connection,
        "SELECT * FROM entity WHERE kind='current_candidacy' AND validity='A' "
        "ORDER BY area_id,list_id,position,entity_id",
    )
    lists = rows(connection, "SELECT * FROM entity WHERE kind='local_list' ORDER BY area_id,entity_id")
    official_fields(connection, candidates, lists, gaps)
    sizes = Counter(candidate["list_id"] for candidate in candidates)
    city_sizes = Counter(candidate["area_id"] for candidate in candidates)
    city_lists = Counter(entity["area_id"] for entity in lists)
    cities = []
    for area in rows(connection, "SELECT * FROM area ORDER BY city_rank,area_id"):
        lon, lat = CITY_COORDS[area["name"]]
        cities.append(
            {
                "id": area["area_id"],
                "name": area["name"],
                "lon": lon,
                "lat": lat,
                "population": area["population"],
                "valid_candidacies": city_sizes[area["area_id"]],
                "retained_lists": city_lists[area["area_id"]],
            }
        )
    raw = {
        "source": {
            "kind": "real",
            **{key: pointer[key] for key in ("checkpoint_id", "created_at", "schema_version")},
            "exported_at": datetime.now(UTC).isoformat(),
        },
        "cities": cities,
        "lists": [
            {
                "id": entity["entity_id"],
                "city_id": entity["area_id"],
                "name": entity["name"],
                "short": entity["short"],
                "number": entity.get("number"),
                "size": sizes[entity["entity_id"]],
                "relevant": entity["qualified"],
            }
            for entity in lists
        ],
        "cands": [
            {
                "id": entity["entity_id"],
                "name": entity["name"],
                "list_id": entity["list_id"],
                "city_id": entity["area_id"],
                "position": entity["position"],
                "qualified": entity["qualified"],
                "age": entity.get("age"),
                "occupation": entity.get("occupation"),
                "photo": None,
                "photo_source": None,
            }
            for entity in candidates
        ],
        "accounts": [],
        "assets": [],
        "topics": [],
        "coverage": coverage,
    }
    entity_ids = {entity["id"] for entity in raw["cands"] + raw["lists"]}
    accounts_by_id = defaultdict(list)
    for account in rows(connection, "SELECT DISTINCT * FROM verified_accounts ORDER BY account_id,entity_id"):
        accounts_by_id[account["account_id"]].append(account)
    metrics = rows(
        connection,
        "SELECT * FROM metric WHERE name IN ('followers','views','likes','comments','comments_count','shares')",
    )
    account_snapshots = latest_snapshots(rows(connection, "SELECT * FROM account_observation"), metrics, "account_id")
    for account_id, accounts in accounts_by_id.items():
        owners = {account["entity_id"] for account in accounts}
        if len(owners) != 1 or not owners <= entity_ids:
            gaps["account_owner_ambiguous_or_outside_app_universe"] += 1
            continue
        account = accounts[0]
        snapshot = account_snapshots.get(account_id, {})
        raw["accounts"].append(
            {
                "id": account_id,
                "entity_id": account["entity_id"],
                "platform": account["platform"],
                "handle": account["handle"],
                "url": account["url"],
                "followers": snapshot.get("followers"),
                "followers_observed_at": snapshot.get("observed_at"),
            }
        )
    owners = {account["id"]: account["entity_id"] for account in raw["accounts"]}
    asset_observations = rows(
        connection, "SELECT * FROM asset_observation ORDER BY observed_at DESC NULLS LAST,observation_id"
    )
    if "production_observation" in tables:
        asset_observations += rows(connection, "SELECT * FROM production_observation")
        asset_observations.sort(key=lambda observation: observation["observed_at"] or "", reverse=True)
    asset_snapshots = latest_snapshots(asset_observations, metrics, "asset_id")
    relations = defaultdict(list)
    publications = defaultdict(set)
    for relation in rows(connection, "SELECT * FROM asset_relation WHERE status='confirmed'"):
        if relation["relation"] == "published_by":
            publications[relation["asset_id"]].add(relation["entity_id"])
        elif relation["relation"] in {"about", "mentions", "depicts"} and relation["entity_id"] in entity_ids:
            item = {"kind": relation["relation"], "entity_id": relation["entity_id"]}
            if item not in relations[relation["asset_id"]]:
                relations[relation["asset_id"]].append(item)
    previews = defaultdict(list)
    for observation in asset_observations:
        preview = observation["preview_url"]
        if preview and preview not in previews[observation["asset_id"]]:
            previews[observation["asset_id"]].append(preview)
    for asset in rows(connection, "SELECT * FROM verified_assets ORDER BY published_at DESC NULLS LAST,asset_id"):
        asset_id, account_id = asset["asset_id"], asset["owner_account_id"]
        if account_id not in owners or publications[asset_id] != {owners[account_id]}:
            gaps["asset_without_unique_verified_publication_owner"] += 1
            continue
        snapshot = asset_snapshots.get(asset_id, {})
        asset_type = ASSET_TYPES.get((asset["asset_type"] or "").lower())
        if asset_type is None:
            gaps["unknown_asset_type"] += 1
        raw["assets"].append(
            {
                "id": asset_id,
                "account_id": account_id,
                "owner_entity_id": owners[account_id],
                "platform": asset["platform"],
                "type": asset_type,
                "published_at": asset["published_at"],
                "text": asset["text"],
                "url": asset["url"],
                "image": None,
                "video": None,
                "video_mime": None,
                **{name: snapshot.get(name) for name in ("views", "likes", "comments", "shares", "observed_at")},
                "relations": relations[asset_id],
                "topics": [],
                "topic_status": None,
                "claims": [],
            }
        )
    by_asset = {asset["id"]: asset for asset in raw["assets"]}
    if "classification_coverage" in tables:
        for classification in rows(connection, "SELECT * FROM classification_coverage WHERE review_decision='accept'"):
            asset = by_asset.get(classification["asset_id"])
            if asset and classification["content_sha256"] == sha256((asset["text"] or "").encode()):
                asset["topic_status"] = "admitted"
    topic_ids = set()
    for claim in rows(connection, "SELECT * FROM claim ORDER BY claim_id"):
        if claim["review_status"] not in REVIEWED or claim["asset_id"] not in by_asset:
            gaps["claim_not_admitted_for_exported_asset"] += 1
            continue
        by_asset[claim["asset_id"]]["claims"].append(
            {
                "text": claim["text"],
                "quote": claim["evidence_quote"],
                "start_s": claim["time_start"],
                "end_s": claim["time_end"],
                "status": "admitted",
            }
        )
    links = rows(
        connection,
        "SELECT c.asset_id,ct.topic_id,ct.review_status FROM claim_topic ct "
        "JOIN claim c USING(claim_id) WHERE c.review_status IN ('independently_reviewed','admitted')",
    )
    if "asset_topic" in tables:
        links += rows(connection, "SELECT asset_id,topic_id,review_status FROM asset_topic")
    for link in links:
        if link["asset_id"] in by_asset and link["review_status"] in REVIEWED:
            asset = by_asset[link["asset_id"]]
            if link["topic_id"] not in asset["topics"]:
                asset["topics"].append(link["topic_id"])
            asset["topic_status"] = "admitted"
            topic_ids.add(link["topic_id"])
    for topic in rows(connection, "SELECT * FROM topic ORDER BY topic_id"):
        raw["topics"].append({"id": topic["topic_id"], "label": topic["label"], "status": "admitted"})
    if not topic_ids <= {topic["id"] for topic in raw["topics"]}:
        raise ValueError("Admitted topic link references an unknown topic")
    return raw, previews


def pending_labels(raw: Record, project: Path, gaps: Counter[str]) -> None:
    """Reuse producer review gates; pending labels never change checkpoint admission or ownership."""
    bundles = sorted((project / "data/production/classification").glob("bundle-*.json"))
    if not bundles:
        return
    module = project / ".claude/worktrees/production/src/czlake/production_labels.py"
    if not module.is_file():
        gaps["pending_review_gate_unavailable"] += 1
        return
    # run_path executes the stdlib-only producer gate without importing packages or writing pyc files.
    gate = runpy.run_path(str(module))
    assets = {asset["id"]: asset for asset in raw["assets"]}
    topics = {topic["id"]: topic for topic in raw["topics"]}
    seen_labels = {}
    for bundle_path in bundles:
        try:
            bundle = read_json(bundle_path)
        except (OSError, ValueError):
            gaps["pending_bundle_unavailable"] += 1
            continue
        if bundle["schema_version"] not in (1, "production-label-bundle-v1"):
            gaps["pending_bundle_unknown_schema"] += 1
            continue
        for packet in bundle["packets"]:
            try:
                documents = {}
                paths = {}
                for kind in ("cards", "labels", "review", "registry"):
                    reference = packet.get(kind, bundle.get(kind))
                    path = Path(reference if isinstance(reference, str) else reference["path"])
                    path = path if path.is_absolute() else bundle_path.parent / path
                    paths[kind] = path.resolve()
                    content = path.read_bytes()
                    if isinstance(reference, dict) and sha256(content) != reference["sha256"]:
                        raise ValueError("Pending artifact hash mismatch")
                    documents[kind] = json.loads(content)
                cards, registry = documents["cards"], documents["registry"]
                for kind, task_kind in (("labels", "classification"), ("review", "independent_review")):
                    registered = gate["registered_output"](paths[kind], registry, task_kind)
                    if gate["digest"](registered) != gate["digest"](documents[kind]):
                        raise ValueError("Pending output changed during validation")
                    assignment = next(
                        row for row in registry["assignments"] if row["assignment_id"] == registered["assignment_id"]
                    )
                    if sha256(paths["cards"].read_bytes()) != assignment["cards_sha256"]:
                        raise ValueError("Pending cards differ from registered input")
                result = gate["reviewed_records"](cards, documents["labels"], documents["review"], registry)
                if result["batch_hold"] or result["counts"]["reviewed"] != len(cards):
                    raise ValueError("Pending classification packet is held or incompletely reviewed")
            except (OSError, ValueError, KeyError, TypeError, StopIteration):
                gaps["pending_packet_failed_producer_review_gate"] += 1
                continue
            card_by_asset = {card["asset_id"]: card for card in cards}
            for label in result["verified"]:
                asset = assets.get(label["asset_id"])
                if asset is None:
                    gaps["pending_label_asset_not_in_checkpoint"] += 1
                    continue
                card = card_by_asset[asset["id"]]
                if (
                    card["entity_id"] != asset["owner_entity_id"]
                    or card["source_url"] != asset["url"]
                    or card["platform"] != asset["platform"]
                    or card["text"] != asset["text"]
                    or label["content_sha256"] != sha256((asset["text"] or "").encode())
                ):
                    gaps["pending_label_does_not_match_checkpoint_content_or_owner"] += 1
                    continue
                if asset["topic_status"] == "admitted":
                    continue
                label_hash = label["label_sha256"]
                if asset["id"] in seen_labels:
                    if seen_labels[asset["id"]] != label_hash:
                        # A disagreement between separately accepted pending packets needs promotion review.
                        asset.update(topics=[], topic_status=None, claims=[])
                        gaps["conflicting_pending_labels"] += 1
                    continue
                seen_labels[asset["id"]] = label_hash
                status = "reviewed_pending_promotion"
                names = sorted(set(label["topics"]) | {topic for claim in label["claims"] for topic in claim["topics"]})
                asset["topics"] = [f"{gate['VERSION']}:{name}" for name in names]
                asset["topic_status"] = status
                asset["claims"] = [
                    {"text": claim["text"], "quote": claim["text"], "start_s": None, "end_s": None, "status": status}
                    for claim in label["claims"]
                ]
                for name, topic_id in zip(names, asset["topics"], strict=True):
                    topics.setdefault(topic_id, {"id": topic_id, "label": name, "status": status})
    used = {topic_id for asset in raw["assets"] for topic_id in asset["topics"]}
    raw["topics"] = sorted(
        (topic for topic in topics.values() if topic["status"] == "admitted" or topic["id"] in used),
        key=lambda topic: topic["id"],
    )


def image_extension(content: bytes) -> str:
    """Accept image bytes rather than login/error HTML returned by expired CDN links."""
    if content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9"):
        return ".jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n") and b"IEND" in content[-16:]:
        return ".png"
    if content[:6] in (b"GIF87a", b"GIF89a") and content.endswith(b";"):
        return ".gif"
    if (
        content.startswith(b"RIFF")
        and content[8:12] == b"WEBP"
        and len(content) == int.from_bytes(content[4:8], "little") + 8
    ):
        return ".webp"
    if content[4:8] == b"ftyp" and (b"avif" in content[8:32] or b"avis" in content[8:32]):
        return ".avif"
    raise ValueError("Response is not a supported complete image")


def public_url(url: str) -> None:
    """Preview downloads must stay on public HTTP(S), including redirects."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Not a public preview URL")
    for address in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)):
        if not ipaddress.ip_address(address[4][0]).is_global:
            raise ValueError("Preview resolves to a non-public address")


class PublicRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def retain_preview(asset_id: str, urls: list[str], media: Path, cached: Record | None, download: bool) -> Record:
    """Reuse verified retained bytes, otherwise try only this asset's observed previews."""
    if cached:
        try:
            path = (media / cached["file"]).resolve()
            if path.parent != media.resolve():
                raise ValueError("Media cache path escapes directory")
            content = path.read_bytes()
            if sha256(content) == cached["sha256"] and cached["source_url"] in urls:
                image_extension(content)
                return cached
        except (OSError, ValueError, KeyError):
            pass
    result = {"asset_id": asset_id, "status": "no_observed_preview" if not urls else "download_disabled"}
    if not download:
        return result
    for url in urls:
        try:
            public_url(url)
            request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"})
            with build_opener(PublicRedirects()).open(request, timeout=15) as response:
                content = response.read(MAX_IMAGE_BYTES + 1)
            if len(content) > MAX_IMAGE_BYTES:
                raise ValueError("Preview exceeds byte limit")
            extension = image_extension(content)
            filename = sha256(asset_id.encode())[:24] + extension
            atomic_write(media / filename, content)
            return {
                "asset_id": asset_id,
                "status": "retained",
                "file": filename,
                "sha256": sha256(content),
                "bytes": len(content),
                "source_url": url,
                "fetched_at": datetime.now(UTC).isoformat(),
            }
        except HTTPError as error:
            result = {"asset_id": asset_id, "status": f"http_{error.code}"}
        except (URLError, OSError, ValueError):
            result = {"asset_id": asset_id, "status": "unavailable_or_invalid_image"}
    return result


def export_previews(
    raw: Record, previews: dict[str, list[str]], media: Path, workers: int, download: bool
) -> Counter[str]:
    """Retain previews concurrently without paid services or unobserved URL discovery."""
    media.mkdir(parents=True, exist_ok=True)
    index_path = media / ".previews.json"
    previous = read_json(index_path) if index_path.is_file() else {}
    index = {}
    counts = Counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                retain_preview, asset["id"], previews[asset["id"]], media, previous.get(asset["id"]), download
            ): asset
            for asset in raw["assets"]
        }
        for future in as_completed(futures):
            asset = futures[future]
            record = future.result()
            index[asset["id"]] = record
            counts[record["status"]] += 1
            if record["status"] == "retained":
                asset["image"] = "media/" + record["file"]
    atomic_write(index_path, (json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    return counts


def matching_parties(entity: Record) -> list[str]:
    """Match explicit official names/abbreviations; preserve name order, then abbreviation-only order."""
    name = "".join(c for c in unicodedata.normalize("NFD", entity["name"]) if not unicodedata.combining(c))
    short = "".join(c for c in unicodedata.normalize("NFD", entity["short"] or "") if not unicodedata.combining(c))
    folded_name, folded_short = name.lower(), short.lower()
    # DSZ is a separate party; its green-worded name cannot establish membership of Zelení.
    folded_name = re.sub(r"demokraticka strana zelenych", lambda match: " " * len(match[0]), folded_name)
    matches = []
    for key, (_, _, name_pattern, short_pattern) in PARTY_LOGOS.items():
        name_matches = list(re.finditer(name_pattern, folded_name))
        short_matches = list(re.finditer(short_pattern, folded_short))
        if key == "stan" and short_matches:
            name_matches += list(re.finditer(r"\bstarostove\b", folded_name))
        if key == "pro":
            # Uppercase PRO as a listed coalition member; exclude the preposition and local PRO names.
            name_matches += list(re.finditer(r"(?<!\w)PRO(?=\s*(?:[,;+)]|$))", name))
        if name_matches:
            matches.append((0, min(match.start() for match in name_matches), key))
        elif short_matches:
            matches.append((1, min(match.start() for match in short_matches), key))
    return [key for _, _, key in sorted(matches)]


def commons_url(url: str) -> None:
    """Constrain logo metadata, files and redirects to public Wikimedia Commons endpoints."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Invalid Commons URL")
    if parsed.hostname not in {"commons.wikimedia.org", "upload.wikimedia.org"}:
        raise ValueError("Logo request leaves Wikimedia Commons")
    if parsed.hostname == "upload.wikimedia.org" and not parsed.path.startswith("/wikipedia/commons/"):
        raise ValueError("Upload is not a Commons file")


class CommonsRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        commons_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def commons_bytes(url: str) -> bytes:
    """Fetch bounded public Commons bytes without credentials or other source-network calls."""
    commons_url(url)
    request = Request(url, headers={"User-Agent": "StarwatchLocalAssetPreparation/1.0"})
    with build_opener(CommonsRedirects()).open(request, timeout=20) as response:
        content = response.read(MAX_IMAGE_BYTES + 1)
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError("Commons response exceeds byte limit")
    return content


def logo_extension(content: bytes) -> str:
    """Accept complete PNG or passive SVG logos, excluding active or externally loaded SVG content."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return image_extension(content)
    if b"<!ENTITY" in content.upper():
        raise ValueError("SVG entity declarations are not allowed")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise ValueError("Not a valid SVG") from error
    if root.tag != "{http://www.w3.org/2000/svg}svg":
        raise ValueError("Not an SVG logo")
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].lower() in {"script", "foreignobject", "iframe"}:
            raise ValueError("Active SVG content")
        for key, value in node.attrib.items():
            local_key = key.rsplit("}", 1)[-1].lower()
            embedded_raster = node.tag.endswith("}image") and re.fullmatch(
                r"data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=\s]+", value
            )
            if local_key.startswith("on") or (
                local_key in {"href", "base"} and value and not value.startswith("#") and not embedded_raster
            ):
                raise ValueError("Active or external SVG attribute")
        styles = " ".join(node.attrib.values()) + (node.text or "" if node.tag.endswith("}style") else "")
        if "@import" in styles.lower() or any(
            not value.strip(" \"'").startswith("#") for value in re.findall(r"url\(([^)]+)\)", styles, re.IGNORECASE)
        ):
            raise ValueError("External SVG stylesheet resource")
    return ".svg"


def commons_retry(directory: Path, error: HTTPError) -> None:
    """Persist the provider's rate-limit window rather than retrying other files during it."""
    try:
        seconds = max(60, int(error.headers.get("Retry-After", "600")))
    except ValueError:
        seconds = 600
    record = {"status": error.code, "retry_not_before": (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()}
    atomic_write(directory / ".commons-retry.json", (json.dumps(record) + "\n").encode())


def export_logos(raw: Record, directory: Path, download: bool) -> Counter[str]:
    """Retain selected Commons logos and attach only parties explicitly named by the official lists."""
    directory.mkdir(parents=True, exist_ok=True)
    index_path = directory / ".logos.json"
    previous = read_json(index_path) if index_path.is_file() else {}
    index = {}
    counts: Counter[str] = Counter()
    for key, (party, title, _, _) in PARTY_LOGOS.items():
        cached = previous.get(key)
        if cached:
            try:
                path = (directory / cached["file"]).resolve()
                if path.parent != directory.resolve() or cached["title"] != "File:" + title or cached["party"] != party:
                    raise ValueError("Logo cache binding differs from the catalog")
                content = path.read_bytes()
                if sha256(content) != cached["sha256"] or not cached["license"]:
                    raise ValueError("Logo cache changed or has no license")
                commons_url(cached["source_url"])
                logo_extension(content)
                index[key] = cached
                counts["cached"] += 1
            except (OSError, ValueError, KeyError):
                pass
    missing = [key for key in PARTY_LOGOS if key not in index]
    retry_path = directory / ".commons-retry.json"
    if (
        missing
        and download
        and retry_path.is_file()
        and datetime.fromisoformat(read_json(retry_path)["retry_not_before"]) > datetime.now(UTC)
    ):
        counts["commons_retry_pending"] = len(missing)
        download = False
    if missing and download:
        query = urlencode(
            {
                "action": "query",
                "format": "json",
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|mime|size",
                "titles": "|".join("File:" + PARTY_LOGOS[key][1] for key in missing),
            }
        )
        try:
            catalog_path = directory / ".commons-metadata.json"
            pages = (
                {page["title"]: page for page in read_json(catalog_path)["query"]["pages"].values()}
                if catalog_path.is_file()
                else {}
            )
            if not all("File:" + PARTY_LOGOS[key][1] in pages for key in missing):
                catalog = commons_bytes("https://commons.wikimedia.org/w/api.php?" + query)
                atomic_write(catalog_path, catalog)
                pages = {page["title"]: page for page in json.loads(catalog)["query"]["pages"].values()}
            last_download = None
            for key in missing:
                party, title, _, _ = PARTY_LOGOS[key]
                page = pages["File:" + title]
                if "imageinfo" not in page:
                    counts["commons_file_not_found"] += 1
                    continue
                info = page["imageinfo"][0]
                metadata = info["extmetadata"]
                try:
                    license_name = metadata["LicenseShortName"]["value"]
                    if not license_name or info["mime"] not in {"image/svg+xml", "image/png"}:
                        raise ValueError("Missing logo license or unsupported file type")
                    url = info["url"].split("?", 1)[0]
                    commons_url(info["descriptionurl"])
                    if last_download is not None:
                        time.sleep(max(0, 10 - (time.monotonic() - last_download)))
                    last_download = time.monotonic()
                    content = commons_bytes(url)
                    extension = logo_extension(content)
                    filename = key + extension
                    atomic_write(directory / filename, content)
                    index[key] = {
                        "party": party,
                        "title": page["title"],
                        "file": filename,
                        "source_url": info["descriptionurl"],
                        "download_url": url,
                        "license": license_name,
                        "license_url": metadata.get("LicenseUrl", {}).get("value"),
                        "artist": unescape(re.sub(r"<[^>]*>", "", metadata.get("Artist", {}).get("value", ""))),
                        "credit": unescape(re.sub(r"<[^>]*>", "", metadata.get("Credit", {}).get("value", ""))),
                        "attribution_required": metadata.get("AttributionRequired", {}).get("value"),
                        "sha256": sha256(content),
                        "bytes": len(content),
                        "fetched_at": datetime.now(UTC).isoformat(),
                    }
                    counts["downloaded"] += 1
                except HTTPError as error:
                    counts[f"commons_file_http_{error.code}"] += 1
                    if error.code == 429:
                        commons_retry(directory, error)
                        break
                except (OSError, ValueError, KeyError):
                    counts["commons_file_unavailable_or_invalid"] += 1
        except HTTPError as error:
            counts[f"commons_metadata_http_{error.code}"] += 1
            if error.code == 429:
                commons_retry(directory, error)
        except (OSError, ValueError, KeyError):
            counts["commons_metadata_unavailable"] += 1
    atomic_write(index_path, (json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    for entity in raw["lists"]:
        keys = matching_parties(entity)
        entity["logos"] = [
            {
                "party": index[key]["party"],
                "path": "media/logos/" + index[key]["file"],
                "source_url": index[key]["source_url"],
                "license": index[key]["license"],
            }
            for key in keys
            if key in index
        ]
        counts["mapped_lists" if entity["logos"] else "unmapped_lists"] += 1
        counts["logo_links"] += len(entity["logos"])
        counts["named_parties_without_logo"] += sum(key not in index for key in keys)
    counts["available_logos"] = len(index)
    return counts


def export_portraits(raw: Record, records: list[Record], project: Path, directory: Path) -> Counter[str]:
    """Expose source-labelled portraits or verified owned-account avatars without face inference."""
    directory.mkdir(parents=True, exist_ok=True)
    candidates = {candidate["id"]: candidate for candidate in raw["cands"]}
    owners = {account["id"]: account["entity_id"] for account in raw.get("accounts", [])}
    index = {}
    counts: Counter[str] = Counter()
    for record in records:
        candidate = candidates.get(record["entity_id"])
        if candidate is None or candidate["photo"]:
            continue
        try:
            if record["kind"] not in {"source_bound_portrait", "owned_account_avatar"}:
                raise ValueError("Image is not a labelled portrait or owned-account avatar")
            if record["kind"] == "owned_account_avatar" and owners.get(record.get("account_id")) != candidate["id"]:
                raise ValueError("Avatar account does not have a unique verified candidate owner")
            source_path, blob_path = Path(record["source_path"]).resolve(), Path(record["local_path"]).resolve()
            if not source_path.is_relative_to(project) or not blob_path.is_relative_to(project):
                raise ValueError("Portrait source leaves the project")
            if record["source_sha256"] != record["source_page_sha256"] or record["source_bytes"] > 64 * 1024 * 1024:
                raise ValueError("Portrait source binding differs")
            if (record["blob_path"], record["blob_sha256"], record["blob_bytes"]) != (
                record["local_path"],
                record["sha256"],
                record["bytes"],
            ):
                raise ValueError("Portrait blob differs from pinned source")
            source_content = source_path.read_bytes()
            if len(source_content) != record["source_bytes"] or sha256(source_content) != record["source_sha256"]:
                raise ValueError("Portrait source bytes changed")
            selected = json.loads(source_content)
            for component in record["source_image_pointer"].lstrip("/").split("/"):
                component = component.replace("~1", "/").replace("~0", "~")
                selected = selected[int(component)] if isinstance(selected, list) else selected[component]
            if selected != record["original_image_url"] or record["bytes"] > MAX_IMAGE_BYTES:
                raise ValueError("Portrait image is not the exact recorded source image")
            content = blob_path.read_bytes()
            if len(content) != record["bytes"] or sha256(content) != record["sha256"]:
                raise ValueError("Portrait bytes changed")
            extension = image_extension(content)
            mime = {
                ".jpg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".webp": "image/webp",
                ".avif": "image/avif",
            }[extension]
            if mime != record["content_type"]:
                raise ValueError("Portrait MIME type differs")
            filename = sha256(record["image_id"].encode())[:24] + extension
            atomic_write(directory / filename, content)
            candidate.update(
                photo="media/portraits/" + filename,
                photo_source=record["source_page_url"],
                photo_kind=record["kind"],
                photo_depicted_person_status=record["depicted_person_status"],
                photo_observed_at=record["observed_at"],
            )
            index[candidate["id"]] = {
                "image_id": record["image_id"],
                "file": filename,
                "sha256": record["sha256"],
                "source_url": record["source_page_url"],
                "observed_at": record["observed_at"],
            }
            counts["mapped_candidates"] += 1
            counts["mapped_" + record["kind"]] += 1
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            counts["portrait_unavailable_or_changed"] += 1
    counts["unmapped_candidates"] = len(candidates) - len(index)
    counts["admitted_portrait_records"] = len(records)
    atomic_write(directory / ".portraits.json", (json.dumps(index, sort_keys=True, indent=2) + "\n").encode())
    return counts


def retain_video(resource: Record, project: Path, media: Path) -> Record:
    """Copy hash-bound checkpoint media atomically without modifying producer files."""
    record = {"media_id": resource["media_id"], "asset_id": resource["asset_id"]}
    source = Path(resource["local_path"]).resolve()
    allowed = (project / "data/production/media", project / "tmp/production")
    if not any(source.is_relative_to(root.resolve()) for root in allowed):
        return {**record, "status": "invalid_source_path"}
    filename = sha256(resource["media_id"].encode())[:24] + ".mp4"
    fd, temporary = tempfile.mkstemp(prefix=".video-", dir=media)
    try:
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(fd, "wb") as output, source.open("rb") as stream:
            header = stream.read(32)
            if header[4:8] != b"ftyp" or resource["content_type"] != "video/mp4":
                return {**record, "status": "invalid_video_type"}
            output.write(header)
            digest.update(header)
            size += len(header)
            while chunk := stream.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            output.flush()
            os.fsync(output.fileno())
        if size != resource["bytes"] or digest.hexdigest() != resource["sha256"]:
            return {**record, "status": "video_bytes_changed"}
        destination = media / filename
        os.replace(temporary, destination)
        duration = None
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(destination)],
                capture_output=True,
                timeout=15,
                check=True,
            )
            value = float(json.loads(probe.stdout)["format"]["duration"])
            if math.isfinite(value) and value > 0:
                duration = value
        except (OSError, subprocess.SubprocessError, ValueError, KeyError):
            pass
        return {
            **record,
            "status": "retained",
            "file": filename,
            "sha256": digest.hexdigest(),
            "bytes": size,
            "video_mime": "video/mp4",
            "duration_s": duration,
        }
    except FileNotFoundError:
        return {**record, "status": "missing_file"}
    except OSError:
        return {**record, "status": "video_file_unavailable"}
    finally:
        Path(temporary).unlink(missing_ok=True)


def export_videos(raw: Record, resources: list[Record], project: Path, media: Path, workers: int) -> Counter[str]:
    """Export one real retained video per admitted asset, falling back across its media resources."""
    media.mkdir(parents=True, exist_ok=True)
    by_asset = defaultdict(list)
    for resource in resources:
        by_asset[resource["asset_id"]].append(resource)
    index = {}
    counts: Counter[str] = Counter()

    def export_asset(asset: Record) -> tuple[Record | None, list[Record]]:
        attempts = []
        for resource in by_asset[asset["id"]]:
            record = retain_video(resource, project, media)
            attempts.append(record)
            if record["status"] == "retained":
                return record, attempts
        return None, attempts

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(export_asset, asset): asset for asset in raw["assets"] if asset["id"] in by_asset}
        for future in as_completed(futures):
            asset = futures[future]
            record, attempts = future.result()
            index[asset["id"]] = {"selected": record, "attempts": attempts}
            counts.update(attempt["status"] for attempt in attempts)
            if record:
                asset["video"] = "media/" + record["file"]
                asset["video_mime"] = record["video_mime"]
                if record["duration_s"] is not None:
                    asset["duration_s"] = record["duration_s"]
    counts["assets_without_retained_video"] = sum(asset["video"] is None for asset in raw["assets"])
    counts["downloaded_resources"] = len(resources)
    counts["downloaded_video_assets"] = len(by_asset)
    atomic_write(media / ".videos.json", (json.dumps(index, sort_keys=True, indent=2) + "\n").encode())
    return counts


def export_forecasts(raw: Record, path: Path) -> Counter[str]:
    """Attach published values only to an exact, unique official name/abbreviation in the same city."""
    counts: Counter[str] = Counter()
    for entity in raw["lists"] + raw["cands"]:
        entity["forecast"] = []
    if not path.is_file():
        counts["file_missing"] = 1
        return counts
    document = read_json(path)
    datetime.fromisoformat(document["generated_at"].replace("Z", "+00:00"))
    sources = {}
    for source in document["sources"]:
        source_id = source["id"]
        if not isinstance(source_id, str) or not source_id or source_id in sources:
            raise ValueError("Forecast source IDs must be unique nonempty strings")
        if source["kind"] not in {"poll", "model", "betting", "ranking"}:
            raise ValueError("Unknown forecast source kind")
        for field in ("publisher", "fieldwork_or_published", "method_note", "url"):
            if not isinstance(source[field], str) or not source[field].strip():
                raise ValueError("Forecast source lacks provenance")
        parsed = urlsplit(source["url"])
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Forecast source is not a public web URL")
        sample = source["sample_size"]
        if sample is not None and (type(sample) is not int or sample <= 0):
            raise ValueError("Invalid forecast sample size")
        sources[source_id] = source
    counts["sources"] = len(sources)
    cities = {city["name"]: city["id"] for city in raw["cities"]}
    if set(document["cities"]) != set(cities):
        raise ValueError("Forecast coverage must explicitly contain every exported city")
    # No case-folding, accent removal, coalition aliases or component-party matching.
    indexes: dict[str, dict[tuple[str, str], set[str]]] = {}
    entities = {entity["id"]: entity for entity in raw["lists"] + raw["cands"]}
    for group, records in (("lists", raw["lists"]), ("candidates", raw["cands"])):
        index: dict[tuple[str, str], set[str]] = defaultdict(set)
        for entity in records:
            names = {entity["name"]}
            if group == "lists" and entity.get("short"):
                names.add(entity["short"])
            for name in names:
                index[(entity["city_id"], name)].add(entity["id"])
        indexes[group] = index
    for city, forecast in document["cities"].items():
        present = bool(forecast["lists"] or forecast["candidates"])
        if forecast["status"] != ("found" if present else "none_found"):
            raise ValueError("Forecast status disagrees with retained values")
        counts["cities_" + forecast["status"]] += 1
        for group, id_field in (("lists", "list_id_2026"), ("candidates", "cand_id_2026")):
            for record in forecast[group]:
                source = sources[record["source_id"]]
                value, unit = record["value"], record["unit"]
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError("Forecast value must be a finite nonnegative number")
                if unit not in {"pct", "seats", "odds"}:
                    raise ValueError("Unknown forecast unit")
                if (unit == "pct" and value > 100) or (unit == "seats" and not float(value).is_integer()):
                    raise ValueError("Invalid forecast percentage or seat count")
                if unit == "odds" and (source["kind"] != "betting" or value < 1):
                    raise ValueError("Decimal betting odds require a betting source and value >= 1")
                if group == "candidates" and record["role"] not in {"mayor_candidate", "other"}:
                    raise ValueError("Unknown forecast candidacy role")
                counts[group + "_values"] += 1
                entity_id = record[id_field]
                if entity_id is None:
                    counts[group + "_unmatched"] += 1
                    continue
                matches = indexes[group].get((cities[city], record["name_as_published"]), set())
                if matches != {entity_id}:
                    counts[group + "_match_rejected"] += 1
                    continue
                item = {
                    "value": value,
                    "unit": unit,
                    "kind": source["kind"],
                    "publisher": source["publisher"],
                    "date": source["fieldwork_or_published"],
                    "url": source["url"],
                }
                if item not in entities[entity_id]["forecast"]:
                    entities[entity_id]["forecast"].append(item)
                    counts[group + "_exported"] += 1
    counts["matched_lists"] = sum(bool(entity["forecast"]) for entity in raw["lists"])
    counts["matched_candidates"] = sum(bool(entity["forecast"]) for entity in raw["cands"])
    return counts


def platform_coverage(raw: Record) -> list[Record]:
    """Count exported verified records once, with absence explicit for every supported platform."""
    accounts = Counter(account["platform"] for account in raw["accounts"])
    assets = Counter(asset["platform"] for asset in raw["assets"])
    videos = Counter(asset["platform"] for asset in raw["assets"] if asset["video"])
    return [
        {
            "platform": platform,
            "verified_accounts": accounts[platform],
            "verified_assets": assets[platform],
            "playable_videos": videos[platform],
            "status": "observed" if assets[platform] else "accounts_only" if accounts[platform] else "not_collected",
        }
        for platform in PLATFORMS
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--no-download", action="store_true", help="Reuse local previews/logos without network requests"
    )
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        parser.error("--workers must be between 1 and 16")
    app = Path(__file__).resolve().parents[1]
    project = args.project.resolve()
    pointer, database, coverage = pinned_checkpoint(project / "tmp/production/read")
    gaps: Counter[str] = Counter()
    with duckdb.connect(str(database), read_only=True) as connection:
        raw, previews = export_graph(connection, pointer, coverage, gaps)
        tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
        video_resources = (
            rows(
                connection,
                "SELECT m.* FROM media_resource m JOIN verified_assets a USING(asset_id) "
                "WHERE m.kind='video' AND m.status='downloaded' "
                "ORDER BY m.asset_id,m.source_pointer,m.media_id",
            )
            if "media_resource" in tables
            else []
        )
        portrait_records = (
            rows(
                connection,
                "SELECT i.*,s.path AS source_path,s.sha256 AS source_sha256,s.bytes AS source_bytes,"
                "b.path AS blob_path,b.sha256 AS blob_sha256,b.bytes AS blob_bytes FROM source_image i "
                "JOIN source s ON s.source_id=i.source_page_id JOIN source b ON b.source_id=i.blob_source_id "
                "WHERE i.kind IN ('source_bound_portrait','owned_account_avatar') "
                "AND i.relation_status='source_identified' "
                "AND i.download_status='downloaded' AND i.depicted_person_status='unknown' "
                "ORDER BY i.entity_id,CASE WHEN i.kind='source_bound_portrait' THEN 0 ELSE 1 END,"
                "i.observed_at DESC,i.image_id",
            )
            if "source_image" in tables
            else []
        )
    election_counts = export_election_results(raw, project)
    pending_labels(raw, project, gaps)
    forecast_counts = export_forecasts(raw, app / "web/data/forecasts.json")
    print(
        json.dumps(
            {
                "checkpoint": pointer["checkpoint_id"],
                "counts": {key: len(raw[key]) for key in ("cities", "lists", "cands", "accounts", "assets", "topics")},
            },
            sort_keys=True,
        ),
        flush=True,
    )
    media_counts = export_previews(raw, previews, app / "web/media", args.workers, not args.no_download)
    video_counts = export_videos(raw, video_resources, project, app / "web/media", args.workers)
    logo_counts = export_logos(raw, app / "web/media/logos", not args.no_download)
    portrait_counts = export_portraits(raw, portrait_records, project, app / "web/media/portraits")
    portrait_counts["source_image_table_present"] = int("source_image" in tables)
    raw["platform_coverage"] = platform_coverage(raw)
    script = "window.SW_RAW = " + json.dumps(raw, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + ";\n"
    # Escape script-sensitive separators so this remains safe even when embedded in HTML.
    script = script.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029").replace("</", "<\\/")
    atomic_write(app / "web/data/real.js", script.encode())
    summary = {
        "checkpoint_id": pointer["checkpoint_id"],
        "exported_at": raw["source"]["exported_at"],
        "counts": {
            key: len(raw[key]) for key in ("cities", "lists", "cands", "accounts", "assets", "topics", "coverage")
        },
        "claims": sum(len(asset["claims"]) for asset in raw["assets"]),
        "pending_assets": sum(asset["topic_status"] == "reviewed_pending_promotion" for asset in raw["assets"]),
        "unclassified_assets": sum(asset["topic_status"] is None for asset in raw["assets"]),
        "accounts_without_follower_count": sum(account["followers"] is None for account in raw["accounts"]),
        "unknown_asset_metrics": {
            name: sum(asset[name] is None for asset in raw["assets"])
            for name in ("views", "likes", "comments", "shares")
        },
        "previews": dict(media_counts),
        "videos": dict(video_counts),
        "logos": dict(logo_counts),
        "portraits": dict(portrait_counts),
        "forecasts": dict(forecast_counts),
        "election_results2022": dict(election_counts),
        "platform_coverage": raw["platform_coverage"],
        "gaps": dict(gaps),
    }
    atomic_write(app / "web/media/.export-summary.json", (json.dumps(summary, indent=2) + "\n").encode())
    print(json.dumps(summary, sort_keys=True), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, duckdb.Error) as error:
        # Avoid printing exception messages that can contain signed URLs or source content.
        print(f"Export failed ({type(error).__name__}); previous real.js retained.", file=sys.stderr)
        raise SystemExit(1) from None
