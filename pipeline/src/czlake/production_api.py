"""Local read-only HTTP adapter for immutable Starwatch production checkpoints.

No provider calls, checkpoint writes, arbitrary SQL or raw source-file routes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

import duckdb

VERSION = "starwatch-production-api/1.5.0"
DEFAULT_ROOT = Path("/home/vecera/code/agents007-hackathon/tmp/production/read")
REVIEWED = "('admitted','independently_reviewed')"
ACCOUNT_ADMISSION = "(SELECT * FROM verified_accounts QUALIFY row_number() OVER(PARTITION BY account_id,entity_id ORDER BY reviewed_at DESC NULLS LAST,evidence_url NULLS LAST)=1)"
BASE_TABLES = {"area", "entity", "account", "account_observation", "account_relation", "asset", "asset_observation", "asset_relation", "metric", "claim", "topic", "claim_topic", "verified_accounts", "verified_assets"}
FILTERS = {
    "cities": {"area_id", "q"},
    "entities": {"area_id", "list_id", "kind", "selection_status", "qualified", "scope", "q"},
    "accounts": {"area_id", "entity_id", "platform", "q"},
    "assets": {"area_id", "entity_id", "account_id", "platform", "asset_type", "relation", "topic_id", "since", "until", "q"},
    "claims": {"area_id", "entity_id", "asset_id", "topic_id", "q"},
    "topics": {"area_id", "entity_id", "asset_id", "platform", "since", "until", "q"},
    "metrics": {"area_id", "entity_id", "account_id", "asset_id", "platform", "name", "since", "until", "mode"},
    "coverage": {"area_id"},
    "web-assets": {"reported_publisher_id", "asset_type", "q"},
    "publishers": {"kind", "q"},
    "photos": {"entity_id", "area_id", "kind", "download_status", "relation_status"},
    "photo-coverage": {"entity_id", "area_id", "status"},
    "media": {"asset_id", "entity_id", "area_id", "kind", "status"},
    "election-lists": {"area_id", "election_id", "q"},
    "election-candidates": {"area_id", "election_id", "list_result_id", "elected", "q"},
    "election-links": {"entity_id", "area_id", "election_id", "result_kind", "match_status", "q"},
}


class APIError(Exception):
    def __init__(self, status, code, message, headers=None):
        self.status, self.code, self.message = status, code, message
        self.headers = headers or {}
        super().__init__(message)


def fail(status, code, message, headers=None):
    raise APIError(status, code, message, headers)


def json_bytes(path, maximum):
    with path.open("rb") as stream:
        content = stream.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError("Metadata exceeds limit")
    return content, json.loads(content)


def checked_path(root, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError("Expected relative checkpoint path")
    parts = Path(relative).parts
    if any(part in {"..", "."} or part.startswith(".building-") for part in parts):
        raise ValueError("Unsafe checkpoint path")
    path = root / relative
    for parent in [path, *path.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError("Checkpoint paths must not be symlinks")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root / "checkpoints") or not resolved.is_file():
        raise ValueError("Checkpoint path escapes immutable root")
    return resolved


def verify_file(path, specification):
    if not isinstance(specification, dict) or type(specification.get("bytes")) is not int or not re.fullmatch(r"[a-f0-9]{64}", str(specification.get("sha256", ""))):
        raise ValueError("Missing checkpoint file digest")
    sha = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        while content := stream.read(1024 * 1024):
            count += len(content)
            sha.update(content)
    if count != specification["bytes"] or sha.hexdigest() != specification["sha256"]:
        raise ValueError("Checkpoint file digest mismatch")


class PinnedCheckpoint:
    """One pointer read followed by verified immutable files and a read-only connection."""
    def __init__(self, root, requested_id=None):
        self.root = Path(root).resolve()
        try:
            _, pointer = json_bytes(self.root / "current.json", 65536)
            if not isinstance(pointer, dict):
                raise ValueError("Pointer must be an object")
            checkpoint_id = pointer["checkpoint_id"]
            if not isinstance(checkpoint_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", checkpoint_id) or checkpoint_id.startswith(".building-"):
                raise ValueError("Invalid checkpoint identifier")
            expected = f"checkpoints/{checkpoint_id}/"
            if pointer["manifest"] != expected + "manifest.json" or pointer["database"] != expected + "graph.duckdb":
                raise ValueError("Checkpoint path/identity mismatch")
            manifest_path = checked_path(self.root, pointer["manifest"])
            database = checked_path(self.root, pointer["database"])
            content, manifest = json_bytes(manifest_path, 16 * 1024 * 1024)
            if hashlib.sha256(content).hexdigest() != pointer["manifest_sha256"]:
                raise ValueError("Manifest hash mismatch")
            for field in ("checkpoint_id", "created_at", "schema_version"):
                if pointer[field] != manifest[field]:
                    raise ValueError("Pointer and manifest disagree")
            if not re.fullmatch(r"starwatch-production-graph/1\.\d+\.\d+", pointer["schema_version"]):
                raise ValueError("Unsupported graph version")
            if manifest.get("quality", {}).get("status") != "passed" or not str(manifest.get("status", "")).startswith("validated"):
                raise ValueError("Checkpoint not validated")
            verify_file(database, manifest["files"]["graph.duckdb"])
            coverage_path = checked_path(self.root, expected + "coverage.json")
            verify_file(coverage_path, manifest["files"]["coverage.json"])
            _, coverage = json_bytes(coverage_path, 16 * 1024 * 1024)
            if not isinstance(coverage, list) or not all(isinstance(row, dict) and isinstance(row.get("area_id"), str) for row in coverage):
                raise ValueError("Coverage must contain city rows")
            self.pointer, self.manifest, self.database, self.coverage = pointer, manifest, database, coverage
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            fail(503, "checkpoint_unavailable", "No valid production checkpoint is available.")
        if requested_id is not None and requested_id != checkpoint_id:
            fail(409, "checkpoint_changed", "The current checkpoint changed; restart the screen request.")
        self.connection = None

    def __enter__(self):
        try:
            self.connection = duckdb.connect(str(self.database), read_only=True, config={"enable_external_access": "false", "autoload_known_extensions": "false", "autoinstall_known_extensions": "false"})
            self.tables = {row[0] for row in self.connection.execute("SHOW TABLES").fetchall()}
            if not BASE_TABLES <= self.tables:
                raise ValueError("Required graph tables missing")
        except (duckdb.Error, ValueError):
            if self.connection:
                self.connection.close()
            fail(503, "checkpoint_unavailable", "No compatible production checkpoint is available.")
        return self

    def __exit__(self, *_):
        self.connection.close()

    def rows(self, sql, values=()):
        cursor = self.connection.execute(sql, list(values))
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def current_classification_condition(self):
        if "classification_coverage" not in self.tables:
            return None
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info('classification_coverage')").fetchall()}
        return '"current"=true' if "current" in columns else "true"

    def classification_summary(self):
        condition = self.current_classification_condition()
        if condition is None:
            return {"status": "not_reported", "scope": "checkpoint", "current_assets": None, "packet_history_rows": None}
        count = self.rows("SELECT count(*) total FROM classification_coverage")[0]["total"]
        current = self.rows(f"SELECT review_decision,count(*) AS packet_rows,count(DISTINCT asset_id) AS asset_count FROM classification_coverage WHERE {condition} GROUP BY review_decision ORDER BY review_decision")
        return {"status": "reported", "scope": "checkpoint", "packet_history_rows": count, "current_assets": self.rows(f"SELECT count(DISTINCT asset_id) total FROM classification_coverage WHERE {condition}")[0]["total"], "current_decisions": current}

    def identity(self):
        return {key: self.pointer[key] for key in ("checkpoint_id", "created_at", "schema_version", "manifest_sha256")} | {"api_version": VERSION, "data_mode": "cached"}

    def gaps(self):
        gaps = [{"code": "incomplete_history", "message": "Retained observations do not establish complete posting histories, audience location, support or growth."}, {"code": "source_statement_not_verified_truth", "message": "Reviewed claims are source statements; attribution and truth are separate."}, {"code": "remote_preview_not_retained_media", "message": "Observation preview/video URLs are remote source URLs; asset image/video URLs are checkpoint-bound retained media, verified on blob reads."}]
        if not self.rows(f"SELECT count(*) AS total FROM claim c JOIN verified_assets a USING(asset_id) WHERE c.review_status IN {REVIEWED}")[0]["total"]:
            gaps.append({"code": "claims_not_available", "message": "No independently reviewed claims are admitted in this checkpoint."})
        links = topic_link(self)
        if not self.rows(f"SELECT count(*) AS total FROM {links} tl JOIN verified_assets a USING(asset_id)")[0]["total"]:
            gaps.append({"code": "topics_not_available", "message": "No independently reviewed topic links are admitted in this checkpoint."})
        if "media_resource" not in self.tables:
            gaps.append({"code": "media_retention_not_reported", "message": "This checkpoint has no retained-media metadata."})
        if "classification_coverage" not in self.tables:
            gaps.append({"code": "classification_coverage_not_reported", "message": "This checkpoint has no per-asset classification coverage."})
        return gaps


def parameters(resource, query, *, detail=False):
    if len(query) > 4096:
        fail(400, "invalid_query", "Query is too long.")
    try:
        parsed = parse_qs(query, keep_blank_values=True, strict_parsing=True, max_num_fields=24, errors="strict")
    except (ValueError, UnicodeError):
        fail(400, "invalid_query", "Malformed query.")
    allowed = {"checkpoint_id"} if detail else FILTERS.get(resource, set()) | {"limit", "offset", "checkpoint_id"}
    if set(parsed) - allowed or any(len(values) != 1 or not values[0] or len(values[0]) > 200 for values in parsed.values()):
        fail(400, "invalid_query", "Unknown, duplicate, empty or oversized query parameter.")
    p = {key: values[0] for key, values in parsed.items()}
    for key, default, minimum, maximum in (("limit", 50, 1, 200), ("offset", 0, 0, 100000)):
        if key in p and not re.fullmatch(r"\d{1,6}", p[key]):
            fail(400, "invalid_pagination", "Pagination must use bounded integers.")
        value = int(p.get(key, default))
        if not minimum <= value <= maximum:
            fail(400, "invalid_pagination", "Pagination is outside allowed bounds.")
        p[key] = value
    for key, values in {"scope": {"meaningful", "registered"}, "qualified": {"true", "false"}, "elected": {"true", "false"}, "result_kind": {"candidate", "list"}, "match_status": {"registry_supported", "context_only", "unknown", "ambiguous"}, "mode": {"observations", "snapshots"}, "relation": {"published_by", "created_by", "about", "depicts", "quoted_speaker"}}.items():
        if key in p and p[key] not in values:
            fail(400, "invalid_filter", f"Unsupported {key} filter.")
    for key in ("since", "until"):
        if key in p:
            try:
                date = datetime.fromisoformat(p[key])
                if date.tzinfo is None:
                    raise ValueError()
            except ValueError:
                fail(400, "invalid_timestamp", "Date filters must be ISO timestamps with timezone.")
    if "since" in p and "until" in p and datetime.fromisoformat(p["since"]) > datetime.fromisoformat(p["until"]):
        fail(400, "invalid_timestamp", "since must not be after until.")
    return p


def page(cp, sql, values, p):
    total = cp.rows(f"SELECT count(*) total FROM ({sql}) result", values)[0]["total"]
    items = cp.rows(sql + " LIMIT ? OFFSET ?", [*values, p["limit"], p["offset"]])
    return {"checkpoint": cp.identity(), "items": items, "page": {"limit": p["limit"], "offset": p["offset"], "total": total, "has_more": p["offset"] + len(items) < total}, "gaps": cp.gaps()}


def asset_conditions(p, alias="a"):
    clauses, values = [], []
    for key, column in (("account_id", "owner_account_id"), ("platform", "platform"), ("asset_type", "asset_type")):
        if key in p:
            clauses.append(f"{alias}.{column}=?")
            values.append(p[key])
    relation = p.get("relation", "published_by")
    if "entity_id" in p or "area_id" in p:
        condition = [f"r.asset_id={alias}.asset_id", "r.status='confirmed'", "r.relation=?"]
        values.append(relation)
        for key, column in (("entity_id", "r.entity_id"), ("area_id", "e.area_id")):
            if key in p:
                condition.append(f"{column}=?")
                values.append(p[key])
        clauses.append("EXISTS(SELECT 1 FROM asset_relation r JOIN entity e USING(entity_id) WHERE " + " AND ".join(condition) + ")")
    elif "relation" in p:
        clauses.append(f"EXISTS(SELECT 1 FROM asset_relation r WHERE r.asset_id={alias}.asset_id AND r.status='confirmed' AND r.relation=?)")
        values.append(relation)
    for key, op in (("since", ">="), ("until", "<=")):
        if key in p:
            clauses.append(f"try_cast({alias}.published_at AS TIMESTAMPTZ) {op} cast(? AS TIMESTAMPTZ)")
            values.append(p[key])
    if "q" in p:
        clauses.append(f"strpos(lower(coalesce({alias}.text,'')),lower(?))>0")
        values.append(p["q"])
    return clauses, values


def topic_link(cp):
    """Only independently reviewed topic edges; never infer from raw taxonomy rows."""
    link = f"SELECT c.asset_id, ct.topic_id FROM claim_topic ct JOIN claim c USING(claim_id) WHERE ct.review_status IN {REVIEWED} AND c.review_status IN {REVIEWED}"
    if "asset_topic" in cp.tables:
        link += f" UNION SELECT asset_id,topic_id FROM asset_topic WHERE review_status IN {REVIEWED}"
    return f"({link})"


def listing(cp, resource, p):
    where, values = [], []
    if resource == "cities":
        sql, alias, order = "SELECT a.* FROM area a", "a", "a.city_rank NULLS LAST,a.area_id"
        for key in ("area_id",):
            if key in p:
                where.append(f"a.{key}=?"); values.append(p[key])
        if "q" in p:
            where.append("strpos(lower(a.name),lower(?))>0"); values.append(p["q"])
    elif resource == "entities":
        sql, order = "SELECT e.* FROM entity e", "e.area_id,e.kind,e.entity_id"
        if p.get("scope", "meaningful") == "meaningful":
            where.append("(e.qualified OR e.kind='local_list')")
        for key in ("area_id", "list_id", "kind", "selection_status"):
            if key in p:
                where.append(f"e.{key}=?"); values.append(p[key])
        if "qualified" in p:
            where.append("e.qualified=?"); values.append(p["qualified"] == "true")
        if "q" in p:
            where.append("strpos(lower(e.name),lower(?))>0"); values.append(p["q"])
    elif resource == "accounts":
        sql, order = f"SELECT a.* FROM {ACCOUNT_ADMISSION} a JOIN entity e USING(entity_id)", "a.account_id,a.entity_id"
        for key, column in (("area_id", "e.area_id"), ("entity_id", "a.entity_id"), ("platform", "a.platform")):
            if key in p:
                where.append(f"{column}=?"); values.append(p[key])
        if "q" in p:
            where.append("strpos(lower(a.handle),lower(?))>0"); values.append(p["q"])
    elif resource == "assets":
        sql, order = "SELECT a.* FROM verified_assets a", "a.published_at DESC NULLS LAST,a.asset_id"
        where, values = asset_conditions(p)
        if "topic_id" in p:
            where.append(f"EXISTS(SELECT 1 FROM {topic_link(cp)} tl WHERE tl.asset_id=a.asset_id AND tl.topic_id=?)"); values.append(p["topic_id"])
    elif resource == "claims":
        sql, order = "SELECT c.* FROM claim c JOIN verified_assets a USING(asset_id)", "c.asset_id,c.claim_id"
        where = [f"c.review_status IN {REVIEWED}"]
        nested, values = asset_conditions({k: v for k, v in p.items() if k in {"area_id", "entity_id"}})
        where += nested
        if "asset_id" in p:
            where.append("c.asset_id=?"); values.append(p["asset_id"])
        if "topic_id" in p:
            where.append(f"EXISTS(SELECT 1 FROM claim_topic ct WHERE ct.claim_id=c.claim_id AND ct.topic_id=? AND ct.review_status IN {REVIEWED})"); values.append(p["topic_id"])
        if "q" in p:
            where.append("strpos(lower(c.text),lower(?))>0"); values.append(p["q"])
    elif resource == "topics":
        sql, order = "SELECT t.* FROM topic t", "t.topic_id"
        conditions, values = asset_conditions({k: v for k, v in p.items() if k in {"area_id", "entity_id"}})
        if "asset_id" in p:
            conditions.append("a.asset_id=?"); values.append(p["asset_id"])
        where = [f"EXISTS(SELECT 1 FROM {topic_link(cp)} tl JOIN verified_assets a USING(asset_id) WHERE tl.topic_id=t.topic_id" + (" AND " + " AND ".join(conditions) if conditions else "") + ")"]
        if "q" in p:
            where.append("strpos(lower(t.label),lower(?))>0"); values.append(p["q"])
    elif resource == "metrics":
        mode = p.get("mode", "observations")
        # Snapshot derivation preserves conflicts on both 1.0 and 1.1 graphs.
        table = "metric" if mode == "observations" else "(SELECT account_id,asset_id,platform,name,observed_at,count(*) AS observation_count, CASE WHEN count(DISTINCT value)>1 THEN NULL ELSE max(value) END AS value, CASE WHEN count(DISTINCT value)>1 THEN 'conflicting_values_same_time' WHEN count(value)=0 THEN min(null_reason) ELSE NULL END AS null_reason, count(DISTINCT value)>1 AS conflict, min(unit) AS unit, list(DISTINCT source_url) AS source_urls, list(DISTINCT source_id) AS source_ids, list(DISTINCT coverage) AS coverage FROM metric GROUP BY account_id,asset_id,platform,name,observed_at)"
        sql = f"SELECT m.* FROM {table} m"
        order = "m.observed_at DESC NULLS LAST,m.platform,m.name,m.account_id NULLS LAST,m.asset_id NULLS LAST" + (",m.metric_id" if mode == "observations" else "")
        ownership, owner_values = [], []
        for key, column in (("entity_id", "v.entity_id"), ("area_id", "e.area_id")):
            if key in p:
                ownership.append(f"{column}=?"); owner_values.append(p[key])
        match = " AND " + " AND ".join(ownership) if ownership else ""
        where = ["((m.account_id IS NOT NULL AND EXISTS(SELECT 1 FROM verified_accounts v JOIN entity e USING(entity_id) WHERE v.account_id=m.account_id" + match + ")) OR (m.asset_id IS NOT NULL AND EXISTS(SELECT 1 FROM verified_assets a JOIN verified_accounts v ON v.account_id=a.owner_account_id JOIN entity e USING(entity_id) WHERE a.asset_id=m.asset_id" + match + ")))" ]
        values = owner_values + owner_values
        for key in ("account_id", "asset_id", "platform", "name"):
            if key in p:
                where.append(f"m.{key}=?"); values.append(p[key])
        for key, op in (("since", ">="), ("until", "<=")):
            if key in p:
                where.append(f"try_cast(m.observed_at AS TIMESTAMPTZ) {op} cast(? AS TIMESTAMPTZ)"); values.append(p[key])
    else:
        fail(404, "not_found", "Unknown resource.")
    result = page(cp, sql + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY " + order, values, p)
    if resource == "cities":
        coverage = {row["area_id"]: row for row in cp.coverage}
        for item in result["items"]:
            item["coverage"] = coverage.get(item["area_id"])
    if resource == "assets":
        ids = [item["asset_id"] for item in result["items"]]
        observations = {}
        if ids:
            placeholders = ",".join("?" for _ in ids)
            bases = [("asset_observation", "coverage")]
            if "production_observation" in cp.tables:
                bases.append(("production_observation", "lane"))
            for table, coverage_column in bases:
                for row in cp.rows(f"SELECT asset_id,observation_id,observed_at,preview_url,video_url,{coverage_column} AS observation_coverage FROM {table} WHERE asset_id IN ({placeholders}) QUALIFY row_number() OVER(PARTITION BY asset_id ORDER BY observed_at DESC NULLS LAST,observation_id)=1", ids):
                    previous = observations.get(row["asset_id"])
                    if previous is None or (row["observed_at"] or "", row["observation_id"]) > (previous["observed_at"] or "", previous["observation_id"]):
                        observations[row["asset_id"]] = row
        for item in result["items"]:
            observation = observations.get(item["asset_id"])
            item["latest_observation"] = observation
        attach_asset_media(cp, result["items"])
    if resource == "claims":
        for item in result["items"]:
            item["topics"] = cp.rows(f"SELECT t.* FROM claim_topic ct JOIN topic t USING(topic_id) WHERE ct.claim_id=? AND ct.review_status IN {REVIEWED} ORDER BY t.topic_id", [item["claim_id"]])
            item["evidence"] = next(iter(cp.rows("SELECT * FROM claim_evidence WHERE claim_id=?", [item["claim_id"]])), None) if "claim_evidence" in cp.tables else None
            if item["evidence"] is None:
                item["evidence_gap"] = "source_context_not_retained"
    return result


def detail(cp, resource, record_id):
    if resource == "entities":
        records = cp.rows("SELECT * FROM entity WHERE entity_id=?", [record_id])
        if not records:
            fail(404, "not_found", "Unknown registry entity.")
        item = records[0]
        item["area"] = next(iter(cp.rows("SELECT * FROM area WHERE area_id=?", [item["area_id"]])), None)
        item["accounts"] = cp.rows(f"SELECT * FROM {ACCOUNT_ADMISSION} WHERE entity_id=? ORDER BY account_id", [record_id])
        for account in item["accounts"]:
            snapshots = cp.rows("SELECT * FROM account_observation WHERE account_id=? ORDER BY observed_at DESC NULLS LAST,observation_id LIMIT 1", [account["account_id"]])
            account["latest_observation"] = snapshots[0] if snapshots else None
        assets = listing(cp, "assets", {"entity_id": record_id, "limit": 20, "offset": 0})
        item["asset_preview"], item["asset_page"] = assets["items"], assets["page"]
        item["coverage"] = next((row for row in cp.coverage if row["area_id"] == item["area_id"]), None)
        photos = photo_listing(cp, "photos", {"entity_id": record_id, "limit": 20, "offset": 0})
        item["photo_preview"], item["photo_page"] = photos["items"], photos["page"]
        coverage = photo_listing(cp, "photo-coverage", {"entity_id": record_id, "limit": 1, "offset": 0})
        item["photo_coverage"] = next(iter(coverage["items"]), None)
        if "entity_election_link" in cp.tables:
            from czlake.production_elections import election_listing
            historical = election_listing(cp, "election-links", {"entity_id": record_id, "limit": 200, "offset": 0})
            item["election_history"] = historical["items"]
            item["election_history_semantics"] = historical["semantics"]
        else:
            item["election_history"] = None
    elif resource == "assets":
        records = cp.rows("SELECT * FROM verified_assets WHERE asset_id=?", [record_id])
        if not records:
            fail(404, "not_found", "Unknown admitted asset.")
        item = records[0]
        item["relations"] = cp.rows("SELECT * FROM asset_relation WHERE asset_id=? AND status='confirmed' ORDER BY relation,entity_id,relation_id", [record_id])
        item["latest_observation"] = next(iter(cp.rows("SELECT * FROM asset_observation WHERE asset_id=? ORDER BY observed_at DESC NULLS LAST,observation_id LIMIT 1", [record_id])), None)
        if "production_observation" in cp.tables:
            item["latest_production_observation"] = next(iter(cp.rows("SELECT * FROM production_observation WHERE asset_id=? ORDER BY observed_at DESC NULLS LAST,observation_id LIMIT 1", [record_id])), None)
        claims = listing(cp, "claims", {"asset_id": record_id, "limit": 20, "offset": 0})
        item["claim_preview"], item["claim_page"] = claims["items"], claims["page"]
        item["topics"] = listing(cp, "topics", {"asset_id": record_id, "limit": 200, "offset": 0})["items"]
        condition = cp.current_classification_condition()
        item["classification_coverage"] = cp.rows(f"SELECT * FROM classification_coverage WHERE asset_id=? AND {condition} ORDER BY classification_id LIMIT 200", [record_id]) if condition else None
        item["classification_history_count"] = cp.rows("SELECT count(*) total FROM classification_coverage WHERE asset_id=?", [record_id])[0]["total"] if condition else None
        resources = media_listing(cp, {"asset_id": record_id, "limit": 200, "offset": 0})
        item["media_resources"], item["media_page"] = resources["items"], resources["page"]
        attach_asset_media(cp, [item])
    else:
        fail(404, "not_found", "Unknown detail resource.")
    return {"checkpoint": cp.identity(), "item": item, "gaps": cp.gaps()}


WEB_METADATA = "asset_id,url,asset_type,public,published_at,publication_evidence,observed_at,title,content_sha256,reported_publisher_id,publisher_status,subject_status,speaker_status,text_truncated,coverage,source_id,text_source_id,text_source_pointer,source_pointer"
WEB_UNKNOWN = "public=true AND publisher_status='unknown' AND subject_status='unknown' AND speaker_status='unknown'"


def web_envelope(cp, result, resource, *, absent=False):
    result["admission_status"] = "source_only_unattributed" if resource == "web-assets" else "unreviewed_publisher_context"
    result["gaps"].append({"code": "web_attribution_unknown", "message": "Retained source text and publisher context do not establish publisher, subject or speaker identity; proposed relations remain unknown or rejected."})
    if absent:
        result["gaps"].append({"code": "web_sources_not_retained", "message": "This checkpoint has no optional source-only web records."})
    return result


def web_listing(cp, resource, p):
    table = "web_asset" if resource == "web-assets" else "publisher"
    if table not in cp.tables:
        return web_envelope(cp, {"checkpoint": cp.identity(), "items": [], "page": {"limit": p["limit"], "offset": p["offset"], "total": 0, "has_more": False}, "gaps": cp.gaps()}, resource, absent=True)
    conditions, values = [], []
    if resource == "web-assets":
        sql = f"SELECT {WEB_METADATA},left(text,320) AS excerpt,length(text) AS text_length FROM web_asset"
        conditions.append(WEB_UNKNOWN)
        for key in ("reported_publisher_id", "asset_type"):
            if key in p:
                conditions.append(f"{key}=?"); values.append(p[key])
        if "q" in p:
            conditions.append("(strpos(lower(title),lower(?))>0 OR strpos(lower(text),lower(?))>0)"); values += [p["q"],p["q"]]
        order = "observed_at DESC NULLS LAST,asset_id"
    else:
        sql = "SELECT publisher_id,name,url,kind,identity_status,source_id,source_pointer FROM publisher"
        conditions.append("identity_status='unknown'")
        if "kind" in p:
            conditions.append("kind=?"); values.append(p["kind"])
        if "q" in p:
            conditions.append("strpos(lower(name),lower(?))>0"); values.append(p["q"])
        order = "publisher_id"
    return web_envelope(cp, page(cp, sql + " WHERE " + " AND ".join(conditions) + " ORDER BY " + order, values, p), resource)


def web_detail(cp, record_id):
    if "web_asset" not in cp.tables:
        fail(404, "not_found", "Unknown retained web source.")
    records = cp.rows(f"SELECT {WEB_METADATA},text FROM web_asset WHERE asset_id=? AND {WEB_UNKNOWN}", [record_id])
    if not records:
        fail(404, "not_found", "Unknown retained web source.")
    item = records[0]
    item["offset_unit"] = "unicode_codepoint"
    item["relation_proposals"] = cp.rows("SELECT relation_id,asset_id,relation,publisher_id,entity_id,status,reason,evidence_quote,span_start,span_end,content_sha256,reviewed_at,review_source_id,source_id,source_pointer FROM web_relation WHERE asset_id=? AND status IN ('unknown','rejected') ORDER BY relation,relation_id LIMIT 200", [record_id]) if "web_relation" in cp.tables else None
    item["relation_proposals_total"] = cp.rows("SELECT count(*) AS total FROM web_relation WHERE asset_id=? AND status IN ('unknown','rejected')", [record_id])[0]["total"] if "web_relation" in cp.tables else None
    item["reported_publisher_context"] = next(iter(cp.rows("SELECT publisher_id,name,url,kind,identity_status,source_id,source_pointer FROM publisher WHERE publisher_id=? AND identity_status='unknown'", [item["reported_publisher_id"]])), None) if "publisher" in cp.tables else None
    return web_envelope(cp, {"checkpoint": cp.identity(), "item": item, "gaps": cp.gaps()}, "web-assets")


PROJECT_ROOT = Path("/home/vecera/code/agents007-hackathon")
DEFAULT_PHOTO_ROOTS = tuple(PROJECT_ROOT / "tmp/production/native" / f"identity_{city}" / "portraits/images" for city in ("brno", "budejovice", "hradec", "liberec", "olomouc", "ostrava", "pardubice", "plzen", "praha", "usti")) + (PROJECT_ROOT / "tmp/production/native/portrait_engine/avatar_intake/downloads/images", PROJECT_ROOT / "tmp/production/native/portrait_engine/avatar_intake/fb_downloads/images", PROJECT_ROOT / "tmp/production/native/portrait_engine/avatar_intake/increment-p041/downloads/images")
DEFAULT_PHOTO_ROOTS += (PROJECT_ROOT / "tmp/production/native/portraits_resume/downloads/images",)
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"}
PHOTO_METADATA = "i.image_id,i.entity_id,i.target_id,i.kind,i.relation_status,i.depicted_person_status,i.download_status,i.sha256,i.bytes,i.content_type,i.width,i.height,i.original_image_url,i.observed_at,i.source_page_url,i.source_page_sha256,i.source_image_pointer,i.source_text_pointer,i.account_id,i.source_id,i.source_page_id,i.source_pointer"


class ImageResponse:
    def __init__(self, data, content_type, sha256, checkpoint_id):
        self.data, self.content_type, self.sha256, self.checkpoint_id = data, content_type, sha256, checkpoint_id


def photo_blob_url(cp, row):
    if row.get("download_status") != "downloaded" or row.get("relation_status") != "source_identified":
        return None
    return "/api/photos/" + quote(row["image_id"], safe="") + "/blob?" + urlencode({"checkpoint_id": cp.pointer["checkpoint_id"]})


def photo_gap():
    return {"code": "photo_depiction_unknown", "message": "Source-linked portraits and owned account avatars are distinct; retained imagery does not establish who is depicted."}


def photo_listing(cp, resource, p):
    table = "source_image" if resource == "photos" else "entity_photo_coverage"
    if table not in cp.tables:
        return {"checkpoint": cp.identity(), "items": [], "page": {"limit": p["limit"], "offset": p["offset"], "total": 0, "has_more": False}, "gaps": cp.gaps() + [photo_gap(), {"code": "photo_data_not_retained", "message": "This checkpoint has no source-image coverage table."}]}
    alias = "i" if resource == "photos" else "c"
    if resource == "photos":
        sql = f"SELECT {PHOTO_METADATA} FROM source_image i JOIN entity e USING(entity_id)"
        order = "i.entity_id,i.kind,i.image_id"
        allowed = ("entity_id", "kind", "download_status", "relation_status")
    else:
        sql = "SELECT c.entity_id,c.target_id,c.name,c.city,c.status,c.portrait_status,c.image_count,c.downloaded_count,c.source_portrait_count,c.unknown_reason,c.source_id,c.source_pointer FROM entity_photo_coverage c JOIN entity e USING(entity_id)"
        order = "c.entity_id"
        allowed = ("entity_id", "status")
    conditions, values = [], []
    for key in allowed:
        if key in p:
            conditions.append(f"{alias}.{key}=?"); values.append(p[key])
    if "area_id" in p:
        conditions.append("e.area_id=?"); values.append(p["area_id"])
    result = page(cp, sql + (" WHERE " + " AND ".join(conditions) if conditions else "") + " ORDER BY " + order, values, p)
    if resource == "photos":
        for item in result["items"]:
            item["blob_url"] = photo_blob_url(cp, item)
    result["gaps"].append(photo_gap())
    return result


def photo_detail(cp, record_id):
    if "source_image" not in cp.tables:
        fail(404, "not_found", "Unknown retained source image.")
    rows = cp.rows(f"SELECT {PHOTO_METADATA} FROM source_image i WHERE image_id=?", [record_id])
    if not rows:
        fail(404, "not_found", "Unknown retained source image.")
    item = rows[0]; item["blob_url"] = photo_blob_url(cp, item)
    return {"checkpoint": cp.identity(), "item": item, "gaps": cp.gaps() + [photo_gap()]}


def confined_file(path, roots):
    if not isinstance(path, str) or not Path(path).is_absolute() or ".." in Path(path).parts:
        raise ValueError("Expected an approved image/source path")
    candidate = Path(path)
    permitted = next((root for root in roots if candidate.is_relative_to(root)), None)
    if permitted is None:
        raise ValueError("Unapproved image/source path")
    for part in (candidate, *candidate.parents):
        if part.is_symlink():
            raise ValueError("Image/source paths must not be symlinks")
        if part == permitted:
            break
    if not candidate.resolve(strict=True).is_relative_to(permitted) or not candidate.is_file():
        raise ValueError("Image/source path escaped its approved root")
    return candidate


def exact_file_bytes(path, sha256, byte_count, maximum):
    if type(byte_count) is not int or not 0 < byte_count <= maximum or not re.fullmatch(r"[a-f0-9]{64}", str(sha256)):
        raise ValueError("Missing source/image integrity metadata")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Source/image is not a regular file")
        data = stream.read(maximum + 1)
    if len(data) != byte_count or hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("Source/image integrity mismatch")
    return data


def pointer_value(document, pointer):
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("Exact source-image JSON pointer required")
    value = document
    for part in pointer.split("/")[1:]:
        if re.search(r"~(?![01])", part):
            raise ValueError("Malformed JSON pointer")
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", key):
            value = value[int(key)]
        elif isinstance(value, dict):
            value = value[key]
        else:
            raise ValueError("Source pointer does not resolve")
    return value


def avif_brand(data):
    """Read only the first bounded BMFF ftyp box; never guess from a URL/suffix."""
    if len(data) < 16 or data[4:8] != b"ftyp":
        return False
    size, header = int.from_bytes(data[:4], "big"), 8
    if size == 1:
        if len(data) < 24:
            return False
        size, header = int.from_bytes(data[8:16], "big"), 16
    if not header + 8 <= size <= min(len(data), 4096) or (size - header - 8) % 4:
        return False
    brands = [data[header:header + 4]]
    brands += [data[index:index + 4] for index in range(header + 8, size, 4)]
    return any(brand in {b"avif", b"avis"} for brand in brands)


def image_type(data):
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if avif_brand(data):
        return "image/avif"
    raise ValueError("Only recognized raster-image bytes may be served")


def photo_blob(cp, record_id, roots):
    if "source_image" not in cp.tables:
        fail(404, "not_found", "Unknown retained source image.")
    records = cp.rows("SELECT * FROM source_image WHERE image_id=?", [record_id])
    if not records:
        fail(404, "not_found", "Unknown retained source image.")
    record = records[0]
    if record["download_status"] != "downloaded" or record["relation_status"] != "source_identified" or record["kind"] not in {"source_bound_portrait", "owned_account_avatar"} or record["depicted_person_status"] != "unknown":
        fail(404, "image_not_admitted", "No admitted retained image is available for this record.")
    try:
        source = next(iter(cp.rows("SELECT * FROM source WHERE source_id=?", [record["source_page_id"]])), None)
        if source is None or source["sha256"] != record["source_page_sha256"]:
            raise ValueError("Missing exact source binding")
        source_path = confined_file(source["path"], (PROJECT_ROOT,))
        source_data = exact_file_bytes(source_path, source["sha256"], source["bytes"], 64 * 1024 * 1024)
        if pointer_value(json.loads(source_data), record["source_image_pointer"]) != record["original_image_url"]:
            raise ValueError("Image URL differs from source scalar")
        url = urlsplit(record["original_image_url"])
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("Public image source URL required")
        blob_source = next(iter(cp.rows("SELECT * FROM source WHERE source_id=?", [record["blob_source_id"]])), None)
        if blob_source is None or (blob_source["path"], blob_source["sha256"], blob_source["bytes"]) != (record["local_path"], record["sha256"], record["bytes"]):
            raise ValueError("Image blob differs from its pinned source record")
        image_path = confined_file(record["local_path"], roots)
        data = exact_file_bytes(image_path, record["sha256"], record["bytes"], 20 * 1024 * 1024)
        content_type = str(record["content_type"]).split(";", 1)[0].strip().lower()
        if content_type not in IMAGE_TYPES or image_type(data) != content_type:
            raise ValueError("Declared image type differs from retained bytes")
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        fail(503, "image_unavailable", "The retained image could not be verified safely.")
    return ImageResponse(data, content_type, record["sha256"], cp.pointer["checkpoint_id"])


DEFAULT_MEDIA_ROOTS = (PROJECT_ROOT / "data/production/media", PROJECT_ROOT / "tmp/production/native/media_finish/downloads", PROJECT_ROOT / "tmp/production/native/media_finish/runtime/blobs")
MEDIA_MAX_BYTES = 64 * 1024 * 1024
MEDIA_METADATA = "m.media_id,m.asset_id,m.kind,m.status,m.sha256,m.bytes,m.content_type,m.fetched_at,m.source_url,m.failure_reason,m.source_envelope_sha256,m.source_item_index,m.source_id,m.blob_source_id,m.source_pointer"
MEDIA_JOIN = "FROM media_resource m JOIN verified_assets a USING(asset_id)"


class MediaResponse(ImageResponse):
    def __init__(self, data, content_type, sha256, checkpoint_id, status=200, content_range=None):
        super().__init__(data, content_type, sha256, checkpoint_id)
        self.status, self.content_range = status, content_range


def media_blob_url(cp, row):
    content_type = str(row.get("content_type") or "").split(";", 1)[0].strip().lower()
    allowed = content_type in IMAGE_TYPES if row.get("kind") == "image" else row.get("kind") == "video" and content_type == "video/mp4"
    if row.get("status") != "downloaded" or not allowed or type(row.get("bytes")) is not int or not 0 < row["bytes"] <= MEDIA_MAX_BYTES or not re.fullmatch(r"[a-f0-9]{64}", str(row.get("sha256"))):
        return None
    return "/api/media/" + quote(row["media_id"], safe="") + "/blob?" + urlencode({"checkpoint_id": cp.pointer["checkpoint_id"]})


def decorate_media(cp, item):
    item["blob_url"] = media_blob_url(cp, item)
    item["local_availability"] = "recorded_downloaded_verified_on_read" if item["blob_url"] else "not_available"
    return item


def media_listing(cp, p):
    if "media_resource" not in cp.tables:
        return {"checkpoint": cp.identity(), "items": [], "page": {"limit": p["limit"], "offset": p["offset"], "total": 0, "has_more": False}, "gaps": cp.gaps()}
    where, values = asset_conditions({k: v for k, v in p.items() if k in {"entity_id", "area_id"}})
    for key in ("asset_id", "kind", "status"):
        if key in p:
            where.append(f"m.{key}=?"); values.append(p[key])
    sql = f"SELECT {MEDIA_METADATA} {MEDIA_JOIN}" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY m.asset_id,m.kind,m.source_pointer,m.media_id"
    result = page(cp, sql, values, p)
    for item in result["items"]:
        decorate_media(cp, item)
    return result


def media_detail(cp, record_id):
    records = cp.rows(f"SELECT {MEDIA_METADATA} {MEDIA_JOIN} WHERE m.media_id=?", [record_id]) if "media_resource" in cp.tables else []
    if not records:
        fail(404, "not_found", "Unknown admitted publication media.")
    return {"checkpoint": cp.identity(), "item": decorate_media(cp, records[0]), "gaps": cp.gaps()}


def attach_asset_media(cp, items):
    """Batch bounded preferred poster/video metadata; no remote fetch or filesystem paths."""
    ids = [item["asset_id"] for item in items]
    selected, counts = {}, {}
    if ids and "media_resource" in cp.tables:
        placeholders = ",".join("?" for _ in ids)
        for row in cp.rows(f"SELECT asset_id,kind,status,count(*) resource_count FROM media_resource WHERE asset_id IN ({placeholders}) GROUP BY asset_id,kind,status ORDER BY asset_id,kind,status", ids):
            counts.setdefault(row.pop("asset_id"), []).append(row)
        for row in cp.rows(f"SELECT {MEDIA_METADATA} {MEDIA_JOIN} WHERE m.asset_id IN ({placeholders}) AND m.status='downloaded' AND ((m.kind='image' AND m.content_type IN ('image/jpeg','image/png','image/webp','image/gif','image/avif')) OR (m.kind='video' AND m.content_type='video/mp4')) AND m.bytes>0 AND m.bytes<=? QUALIFY row_number() OVER(PARTITION BY m.asset_id,m.kind ORDER BY CASE WHEN m.source_pointer LIKE '%/displayUrl' AND m.source_pointer NOT LIKE '%/childPosts/%' THEN 0 ELSE 1 END,m.fetched_at DESC NULLS LAST,m.source_pointer,m.media_id)=1", [*ids, MEDIA_MAX_BYTES]):
            selected.setdefault(row["asset_id"], {})[row["kind"]] = decorate_media(cp, row)
    for item in items:
        choices = selected.get(item["asset_id"], {})
        image, video = choices.get("image"), choices.get("video")
        item["preview_media"], item["video_media"] = image, video
        item["image"] = item["preview_url"] = image["blob_url"] if image else None
        item["video"] = item["video_url"] = video["blob_url"] if video else None
        item["video_mime"] = video["content_type"] if video else None
        item["media_availability"] = {"status": "reported" if "media_resource" in cp.tables else "not_reported", "resources": counts.get(item["asset_id"], []), "image_status": "recorded_downloaded" if item["image"] else "no_retained_image", "video_status": "recorded_downloaded" if item["video"] else "no_retained_video", "verification": "Original source, blob hash and media type are rechecked on every blob read."}


def mp4_type(data):
    if len(data) < 16 or data[4:8] != b"ftyp" or avif_brand(data):
        raise ValueError("Not retained MP4 bytes")
    size, header = int.from_bytes(data[:4], "big"), 8
    if size == 1:
        if len(data) < 24:
            raise ValueError("Truncated MP4 box")
        size, header = int.from_bytes(data[8:16], "big"), 16
    if not header + 8 <= size <= min(len(data), 4096) or (size - header - 8) % 4:
        raise ValueError("Invalid MP4 file type box")
    brands = [data[header:header + 4]] + [data[i:i + 4] for i in range(header + 8, size, 4)]
    if not any(brand in {b"isom", b"iso2", b"iso3", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"M4V ", b"dash"} for brand in brands):
        raise ValueError("Unsupported MP4 brands")
    return "video/mp4"


def media_source_scalar(document, record, asset):
    """Constrain a retained URL to the exact returned admitted parent publication."""
    index = record["source_item_index"]
    if document.get("schema_version") != 1 or document.get("policy_version") != "public-metadata-v1" or type(index) is not int or index < 0:
        raise ValueError("Unsupported retained-media source")
    prefix = f"/items/{index}"
    post = pointer_value(document, prefix)
    actor = document.get("actor")
    pointer = record["source_pointer"]
    if actor == "apify/instagram-profile-scraper":
        match = re.match(re.escape(prefix) + r"/latestPosts/(0|[1-9][0-9]*)/", pointer)
        if not match or post.get("private") is not False:
            raise ValueError("Exact public profile post required")
        prefix += "/latestPosts/" + match[1]
        post = pointer_value(document, prefix)
    if actor in {"apify/instagram-scraper", "apify/instagram-profile-scraper"}:
        leaf = r"(?:displayUrl|images/(?:0|[1-9][0-9]*))" if record["kind"] == "image" else r"videoUrl"
        if asset["platform"] != "instagram" or f"instagram:{post.get('id')}" != asset["asset_id"] or re.fullmatch(re.escape(prefix) + r"/(?:childPosts/(?:0|[1-9][0-9]*)/){0,3}" + leaf, pointer) is None:
            raise ValueError("Retained media leaves its Instagram parent")
    elif actor == "apify/facebook-posts-scraper":
        parent_id = str(post.get("postId") or post.get("id") or "")
        author = str((post.get("user") or {}).get("id") or "")
        container = urlsplit(post.get("topLevelUrl") or "")
        if asset["platform"] != "facebook" or "facebook:" + parent_id != asset["asset_id"] or not author.isdigit() or "facebook:" + author != asset["owner_account_id"] or container.scheme != "https" or container.hostname not in {"facebook.com", "www.facebook.com", "m.facebook.com"} or container.username or container.password or container.port not in {None, 443} or container.path.rstrip("/") != f"/{author}/posts/{parent_id}" or record["kind"] != "image" or re.fullmatch(re.escape(prefix) + r"/(?:thumbnailUrl|imageUrl|media/(?:0|[1-9][0-9]*)/(?:thumbnail|thumbnailUrl|imageUrl))", pointer) is None:
            raise ValueError("Retained media leaves its Facebook author/parent")
    else:
        raise ValueError("Unsupported retained-media actor")
    return pointer_value(document, pointer)


def media_byte_range(data, header):
    if header is None:
        return data, 200, None
    match = re.fullmatch(r"bytes=(\d{1,12})?-(\d{1,12})?", header)
    if not match or not any(match.groups()):
        fail(416, "invalid_range", "Only a single satisfiable byte range is supported.", {"Content-Range": f"bytes */{len(data)}"})
    length = len(data)
    if match[1] is None:
        suffix = int(match[2]); start, end = max(0, length - suffix), length - 1
        valid = suffix > 0
    else:
        start, end = int(match[1]), min(int(match[2]), length - 1) if match[2] is not None else length - 1
        valid = start < length and start <= end
    if not valid:
        fail(416, "invalid_range", "Only a single satisfiable byte range is supported.", {"Content-Range": f"bytes */{len(data)}"})
    return data[start:end + 1], 206, f"bytes {start}-{end}/{length}"


def media_blob(cp, record_id, roots, range_header=None):
    records = cp.rows(f"SELECT m.*,a.platform,a.owner_account_id {MEDIA_JOIN} WHERE m.media_id=?", [record_id]) if "media_resource" in cp.tables else []
    if not records:
        fail(404, "not_found", "Unknown admitted publication media.")
    record = records[0]
    if media_blob_url(cp, record) is None:
        fail(404, "media_not_retained", "No retained typed media is available for this record.")
    try:
        source = next(iter(cp.rows("SELECT * FROM source WHERE path=? AND sha256=?", [record["source_envelope"], record["source_envelope_sha256"]])), None)
        if source is None:
            raise ValueError("Missing pinned media source envelope")
        source_path = confined_file(source["path"], (PROJECT_ROOT,))
        source_data = exact_file_bytes(source_path, source["sha256"], source["bytes"], 64 * 1024 * 1024)
        if media_source_scalar(json.loads(source_data), record, record) != record["source_url"]:
            raise ValueError("Media URL differs from its exact source scalar")
        url = urlsplit(record["source_url"])
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("Public media source URL required")
        blob_source = next(iter(cp.rows("SELECT * FROM source WHERE source_id=?", [record["blob_source_id"]])), None)
        if blob_source is None or (blob_source["path"], blob_source["sha256"], blob_source["bytes"]) != (record["local_path"], record["sha256"], record["bytes"]):
            raise ValueError("Media blob differs from its pinned source record")
        path = confined_file(record["local_path"], roots)
        data = exact_file_bytes(path, record["sha256"], record["bytes"], MEDIA_MAX_BYTES)
        content_type = str(record["content_type"]).split(";", 1)[0].strip().lower()
        actual_type = image_type(data) if record["kind"] == "image" else mp4_type(data)
        if actual_type != content_type:
            raise ValueError("Declared media type differs from retained bytes")
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        fail(503, "media_unavailable", "The retained publication media could not be verified safely.")
    data, status, content_range = media_byte_range(data, range_header)
    return MediaResponse(data, content_type, record["sha256"], cp.pointer["checkpoint_id"], status, content_range)


class ProductionAPI:
    def __init__(self, root=DEFAULT_ROOT, photo_roots=None, media_roots=None):
        self.root = Path(root)
        self.photo_roots = tuple(Path(path).absolute() for path in (DEFAULT_PHOTO_ROOTS if photo_roots is None else photo_roots))

        self.media_roots = tuple(Path(path).absolute() for path in (DEFAULT_MEDIA_ROOTS if media_roots is None else media_roots))

    def handle(self, target, range_header=None):
        if len(target) > 8192:
            fail(400, "invalid_request", "Request target is too long.")
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            fail(400, "invalid_request", "Expected local API path.")
        parts = parsed.path.split("/")
        if len(parts) not in {3, 4, 5} or parts[:2] != ["", "api"] or not parts[2]:
            fail(404, "not_found", "Unknown API route.")
        resource, record_id = parts[2], None
        topic_section = parts[4] if len(parts) == 5 and resource == "topics" else None
        if topic_section is not None and topic_section not in {"assets", "entities", "claims", "related", "web-sources", "metrics"}:
            fail(404, "not_found", "Unknown topic navigation route.")
        blob = len(parts) == 5 and topic_section is None
        if blob and (resource not in {"photos", "media"} or parts[4] != "blob"):
            fail(404, "not_found", "Unknown image route.")
        if len(parts) in {4, 5}:
            try:
                record_id = unquote(parts[3], errors="strict")
            except UnicodeError:
                fail(400, "invalid_identifier", "Identifier is not valid UTF-8.")
            if resource not in {"entities", "assets", "web-assets", "photos", "media", "topics"} or not record_id or len(record_id) > 200 or any(ord(c) < 32 for c in record_id):
                fail(404, "not_found", "Unknown detail route.")
        elif resource not in FILTERS and resource not in {"health", "checkpoint"}:
            fail(404, "not_found", "Unknown API route.")
        p = parameters(resource, parsed.query, detail=(record_id is not None and resource != "topics") or resource in {"health", "checkpoint"})
        with PinnedCheckpoint(self.root, p.get("checkpoint_id")) as cp:
            if resource in {"election-lists", "election-candidates", "election-links"}:
                from czlake.production_elections import election_listing
                return election_listing(cp, resource, p)
            if resource == "topics":
                from czlake.production_topic_graph import TopicGraphError, topic_route
                try:
                    return topic_route(cp, p, record_id, topic_section)
                except TopicGraphError as error:
                    fail(error.status, error.code, error.message)
            if blob:
                return photo_blob(cp, record_id, self.photo_roots) if resource == "photos" else media_blob(cp, record_id, self.media_roots, range_header)
            if resource == "media":
                return media_detail(cp, record_id) if record_id is not None else media_listing(cp, p)
            if resource == "photos" and record_id is not None:
                return photo_detail(cp, record_id)
            if resource in {"photos", "photo-coverage"}:
                return photo_listing(cp, resource, p)
            if record_id is not None:
                return web_detail(cp, record_id) if resource == "web-assets" else detail(cp, resource, record_id)
            if resource in {"health", "checkpoint"}:
                return {"status": "ready", "checkpoint": cp.identity(), "counts": cp.manifest.get("counts", {}), "quality": cp.manifest["quality"], "coverage": cp.manifest.get("coverage", {}), "classification": cp.classification_summary(), "capabilities": {name: name in cp.tables for name in ("claim_evidence", "asset_topic", "classification_coverage", "media_resource", "metric_snapshots", "web_asset", "publisher", "web_relation", "source_image", "entity_photo_coverage", "election_list_result", "election_candidate_result", "entity_election_link")}, "gaps": cp.gaps()}
            if resource == "coverage":
                items = [row for row in cp.coverage if "area_id" not in p or row["area_id"] == p["area_id"]]
                return {"checkpoint": cp.identity(), "items": items[p["offset"]:p["offset"] + p["limit"]], "page": {"limit": p["limit"], "offset": p["offset"], "total": len(items), "has_more": p["offset"] + p["limit"] < len(items)}, "summary": cp.manifest.get("coverage", {}), "classification": cp.classification_summary(), "gaps": cp.gaps()}
            return web_listing(cp, resource, p) if resource in {"web-assets", "publishers"} else listing(cp, resource, p)


def request_authority(headers, port):
    """Deny browser DNS rebinding before reading private checkpoint metadata."""
    hosts = headers.get_all("Host", [])
    if len(hosts) != 1:
        fail(403, "forbidden_host", "A single authorized local Host is required.")

    def authority(value):
        if not isinstance(value, str) or any(character.isspace() for character in value) or any(character in value for character in ",@/\\?#%"):
            raise ValueError("Malformed local authority")
        parsed = urlsplit("//" + value)
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("Unapproved host")
        parsed_port = parsed.port if parsed.port is not None else 80
        if parsed_port != port:
            raise ValueError("Wrong local port")
        return parsed.hostname, parsed_port

    try:
        host = authority(hosts[0])
    except ValueError:
        fail(403, "forbidden_host", "Request Host is not the local API authority.")
    origins = headers.get_all("Origin", [])
    if not origins:
        return  # Local CLI and server-side proxies normally omit Origin.
    if len(origins) != 1:
        fail(403, "forbidden_origin", "A single matching local Origin is required.")
    try:
        origin = urlsplit(origins[0])
        if origin.scheme != "http" or origin.path or origin.query or origin.fragment or authority(origin.netloc) != host:
            raise ValueError("Conflicting origin")
    except ValueError:
        fail(403, "forbidden_origin", "Request Origin does not match the local API authority.")


def make_server(root=DEFAULT_ROOT, host="127.0.0.1", port=8123, photo_roots=None, media_roots=None):
    api = ProductionAPI(root, photo_roots=photo_roots, media_roots=media_roots)

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, body, headers=None):
            data = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            if status == 405:
                self.send_header("Allow", "GET, HEAD")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
            self.close_connection = True

        def respond_image(self, result):
            self.send_response(result.status if isinstance(result, MediaResponse) else 200)
            if isinstance(result, MediaResponse):
                self.send_header("Accept-Ranges", "bytes")
                if result.content_range:
                    self.send_header("Content-Range", result.content_range)
            self.send_header("Content-Type", result.content_type)
            self.send_header("Content-Length", str(len(result.data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
            self.send_header("ETag", '"' + result.sha256 + '"')
            self.send_header("X-Starwatch-Checkpoint", result.checkpoint_id)
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(result.data)
            self.close_connection = True

        def do_GET(self):
            try:
                request_authority(self.headers, self.server.server_address[1])
                ranges = self.headers.get_all("Range", [])
                if len(ranges) > 1:
                    fail(416, "invalid_range", "Only a single byte range is supported.")
                result = api.handle(self.path, ranges[0] if ranges else None)
                self.respond_image(result) if isinstance(result, ImageResponse) else self.respond(200, result)
            except APIError as error:
                self.respond(error.status, {"error": {"code": error.code, "message": error.message}}, error.headers)
            except (duckdb.Error, OSError, ValueError, KeyError, TypeError):
                self.respond(503, {"error": {"code": "checkpoint_unavailable", "message": "The checkpoint could not be read safely."}})

        do_HEAD = do_GET

        def unsupported(self):
            self.respond(405, {"error": {"code": "read_only", "message": "This API only supports GET and HEAD."}})

        do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = do_CONNECT = unsupported

        def log_message(self, *_):
            pass  # No subject names, request filters or source content in access logs.

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8123)
    args = parser.parse_args()
    with make_server(args.root, args.host, args.port) as server:
        print(f"Production read API: http://{args.host}:{server.server_address[1]} (read-only)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
