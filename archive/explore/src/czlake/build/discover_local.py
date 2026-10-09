"""Bounded public-source discovery for every municipal list and leader.

Search completion is stored separately from hits so empty results do not cause
duplicate paid queries. Raw query-to-entity mappings make interrupted runs
recoverable. No search result is automatically treated as verified identity.
"""
from __future__ import annotations

import argparse
import hashlib
import json

import pyarrow as pa

from .. import lakehouse as lh
from ..apify_run import run_actor
from ..land import manifest_append, now_iso
from ..paths import RAW
from ..scope import TOP_CITY_RANK
from .discover_accounts import SITES, completed_people, plat_handle


def prepare(kind: str) -> list[dict]:
    con = lh.duck()
    if kind == "leaders":
        records = con.sql(f"""
            select leader_person_id as entity_id, leader_name as name, city, municipality_code,
                   population_rank, list_no, list_name
            from marts.city_2026_contenders where population_rank <= {TOP_CITY_RANK} order by population_rank, list_no
        """).to_arrow_table().to_pylist()
        prior = completed_people(con)
        records = [row for row in records if row["entity_id"] not in prior]
    elif kind == "lists":
        records = con.sql(f"""
            select md5(municipality_code || ':' || list_no) as entity_id,
                   list_name as name, city, municipality_code, population_rank, list_no, list_name
            from marts.city_2026_contenders where population_rank <= {TOP_CITY_RANK} order by population_rank, list_no
        """).to_arrow_table().to_pylist()
    elif kind == "topics":
        records = con.sql(f"""
            select municipality_code as entity_id, city as name, city, municipality_code,
                   population_rank, null::varchar as list_no, null::varchar as list_name
            from marts.city_profile where population_rank <= {TOP_CITY_RANK} order by population_rank
        """).to_arrow_table().to_pylist()
    else:
        raise ValueError(kind)
    records = [row for row in records if row["population_rank"] <= TOP_CITY_RANK]
    for row in records:
        row["kind"] = kind
        if kind == "topics":
            row["query"] = f'"{row["city"]}" komunální volby 2026 program doprava bydlení after:2026-04-09 before:2026-10-09'
        else:
            row["query"] = f'"{row["name"]}" "{row["city"]}" {SITES}'
        row["query_id"] = hashlib.sha256((kind + ":" + row["query"]).encode()).hexdigest()
    return records


def stage(raw_path, mappings: list[dict]) -> dict:
    from pathlib import Path

    raw = json.loads(Path(raw_path).read_text())
    by_query = {row["query"]: row for row in mappings}
    hits, completed = [], []
    for page in raw["items"]:
        term = (page.get("searchQuery") or {}).get("term")
        if term not in by_query:
            continue
        mapping = by_query[term]
        error = page.get("error") or page.get("errorMessage")
        completed.append(mapping | {"apify_run_id": raw["run_id"], "fetched_at": raw["fetched_at"],
                                   "status": "failed" if error else "completed",
                                   "n_results": len(page.get("organicResults") or []), "error": str(error) if error else None})
        for rank, result in enumerate(page.get("organicResults") or [], 1):
            platform, handle = plat_handle(result.get("url", ""))
            hits.append(mapping | {"rank": rank, "url": result.get("url"), "title": result.get("title"),
                                   "description": result.get("description"), "platform": platform, "handle": handle,
                                   "apify_run_id": raw["run_id"], "fetched_at": raw["fetched_at"]})
    con = lh.duck()
    try:
        landed = con.sql(f"select count(*) from staging.local_discovery_query where apify_run_id='{raw['run_id']}'").fetchall()[0][0]
    except Exception:  # noqa: BLE001 - first landing has no table yet
        landed = 0
    if landed:
        return {"already_staged": raw["run_id"]}
    if hits:
        lh.write("staging", "local_discovery_hit", pa.Table.from_pylist(hits), mode="append")
        leader_hits = [{"person_id": hit["entity_id"], **{key: hit[key] for key in
            ("query", "rank", "url", "title", "description", "platform", "handle", "apify_run_id", "fetched_at")}}
            for hit in hits if hit["kind"] == "leaders"]
        if leader_hits:
            lh.write("staging", "serp_social_hits", pa.Table.from_pylist(leader_hits), mode="append")
    if completed:
        lh.write("staging", "local_discovery_query", pa.Table.from_pylist(completed), mode="append")
    return {"run_id": raw["run_id"], "queries_completed": len(completed), "hits": len(hits)}


def run(kind: str, batch_size: int = 200, limit: int | None = None) -> dict:
    con = lh.duck()
    done = set()
    try:
        done = {row[0] for row in con.sql("select query_id from staging.local_discovery_query where status='completed'").fetchall()}
    except Exception:  # noqa: BLE001 - first pass has no query table
        done = set()
    records = [row for row in prepare(kind) if row["query_id"] not in done]
    if limit is not None:
        records = records[:limit]
    for start in range(0, len(records), batch_size):
        chunk = records[start:start + batch_size]
        identifier = hashlib.sha256("\n".join(row["query_id"] for row in chunk).encode()).hexdigest()[:20]
        path = RAW / "discovery_mappings" / f"{kind}_{identifier}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(chunk, ensure_ascii=False, indent=2))
        inp = {"queries": "\n".join(row["query"] for row in chunk), "maxPagesPerQuery": 1,
               "countryCode": "cz", "searchLanguage": "cs", "languageCode": "cs", "mobileResults": False,
               "saveHtml": False, "saveHtmlToKeyValueStore": False, "includeUnfilteredResults": False,
               "maximumLeadsEnrichmentRecords": 0, "focusOnPaidAds": False,
               "aiOverview": {"scrapeFullAiOverview": False}, "aiModeSearch": {"enableAiMode": False},
               "websiteContentScraper": {"enable": False}}
        result = run_actor("apify/google-search-scraper", inp, max(0.5, round(len(chunk) * 0.0025 * 1.2 + 0.01, 3)),
                           f"Local 2026 {kind} discovery; mapping {path.name}", landing=f"local_{kind}", timeout_s=1800)
        manifest_append({"source": "local_discovery_mapping", "source_url": "https://volby.gov.cz/opendata/kv2026/",
                         "fetched_at": now_iso(), "apify_run_id": result["run_id"], "path": str(path),
                         "bytes": path.stat().st_size})
        print(json.dumps(stage(result["raw_path"], chunk) | {"usd": result["usage_total_usd"]}), flush=True)
    return {"kind": kind, "queries_requested": len(records)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["leaders", "lists", "topics"])
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--limit", type=int)
    arguments = parser.parse_args()
    print(run(arguments.kind, arguments.batch_size, arguments.limit))
