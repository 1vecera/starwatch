"""Read-only cached graph exporter; writes only its explicitly selected output root.

No lakehouse/paths import, network call, classification or raw nested-field persistence.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from collections import defaultdict
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import duckdb
import pyarrow as pa

SCHEMA_VERSION = "starwatch-production-graph/1.1.0"
DEFAULT_ROOT = Path("/home/vecera/code/agents007-hackathon")
DEFAULT_REVIEWS = (
    "data/evidence/top10_profile_review.json",
    "data/evidence/top10_organization_profile_review.json",
)
TABLES = (
    "source",
    "area",
    "entity",
    "account",
    "account_observation",
    "account_relation",
    "asset",
    "asset_observation",
    "asset_relation",
    "metric",
    "claim",
    "topic",
    "claim_topic",
    "quarantine",
)
DDL = """
CREATE TABLE source(source_id VARCHAR PRIMARY KEY, path VARCHAR NOT NULL, sha256 VARCHAR NOT NULL, bytes BIGINT NOT NULL);
CREATE TABLE area(area_id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, city_rank INTEGER, population BIGINT, geometry VARCHAR, source_url VARCHAR, source_id VARCHAR REFERENCES source(source_id));
CREATE TABLE entity(entity_id VARCHAR PRIMARY KEY, kind VARCHAR NOT NULL, area_id VARCHAR REFERENCES area(area_id), name VARCHAR NOT NULL, person_cluster_id VARCHAR, person_cluster_status VARCHAR, list_id VARCHAR, position INTEGER, validity VARCHAR, eligibility_kind VARCHAR, qualified BOOLEAN NOT NULL, protected BOOLEAN NOT NULL, selection_status VARCHAR NOT NULL, relevance_score DOUBLE, relevance_components VARCHAR, relevance_reasons VARCHAR, rule_version VARCHAR, local_role_status VARCHAR NOT NULL, source_url VARCHAR, observed_at VARCHAR, source_id VARCHAR REFERENCES source(source_id), source_pointer VARCHAR);
CREATE TABLE account(account_id VARCHAR PRIMARY KEY, platform VARCHAR NOT NULL, handle VARCHAR NOT NULL, url VARCHAR NOT NULL, public BOOLEAN, identity_status VARCHAR NOT NULL);
CREATE TABLE account_observation(observation_id VARCHAR PRIMARY KEY, account_id VARCHAR NOT NULL REFERENCES account(account_id), display_name VARCHAR, biography VARCHAR, external_url VARCHAR, avatar_url VARCHAR, observed_at VARCHAR, run_id VARCHAR, source_id VARCHAR NOT NULL REFERENCES source(source_id), source_pointer VARCHAR NOT NULL, coverage VARCHAR NOT NULL);
CREATE TABLE account_relation(relation_id VARCHAR PRIMARY KEY, entity_id VARCHAR NOT NULL REFERENCES entity(entity_id), account_id VARCHAR NOT NULL REFERENCES account(account_id), relation VARCHAR NOT NULL CHECK(relation='owns_account'), status VARCHAR NOT NULL CHECK(status IN ('confirmed','unknown','rejected','conflicted')), reason VARCHAR NOT NULL, evidence_url VARCHAR, evidence_span VARCHAR, reviewed_at VARCHAR, source_id VARCHAR NOT NULL REFERENCES source(source_id), source_pointer VARCHAR NOT NULL);
CREATE TABLE asset(asset_id VARCHAR PRIMARY KEY, platform VARCHAR NOT NULL, asset_type VARCHAR, url VARCHAR, published_at VARCHAR, text VARCHAR, owner_account_id VARCHAR REFERENCES account(account_id), verification_status VARCHAR NOT NULL, verification_reason VARCHAR NOT NULL, claim_status VARCHAR NOT NULL);
CREATE TABLE asset_observation(observation_id VARCHAR PRIMARY KEY, asset_id VARCHAR NOT NULL REFERENCES asset(asset_id), observed_account_id VARCHAR NOT NULL REFERENCES account(account_id), reported_owner_account_id VARCHAR REFERENCES account(account_id), published_at VARCHAR, observed_at VARCHAR, run_id VARCHAR, source_id VARCHAR NOT NULL REFERENCES source(source_id), source_pointer VARCHAR NOT NULL, preview_url VARCHAR, video_url VARCHAR, coverage VARCHAR NOT NULL, requested_start VARCHAR, requested_end VARCHAR,text VARCHAR,content_sha256 VARCHAR);
CREATE TABLE asset_relation(relation_id VARCHAR PRIMARY KEY, asset_id VARCHAR NOT NULL REFERENCES asset(asset_id), entity_id VARCHAR NOT NULL REFERENCES entity(entity_id), relation VARCHAR NOT NULL CHECK(relation IN ('published_by','created_by','about','depicts','quoted_speaker')), status VARCHAR NOT NULL CHECK(status IN ('confirmed','unknown','rejected','conflicted')), reason VARCHAR NOT NULL, evidence_url VARCHAR, evidence_span VARCHAR, reviewed_at VARCHAR, source_id VARCHAR NOT NULL REFERENCES source(source_id), source_pointer VARCHAR NOT NULL);
CREATE TABLE metric(metric_id VARCHAR PRIMARY KEY, account_id VARCHAR REFERENCES account(account_id), asset_id VARCHAR REFERENCES asset(asset_id), observation_id VARCHAR NOT NULL, platform VARCHAR NOT NULL, name VARCHAR NOT NULL, value DOUBLE, unit VARCHAR NOT NULL, raw_value VARCHAR, null_reason VARCHAR, observed_at VARCHAR, source_url VARCHAR, source_id VARCHAR NOT NULL REFERENCES source(source_id), source_pointer VARCHAR NOT NULL, coverage VARCHAR NOT NULL, CHECK((account_id IS NULL) <> (asset_id IS NULL)), CHECK(value IS NULL OR value >= 0), CHECK((value IS NULL) = (null_reason IS NOT NULL)));
CREATE TABLE claim(claim_id VARCHAR PRIMARY KEY, asset_id VARCHAR NOT NULL REFERENCES asset(asset_id), text VARCHAR NOT NULL, evidence_quote VARCHAR, span_start INTEGER, span_end INTEGER, time_start DOUBLE, time_end DOUBLE, speaker_entity_id VARCHAR REFERENCES entity(entity_id), speaker_status VARCHAR NOT NULL, review_status VARCHAR NOT NULL, source_id VARCHAR REFERENCES source(source_id), source_pointer VARCHAR);
CREATE TABLE topic(topic_id VARCHAR PRIMARY KEY, label VARCHAR NOT NULL, taxonomy_version VARCHAR NOT NULL);
CREATE TABLE claim_topic(claim_id VARCHAR NOT NULL REFERENCES claim(claim_id), topic_id VARCHAR NOT NULL REFERENCES topic(topic_id), review_status VARCHAR NOT NULL, PRIMARY KEY(claim_id,topic_id));
CREATE TABLE quarantine(quarantine_id VARCHAR PRIMARY KEY, grain VARCHAR NOT NULL, record_id VARCHAR NOT NULL, reason VARCHAR NOT NULL, source_id VARCHAR NOT NULL REFERENCES source(source_id), source_pointer VARCHAR NOT NULL);
CREATE VIEW verified_accounts AS SELECT a.*, r.entity_id, r.evidence_url, r.reviewed_at FROM account a JOIN account_relation r USING(account_id) WHERE r.status='confirmed' AND a.identity_status='confirmed' QUALIFY row_number() OVER(PARTITION BY a.account_id ORDER BY r.reviewed_at DESC NULLS LAST,r.relation_id)=1;
CREATE VIEW verified_assets AS SELECT * FROM asset WHERE verification_status='verified_publication_owner';
CREATE VIEW meaningful_entities AS SELECT * FROM entity WHERE qualified;
"""


try:
    from .production_ingest import EXTENSION_DDL, EXTENSION_TABLES, extend_graph
    from .production_elections import ELECTION_GATES
    from .production_logos import LOGO_GATES
except ImportError:
    from production_ingest import EXTENSION_DDL, EXTENSION_TABLES, extend_graph
    from production_elections import ELECTION_GATES
    from production_logos import LOGO_GATES

DDL += EXTENSION_DDL
TABLES += EXTENSION_TABLES


def packed(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value):
    return hashlib.sha256(
        value if isinstance(value, bytes) else value.encode()
    ).hexdigest()


def key(prefix, *parts):
    return prefix + ":" + digest(packed(parts))[:24]


def instant(value):
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value)
        return date.astimezone(UTC).isoformat() if date.tzinfo else None
    except ValueError:
        return None


def public_url(value):
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return (
        value
        if parsed.scheme in ("http", "https")
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        else None
    )


def handle(value):
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower().lstrip("@")
    return cleaned if re.fullmatch(r"[a-z0-9._]{1,100}", cleaned) else None


def normalize_metric(value, observed_at):
    """Negative/sentinel, nonnumeric and undated observations never become totals."""
    if instant(observed_at) is None:
        return None, "observation_time_missing_or_invalid"
    if value is None:
        return None, "not_returned"
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        return None, "invalid_numeric_value"
    if value == -1:
        return None, "provider_unavailable_sentinel"
    if value < 0:
        return None, "invalid_negative_value"
    return value, None


class Inputs:
    """Read each source once and retain a digest, never persist its raw payload."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.values = {}
        self.sources = {}

    def read(self, path, *, optional=False) -> tuple[Any, str | None]:
        path = Path(path)
        if not path.is_absolute():
            path = self.root / path
        path = path.resolve()
        if path in self.values:
            return self.values[path], self.sources[path]["source_id"]
        if optional and not path.exists():
            return None, None
        data = path.read_bytes()
        source_id = key("source", str(path), digest(data))
        self.sources[path] = {
            "source_id": source_id,
            "path": str(path),
            "sha256": digest(data),
            "bytes": len(data),
        }
        value = json.loads(data)
        self.values[path] = value
        return value, source_id

    def unchanged(self):
        return all(
            digest(path.read_bytes()) == source["sha256"]
            for path, source in self.sources.items()
        )


def confirmed_owner(proof, profile, entity, as_of, *, require_profile_public=True):
    """Collector-reviewed exact anchor; labels/counts/profile bios alone never suffice."""
    if entity is None:
        return False, "entity_missing_or_invalid_candidacy"
    required = (
        proof.get("adjudication") == "confirmed",
        proof.get("identity_confirmed") is True,
        proof.get("anchor_links_account") is True,
        proof.get("public") is True,
        not require_profile_public or profile.get("public") is True,
    )
    if not all(required):
        return False, "independent_exact_account_anchor_not_confirmed"
    if (
        handle(proof.get("handle")) != handle(profile.get("handle"))
        or handle(proof.get("handle")) is None
    ):
        return False, "anchor_handle_mismatch"
    target = public_url(proof.get("profile_url"))
    if (
        not target
        or urlparse(target).hostname not in ("instagram.com", "www.instagram.com")
        or urlparse(target).path.strip("/").lower() != handle(profile["handle"])
    ):
        return False, "anchor_profile_url_mismatch"
    anchor = public_url(proof.get("source_url"))
    if not anchor or urlparse(anchor).hostname in (
        "instagram.com",
        "www.instagram.com",
        "facebook.com",
        "www.facebook.com",
        "tiktok.com",
        "www.tiktok.com",
    ):
        return False, "independent_source_missing_or_social_self_assertion"
    reviewed = instant(proof.get("observed_at"))
    if (
        not reviewed
        or not 0
        <= (
            datetime.fromisoformat(as_of) - datetime.fromisoformat(reviewed)
        ).total_seconds()
        <= 30 * 86400
    ):
        return False, "anchor_review_stale_future_or_undated"
    if entity["kind"] == "local_list":
        if proof.get("scope") not in (None, "city_political_organization"):
            return False, "nonlocal_organization_scope"
        if (
            proof.get("list_no") is not None
            and str(proof["list_no"]) != entity["entity_id"].split(":")[-1]
        ):
            return False, "organization_list_mismatch"
    return True, "independently_reviewed_exact_public_anchor"


def build_cached_graph(
    root=DEFAULT_ROOT,
    *,
    relevance_dir=None,
    reviews=None,
    identity_path=None,
    as_of=None,
):
    """Build an allowlisted in-memory graph from coordinator-selected cached paths."""
    inputs = Inputs(root)
    version_dir = (
        Path(relevance_dir)
        if relevance_dir
        else inputs.root / "tmp/prioritization/relevance-v2"
    )
    universe, universe_source = inputs.read(version_dir / "universe.json")
    lists, list_source = inputs.read(version_dir / "lists.json")
    selection, _ = inputs.read(version_dir / "selection.json")
    identity, identity_source = inputs.read(
        identity_path or "data/evidence/top10_public_identity_review.json"
    )
    as_of = instant(as_of or datetime.now(UTC).isoformat())
    if as_of is None:
        raise ValueError("as_of must include an explicit timezone")
    rows = {table: [] for table in TABLES}
    entities, areas = {}, {}
    selected, overflow, discovery = (
        set(selection.get(name, []))
        for name in (
            "qualified_keys",
            "qualifying_overflow",
            "additional_discovery_keys",
        )
    )
    if selected & overflow or (selected | overflow) & discovery:
        raise ValueError("Selection/overflow/discovery keys must be disjoint")

    def reject(grain, record_id, reason, source_id, pointer):
        rows["quarantine"].append(
            {
                "quarantine_id": key(
                    "quarantine", grain, record_id, reason, source_id, pointer
                ),
                "grain": grain,
                "record_id": record_id,
                "reason": reason,
                "source_id": source_id,
                "source_pointer": pointer,
            }
        )

    def entity_record(record, index, is_list=False):
        candidate = record.get("candidate", {})
        evidence = record.get("evidence", {})
        entity_id = record["key"] if is_list else candidate["key"]
        source_id = list_source if is_list else universe_source
        pointer = f"/{index}"
        if not is_list and (
            candidate.get("eligible") is not True
            or (
                candidate.get("eligibility_kind") == "current_candidacy"
                and evidence.get("validity") != "A"
            )
        ):
            reject(
                "entity",
                entity_id,
                "invalid_or_ineligible_current_candidacy",
                source_id,
                pointer,
            )
            return
        if entity_id in entities:
            raise ValueError(f"Duplicate entity key: {entity_id}")
        area_id = str(
            record.get("municipality_code") if is_list else candidate["city_code"]
        )
        kind = (
            "local_list"
            if is_list
            else (
                "current_candidacy"
                if candidate.get("eligibility_kind") == "current_candidacy"
                else "noncandidate_person"
            )
        )
        score = record.get("priority", {}) if is_list else record
        source_url = public_url(
            record.get("priority", {}).get("sources", {}).get("current_list")
            if is_list
            else evidence.get("source_url")
        )
        areas.setdefault(
            area_id,
            {
                "area_id": area_id,
                "name": record["city"],
                "city_rank": record.get("city_rank")
                if is_list
                else candidate.get("city_rank"),
                "population": None if is_list else candidate.get("population"),
                "geometry": None,
                "source_url": source_url,
                "source_id": source_id,
            },
        )
        row = {
            "entity_id": entity_id,
            "kind": kind,
            "area_id": area_id,
            "name": record["name"],
            "person_cluster_id": None if is_list else record.get("person_id"),
            "person_cluster_status": None
            if is_list
            else (
                "inferred_historical_ambiguous"
                if not candidate.get("historical_identity_clear", False)
                else "inferred_not_independently_resolved"
            ),
            "list_id": None
            if is_list or kind != "current_candidacy"
            else f"kv2026:{area_id}:{candidate['list_no']}",
            "position": None if is_list else candidate.get("position"),
            "validity": None
            if is_list or kind != "current_candidacy"
            else evidence.get("validity"),
            "eligibility_kind": "current_local_list"
            if is_list
            else candidate.get("eligibility_kind"),
            "qualified": record.get("qualified") is True,
            "protected": record.get("protected") is True,
            "selection_status": "selected_proposal"
            if entity_id in selected
            else "qualifying_overflow"
            if entity_id in overflow
            else "additional_discovery_proposal"
            if entity_id in discovery
            else "retained_unselected",
            "relevance_score": score.get("score"),
            "relevance_components": packed(score.get("components", {})),
            "relevance_reasons": packed(score.get("reasons", [])),
            "rule_version": record.get("rule_version", "relevance-v2"),
            "local_role_status": "official_registered_candidacy"
            if kind == "current_candidacy"
            else "official_registered_local_list"
            if is_list
            else "reviewed_local_role",
            "source_url": source_url,
            "observed_at": instant(
                record.get("observed_at") if is_list else evidence.get("fetched_at")
            ),
            "source_id": source_id,
            "source_pointer": pointer,
        }
        # Existing reference admits reviewed roles separately; do not fabricate roles.
        if kind == "noncandidate_person" and (
            candidate.get("eligibility_kind") != "reviewed_local_role"
            or not candidate.get("local_role_verified")
            or not record.get("reviewed_sources")
        ):
            reject(
                "entity",
                entity_id,
                "noncandidate_local_role_evidence_missing",
                source_id,
                pointer,
            )
            return
        entities[entity_id] = row
        rows["entity"].append(row)

    for i, record in enumerate(universe):
        entity_record(record, i)
    for i, record in enumerate(lists):
        entity_record(record, i, True)
    rows["area"] = list(areas.values())
    if (selected | overflow | discovery) - entities.keys():
        raise ValueError("Selection references unknown/ineligible entities")
    actual_qualified = {
        r["entity_id"]
        for r in rows["entity"]
        if r["kind"] != "local_list" and r["qualified"]
    }
    if selected | overflow != actual_qualified:
        raise ValueError(
            "Selection and complete overflow must preserve every meaningful qualifier"
        )
    if any(r["list_id"] not in entities for r in rows["entity"] if r["list_id"]):
        raise ValueError("Current candidacy references a missing local list")

    accounts, relations, observations = {}, [], defaultdict(list)
    raw_profiles, raw_posts = {}, defaultdict(list)
    loaded_raw = set()

    def account_for(h, public=None):
        h = handle(h)
        if h is None:
            return None
        account_id = "instagram:" + h
        if account_id not in accounts:
            accounts[account_id] = {
                "account_id": account_id,
                "platform": "instagram",
                "handle": h,
                "url": f"https://www.instagram.com/{h}/",
                "public": public,
                "identity_status": "unknown",
            }
        return account_id

    def metric_row(
        value,
        name,
        observation_id,
        at,
        source_id,
        pointer,
        source_url,
        coverage,
        account_id=None,
        asset_id=None,
    ):
        normalized, reason = normalize_metric(value, at)
        rows["metric"].append(
            {
                "metric_id": key("metric", observation_id, name),
                "account_id": account_id,
                "asset_id": asset_id,
                "observation_id": observation_id,
                "platform": "instagram",
                "name": name,
                "value": normalized,
                "unit": "count",
                "raw_value": packed(value)
                if value is None
                or isinstance(value, (str, bool, int, float))
                and (not isinstance(value, float) or math.isfinite(value))
                else None,
                "null_reason": reason,
                "observed_at": instant(at),
                "source_url": public_url(source_url),
                "source_id": source_id,
                "source_pointer": pointer,
                "coverage": coverage,
            }
        )

    for review_path in reviews or DEFAULT_REVIEWS:
        review, review_source = inputs.read(review_path)
        for profile in review.get("profiles", []):
            raw_path = profile.get("source_path")
            if raw_path and str(raw_path) not in loaded_raw:
                loaded_raw.add(str(raw_path))
                raw, raw_source = inputs.read(raw_path, optional=True)
                if raw:
                    payload = raw.get("items", []) if isinstance(raw, dict) else raw
                    for item in payload:
                        h = handle(item.get("username"))
                        if h:
                            raw_profiles[h] = item
                        for post in item.get("latestPosts", []):
                            if post.get("id"):
                                raw_posts["instagram:" + str(post["id"])].append(
                                    (post, raw_source)
                                )
        by_handle = {}
        for i, profile in enumerate(review.get("profiles", [])):
            account_id = account_for(profile.get("handle"), profile.get("public"))
            if not account_id:
                reject(
                    "account",
                    str(profile.get("handle")),
                    "invalid_public_handle",
                    review_source,
                    f"/profiles/{i}",
                )
                continue
            by_handle[handle(profile["handle"])] = profile
            entity_id = profile.get("requested_entity_key")
            entity = entities.get(entity_id)
            proof = identity.get(
                "lists" if entity and entity["kind"] == "local_list" else "candidates",
                {},
            ).get(entity_id, {})
            accepted, reason = confirmed_owner(proof, profile, entity, as_of)
            raw_profile = raw_profiles.get(handle(profile["handle"]), {})
            if raw_profile.get("private") is True:
                accepted, reason = False, "raw_profile_is_private"
            if entity:
                relation = {
                    "relation_id": key(
                        "account_relation", entity_id, account_id, review_source, i
                    ),
                    "entity_id": entity_id,
                    "account_id": account_id,
                    "relation": "owns_account",
                    "status": "confirmed" if accepted else "unknown",
                    "reason": reason,
                    "evidence_url": public_url(proof.get("source_url")),
                    "evidence_span": proof.get("excerpt")
                    if isinstance(proof.get("excerpt"), str)
                    else None,
                    "reviewed_at": instant(proof.get("observed_at")),
                    "source_id": identity_source,
                    "source_pointer": f"/{'lists' if entity['kind'] == 'local_list' else 'candidates'}/{entity_id}",
                }
                relations.append(relation)
            else:
                reject(
                    "account_relation",
                    account_id,
                    reason,
                    review_source,
                    f"/profiles/{i}",
                )
            observation_id = key("profile_observation", review_source, i)
            at = profile.get("observed_at")
            rows["account_observation"].append(
                {
                    "observation_id": observation_id,
                    "account_id": account_id,
                    "display_name": profile.get("display_name")
                    if isinstance(profile.get("display_name"), str)
                    else None,
                    "biography": profile.get("biography")
                    if isinstance(profile.get("biography"), str)
                    else None,
                    "external_url": public_url(profile.get("external_url")),
                    "avatar_url": public_url(
                        raw_profile.get("profilePicUrlHD")
                        or raw_profile.get("profilePicUrl")
                    ),
                    "observed_at": instant(at),
                    "run_id": profile.get("apify_run_id"),
                    "source_id": review_source,
                    "source_pointer": f"/profiles/{i}",
                    "coverage": "profile_snapshot_not_growth_or_local_audience",
                }
            )
            metric_row(
                profile.get("followers"),
                "followers",
                observation_id,
                at,
                review_source,
                f"/profiles/{i}/followers",
                profile.get("profile_url"),
                "single_profile_snapshot",
                account_id=account_id,
            )
        for i, post in enumerate(review.get("posts", [])):
            observed_id = account_for(
                post.get("observed_profile_handle") or post.get("handle")
            )
            if not observed_id or not isinstance(post.get("post_id"), str):
                reject(
                    "asset_observation",
                    str(post.get("post_id")),
                    "missing_asset_id_or_observed_profile",
                    review_source,
                    f"/posts/{i}",
                )
                continue
            owner_id = account_for(post.get("owner_handle"))
            observation_id = key("post_observation", review_source, i)
            raw_options = raw_posts.get(post["post_id"], [])
            raw_post = next(
                (
                    r
                    for r, _ in raw_options
                    if handle(r.get("ownerUsername"))
                    == handle(post.get("owner_handle"))
                ),
                {},
            )
            row = {
                "observation_id": observation_id,
                "asset_id": post["post_id"],
                "observed_account_id": observed_id,
                "reported_owner_account_id": owner_id,
                "published_at": instant(post.get("published_at")),
                "observed_at": instant(
                    post.get("fetched_at") or review.get("observed_at")
                ),
                "run_id": post.get("apify_run_id"),
                "source_id": review_source,
                "source_pointer": f"/posts/{i}",
                "preview_url": public_url(raw_post.get("displayUrl")),
                "video_url": public_url(raw_post.get("videoUrl")),
                "coverage": "recent_profile_bundle_not_complete_history",
                "requested_start": instant((review.get("window") or [None, None])[0]),
                "requested_end": instant((review.get("window") or [None, None])[1]),
                "text": post.get("text") if isinstance(post.get("text"), str) else None,
                "content_sha256": digest(post["text"])
                if isinstance(post.get("text"), str)
                else None,
            }
            rows["asset_observation"].append(row)
            observations[post["post_id"]].append(
                (
                    post,
                    row,
                    {
                        account_for(r.get("ownerUsername"))
                        for r, _ in raw_options
                        if handle(r.get("ownerUsername"))
                    },
                )
            )
            for name in ("likes", "comments_count", "views", "shares"):
                metric_row(
                    post.get(name),
                    name,
                    observation_id,
                    row["observed_at"],
                    review_source,
                    f"/posts/{i}/{name}",
                    post.get("url"),
                    row["coverage"],
                    asset_id=post["post_id"],
                )

    confirmed = defaultdict(set)
    for relation in relations:
        if relation["status"] == "confirmed":
            confirmed[relation["account_id"]].add(relation["entity_id"])
    for relation in relations:
        if len(confirmed[relation["account_id"]]) > 1:
            relation["status"], relation["reason"] = (
                "conflicted",
                "multiple_independently_proposed_entity_owners",
            )
    confirmed = {
        account_id: next(iter(owners))
        for account_id, owners in confirmed.items()
        if len(owners) == 1
    }
    for account_id, account in accounts.items():
        account["identity_status"] = (
            "confirmed"
            if account_id in confirmed
            else "conflicted"
            if any(
                r["account_id"] == account_id and r["status"] == "conflicted"
                for r in relations
            )
            else "unknown"
        )
    rows["account_relation"] = relations

    for asset_id, values in sorted(observations.items()):
        owners = {
            row["reported_owner_account_id"]
            for _, row, _ in values
            if row["reported_owner_account_id"]
        }
        raw_owners = set().union(*(owners for _, _, owners in values))
        source_texts = {
            post["text"] for post, _, _ in values if isinstance(post.get("text"), str)
        }
        owner = next(iter(owners)) if len(owners) == 1 else None
        direct = any(row["observed_account_id"] == owner for _, row, _ in values)
        reason = "independent_owner_anchor_missing"
        if len(owners) > 1 or raw_owners and raw_owners != owners:
            reason = "reported_publication_owner_conflict"
        elif len(source_texts) > 1:
            reason = "content_contradiction"
        elif not owner:
            reason = "reported_publication_owner_unknown"
        elif not direct:
            reason = "other_owner_in_profile_bundle_not_owned"
        elif owner in confirmed:
            reason = "independent_anchor_and_direct_reported_owner"
        verified = reason == "independent_anchor_and_direct_reported_owner"
        post, observed, _ = max(
            values, key=lambda v: (v[1]["observed_at"] or "", v[1]["observation_id"])
        )
        rows["asset"].append(
            {
                "asset_id": asset_id,
                "platform": "instagram",
                "asset_type": post.get("kind")
                if isinstance(post.get("kind"), str)
                else None,
                "url": public_url(post.get("url")),
                "published_at": instant(post.get("published_at")),
                "text": post.get("text") if isinstance(post.get("text"), str) else None,
                "owner_account_id": owner,
                "verification_status": "verified_publication_owner"
                if verified
                else "quarantined",
                "verification_reason": reason,
                "claim_status": "unreviewed_no_claims_admitted",
            }
        )
        if verified:
            rows["asset_relation"].append(
                {
                    "relation_id": key(
                        "asset_relation", asset_id, confirmed[owner], "published_by"
                    ),
                    "asset_id": asset_id,
                    "entity_id": confirmed[owner],
                    "relation": "published_by",
                    "status": "confirmed",
                    "reason": reason,
                    "evidence_url": next(
                        r["evidence_url"]
                        for r in relations
                        if r["account_id"] == owner and r["status"] == "confirmed"
                    ),
                    "evidence_span": None,
                    "reviewed_at": next(
                        r["reviewed_at"]
                        for r in relations
                        if r["account_id"] == owner and r["status"] == "confirmed"
                    ),
                    "source_id": observed["source_id"],
                    "source_pointer": observed["source_pointer"],
                }
            )
        else:
            reject(
                "asset",
                asset_id,
                reason,
                observed["source_id"],
                observed["source_pointer"],
            )
    rows["account"] = list(accounts.values())
    rows["source"] = list(inputs.sources.values())
    return rows, inputs, as_of


def insert_rows(connection, table, rows):
    if not rows:
        return
    columns = list(rows[0])

    def cell(value):
        if value is None:
            return None
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (str, int, float)):
            return str(value)
        raise TypeError("Graph rows must contain scalar values only")

    # Let the declared DuckDB column types perform the same conversions as the
    # former parameterized inserts, including all-null and large numeric fields.
    batch = pa.table(
        {
            column: pa.array([cell(row[column]) for row in rows], type=pa.string())
            for column in columns
        }
    )
    relation = "_production_graph_batch"
    connection.register(relation, batch)
    try:
        connection.execute(
            f"INSERT INTO {table} ({','.join(columns)}) SELECT {','.join(columns)} FROM {relation}"
        )
    finally:
        connection.unregister(relation)


def query_rows(connection, query):
    cursor = connection.execute(query)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def validate(connection):
    checks = {
        "invalid_current_candidacy": "SELECT count(*) FROM entity WHERE kind='current_candidacy' AND validity IS DISTINCT FROM 'A'",
        "missing_list": "SELECT count(*) FROM entity e LEFT JOIN entity l ON e.list_id=l.entity_id WHERE e.list_id IS NOT NULL AND l.entity_id IS NULL",
        "false_owned_asset": "SELECT count(*) FROM verified_assets v WHERE NOT EXISTS(SELECT 1 FROM verified_accounts a WHERE a.account_id=v.owner_account_id) OR (NOT EXISTS(SELECT 1 FROM asset_observation o WHERE o.asset_id=v.asset_id AND o.observed_account_id=v.owner_account_id AND o.reported_owner_account_id=v.owner_account_id) AND NOT EXISTS(SELECT 1 FROM production_observation p WHERE p.asset_id=v.asset_id AND p.reported_owner_account_id=v.owner_account_id AND p.owner_status='reported_owner' AND (p.lane IN ('standalone_reported_owner','facebook_post','youtube_public_video','x_public_post','tiktok_public_video') OR p.observed_account_id=v.owner_account_id)))",
        "multiple_account_owners": "SELECT count(*) FROM (SELECT account_id FROM account_relation WHERE status='confirmed' GROUP BY account_id HAVING count(DISTINCT entity_id)>1)",
        "verified_account_grain": "SELECT count(*) FROM (SELECT account_id FROM verified_accounts GROUP BY account_id HAVING count(*)>1)",
        "false_publisher_relation": "SELECT count(*) FROM asset_relation r JOIN asset a USING(asset_id) WHERE r.relation='published_by' AND r.status='confirmed' AND (a.verification_status <> 'verified_publication_owner' OR NOT EXISTS(SELECT 1 FROM verified_accounts v WHERE v.account_id=a.owner_account_id AND v.entity_id=r.entity_id))",
        "accumulated_owner_conflict": "WITH observations AS (SELECT asset_id,reported_owner_account_id FROM asset_observation UNION ALL SELECT asset_id,reported_owner_account_id FROM production_observation) SELECT count(*) FROM (SELECT a.asset_id FROM verified_assets a JOIN observations o USING(asset_id) GROUP BY a.asset_id HAVING count(DISTINCT o.reported_owner_account_id)>1)",
        "accumulated_content_conflict": "WITH observations AS (SELECT asset_id,content_sha256 FROM asset_observation UNION ALL SELECT asset_id,content_sha256 FROM production_observation) SELECT count(*) FROM (SELECT a.asset_id FROM verified_assets a JOIN observations o USING(asset_id) GROUP BY a.asset_id HAVING count(DISTINCT o.content_sha256)>1)",
        "historical_conflict_promotion": "SELECT count(*) FROM verified_assets a JOIN quarantine q ON q.grain='asset' AND q.record_id=a.asset_id WHERE q.reason IN ('reported_publication_owner_conflict','content_contradiction','facebook_author_page_mismatch','conflicting_independent_owner_reviews','raw_profile_is_private')",
        "orphan_metric_observation": "SELECT count(*) FROM metric m WHERE (m.account_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM account_observation o WHERE o.observation_id=m.observation_id AND o.account_id=m.account_id)) OR (m.asset_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM asset_observation o WHERE o.observation_id=m.observation_id AND o.asset_id=m.asset_id) AND NOT EXISTS(SELECT 1 FROM production_observation p WHERE p.observation_id=m.observation_id AND p.asset_id=m.asset_id))",
        "unqualified_selection_or_overflow": "SELECT count(*) FROM entity WHERE selection_status IN ('selected_proposal','qualifying_overflow') AND NOT qualified",
        "negative_metric": "SELECT count(*) FROM metric WHERE value < 0",
        "undated_measured_metric": "SELECT count(*) FROM metric WHERE value IS NOT NULL AND observed_at IS NULL",
        "null_without_reason": "SELECT count(*) FROM metric WHERE (value IS NULL) <> (null_reason IS NOT NULL)",
        "owned_downloaded_media": "SELECT count(*) FROM media_resource m JOIN asset a USING(asset_id) WHERE m.status='downloaded' AND a.verification_status <> 'verified_publication_owner'",
        "classification_hash_gate": "SELECT count(*) FROM classification_coverage c JOIN asset a USING(asset_id) WHERE c.content_sha256 IS DISTINCT FROM sha256(a.text)",
        "unknown_speaker_gate": "SELECT count(*) FROM claim WHERE speaker_entity_id IS NOT NULL OR speaker_status <> 'unknown'",
        "claim_unicode_span": "SELECT count(*) FROM claim c JOIN asset a USING(asset_id) WHERE c.evidence_quote IS DISTINCT FROM substring(a.text,c.span_start+1,c.span_end-c.span_start) OR c.text IS DISTINCT FROM c.evidence_quote",
        "claim_coverage_orphan": "SELECT count(*) FROM claim c WHERE NOT EXISTS(SELECT 1 FROM claim_evidence e JOIN classification_coverage v USING(classification_id) WHERE e.claim_id=c.claim_id AND v.asset_id=c.asset_id AND v.review_status='reviewed_claims')",
        "classification_current_unique": "SELECT count(*) FROM (SELECT asset_id FROM classification_coverage WHERE current GROUP BY asset_id HAVING count(*)>1)",
        "claim_superseded_coverage": "SELECT count(*) FROM claim_evidence e JOIN classification_coverage c USING(classification_id) WHERE NOT c.current",
        "asset_topic_superseded_coverage": "SELECT count(*) FROM asset_topic t JOIN classification_coverage c USING(classification_id) WHERE NOT c.current",
        "classification_supersedes_binding": "SELECT count(*) FROM classification_coverage c LEFT JOIN classification_coverage p ON c.supersedes_classification_id=p.classification_id WHERE c.supersedes_classification_id IS NOT NULL AND (p.classification_id IS NULL OR p.asset_id<>c.asset_id OR p.current)",
        "web_content_hash": "SELECT count(*) FROM web_asset WHERE content_sha256 IS DISTINCT FROM sha256(text)",
        "web_relation_source_span": "SELECT count(*) FROM web_relation r JOIN web_asset a USING(asset_id) WHERE r.content_sha256 IS DISTINCT FROM a.content_sha256 OR (r.evidence_quote IS NOT NULL AND r.evidence_quote IS DISTINCT FROM substring(a.text,r.span_start+1,r.span_end-r.span_start))",
        "web_identity_unknown": "SELECT count(*) FROM web_asset WHERE publisher_status<>'unknown' OR subject_status<>'unknown' OR speaker_status<>'unknown'",
        "image_depiction_unknown": "SELECT count(*) FROM source_image WHERE depicted_person_status<>'unknown'",
        "image_download_binding": "SELECT count(*) FROM source_image i LEFT JOIN source s ON i.blob_source_id=s.source_id WHERE (i.download_status='downloaded' AND (i.local_path IS NULL OR i.sha256 IS DISTINCT FROM s.sha256 OR i.bytes IS DISTINCT FROM s.bytes OR i.content_type NOT IN ('image/png','image/jpeg','image/webp','image/gif','image/avif'))) OR (i.download_status<>'downloaded' AND (i.local_path IS NOT NULL OR i.sha256 IS NOT NULL OR i.bytes IS NOT NULL))",
        "image_coverage_binding": "SELECT count(*) FROM entity_photo_coverage c WHERE c.image_count<>(SELECT count(*) FROM source_image i WHERE i.entity_id=c.entity_id) OR c.downloaded_count<>(SELECT count(*) FROM source_image i WHERE i.entity_id=c.entity_id AND i.download_status='downloaded' AND i.relation_status='source_identified') OR c.source_portrait_count<>(SELECT count(*) FROM source_image i WHERE i.entity_id=c.entity_id AND i.download_status='downloaded' AND i.kind='source_bound_portrait' AND i.relation_status='source_identified')",
        "unreviewed_relation_promotion": "SELECT count(*) FROM asset_relation WHERE relation <> 'published_by' AND status='confirmed'",
    }
    checks.update(ELECTION_GATES)
    checks.update(LOGO_GATES)
    failures = {
        name: connection.execute(sql).fetchall()[0][0] for name, sql in checks.items()
    }
    if any(failures.values()):
        raise ValueError(f"Graph quality gates failed: {failures}")
    return {
        "status": "passed",
        "checks": failures,
        "claims_admitted": connection.execute("SELECT count(*) FROM claim").fetchone()[
            0
        ],
        "topics_admitted": connection.execute("SELECT count(*) FROM topic").fetchone()[
            0
        ],
    }


def write_json(path, value):
    with Path(path).open("w") as stream:
        stream.write(packed(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def export_lock(output):
    with (output / ".export.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def export_checkpoint(
    root=DEFAULT_ROOT,
    *,
    output,
    relevance_dir=None,
    reviews=None,
    identity_path=None,
    as_of=None,
    checkpoint_id=None,
    production_root=None,
    identity_reviews=None,
    label_bundle=None,
    media_index=None,
    web_supplement=None,
    image_index=None,
    election_supplement=None,
    logo_supplement=None,
):
    """Commit a validated immutable version, then atomically replace current.json."""
    output = Path(output).resolve()
    root = Path(root).resolve()
    if (
        output == root
        or (root / "data").resolve() == output
        or (root / "data").resolve() in output.parents
    ):
        raise ValueError("Exporter output must be separate from the original lake/data")
    output.mkdir(parents=True, exist_ok=True)
    with export_lock(output):
        graph, inputs, timestamp = build_cached_graph(
            root,
            relevance_dir=relevance_dir,
            reviews=reviews,
            identity_path=identity_path,
            as_of=as_of,
        )
        graph = extend_graph(
            graph,
            inputs,
            timestamp,
            production_root=production_root,
            identity_reviews=identity_reviews,
            label_bundle=label_bundle,
            media_index=media_index,
            web_supplement=web_supplement,
            image_index=image_index,
            election_supplement=election_supplement,
            logo_supplement=logo_supplement,
            helpers={
                "handle": handle,
                "confirmed_owner": confirmed_owner,
                "normalize_metric": normalize_metric,
            },
        )
        content_id = digest(
            packed({"schema": SCHEMA_VERSION, "sources": graph["source"]})
        )[:16]
        checkpoint_id = (
            checkpoint_id
            or datetime.fromisoformat(timestamp).strftime("%Y%m%dT%H%M%S%fZ")
            + "-"
            + content_id
        )
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,160}", checkpoint_id):
            raise ValueError("Unsafe checkpoint ID")
        versions = output / "checkpoints"
        versions.mkdir(exist_ok=True)
        final = versions / checkpoint_id
        if final.exists():
            raise FileExistsError(f"Immutable checkpoint already exists: {final}")
        temporary = Path(tempfile.mkdtemp(prefix=".building-", dir=versions))
        try:
            database = temporary / "graph.duckdb"
            connection = duckdb.connect(str(database))
            try:
                connection.execute(DDL)
                connection.execute("BEGIN TRANSACTION")
                for table in TABLES:
                    insert_rows(connection, table, graph[table])
                quality = validate(connection)
                connection.execute("COMMIT")
                coverage = query_rows(
                    connection,
                    """SELECT a.area_id,a.name,a.city_rank,
                  (SELECT count(*) FROM entity e WHERE e.area_id=a.area_id AND e.kind='current_candidacy') AS valid_candidacies,
                  (SELECT count(*) FROM entity e WHERE e.area_id=a.area_id AND e.kind='current_candidacy' AND e.qualified) AS meaningful_candidates,
                  (SELECT count(*) FROM entity e WHERE e.area_id=a.area_id AND e.kind <> 'local_list' AND e.protected) AS protected_candidates,
                  (SELECT count(*) FROM entity e WHERE e.area_id=a.area_id AND e.selection_status='selected_proposal') AS selected_proposal,
                  (SELECT count(*) FROM entity e WHERE e.area_id=a.area_id AND e.selection_status='qualifying_overflow') AS qualifying_overflow,
                  (SELECT count(*) FROM entity e WHERE e.area_id=a.area_id AND e.kind='local_list') AS retained_lists,
                  (SELECT count(*) FROM entity e WHERE e.area_id=a.area_id AND e.kind='local_list' AND e.qualified) AS relevant_lists,
                  (SELECT count(DISTINCT r.account_id) FROM account_relation r JOIN entity e USING(entity_id) WHERE e.area_id=a.area_id AND e.kind='current_candidacy' AND r.status='confirmed') AS confirmed_person_accounts,
                  (SELECT count(DISTINCT r.account_id) FROM account_relation r JOIN entity e USING(entity_id) WHERE e.area_id=a.area_id AND e.kind='local_list' AND r.status='confirmed') AS confirmed_list_accounts,
                  (SELECT count(*) FROM account_relation r JOIN entity e USING(entity_id) WHERE e.area_id=a.area_id AND r.status <> 'confirmed') AS unresolved_sample_associations,
                  (SELECT count(DISTINCT r.asset_id) FROM asset_relation r JOIN entity e USING(entity_id) WHERE e.area_id=a.area_id AND r.relation='published_by' AND r.status='confirmed') AS owned_publications
                  FROM area a ORDER BY a.city_rank""",
                )
                counts = {table: len(graph[table]) for table in TABLES}
                counts["verified_accounts"] = connection.execute(
                    "SELECT count(DISTINCT account_id) FROM verified_accounts"
                ).fetchall()[0][0]
                counts["verified_assets"] = connection.execute(
                    "SELECT count(*) FROM verified_assets"
                ).fetchall()[0][0]
                views = {
                    "areas.json": query_rows(
                        connection, "SELECT * FROM area ORDER BY city_rank"
                    ),
                    "entities.json": query_rows(
                        connection,
                        "SELECT entity_id,kind,area_id,name,person_cluster_id,person_cluster_status,list_id,position,qualified,protected,selection_status,relevance_score,rule_version,local_role_status,source_url FROM entity WHERE qualified OR kind='local_list' ORDER BY area_id,kind,entity_id",
                    ),
                    "accounts.json": query_rows(
                        connection,
                        "SELECT * FROM verified_accounts ORDER BY account_id",
                    ),
                    "assets.json": query_rows(
                        connection,
                        "SELECT * FROM verified_assets ORDER BY published_at DESC,asset_id",
                    ),
                    "coverage.json": coverage,
                    "media.json": query_rows(
                        connection, "SELECT * FROM media_resource ORDER BY media_id"
                    ),
                    "web-assets.json": query_rows(
                        connection,
                        "SELECT * FROM web_asset ORDER BY observed_at DESC,asset_id",
                    ),
                    "publishers.json": query_rows(
                        connection, "SELECT * FROM publisher ORDER BY publisher_id"
                    ),
                    "web-relations.json": query_rows(
                        connection,
                        "SELECT * FROM web_relation ORDER BY asset_id,relation_id",
                    ),
                    "source-images.json": query_rows(
                        connection,
                        "SELECT * FROM source_image ORDER BY entity_id,image_id",
                    ),
                    "election-lists.json": query_rows(connection, "SELECT * FROM election_list_result ORDER BY area_id,votes DESC,result_id"),
                    "election-candidates.json": query_rows(connection, "SELECT * FROM election_candidate_result ORDER BY area_id,candidate_votes DESC,result_id"),
                    "election-links.json": query_rows(connection, "SELECT * FROM entity_election_link ORDER BY entity_id"),
                    "list-logos.json": query_rows(connection, "SELECT * FROM list_logo ORDER BY entity_id,brand_id"),
                    "list-logo-coverage.json": query_rows(connection, "SELECT * FROM list_logo_coverage ORDER BY entity_id"),
                    "photo-coverage.json": query_rows(
                        connection,
                        "SELECT * FROM entity_photo_coverage ORDER BY entity_id",
                    ),
                    "active-quarantine.json": query_rows(
                        connection,
                        "SELECT * FROM active_quarantine ORDER BY grain,record_id,quarantine_id",
                    ),
                    "claims.json": query_rows(
                        connection, "SELECT * FROM claim ORDER BY claim_id"
                    ),
                    "topics.json": query_rows(
                        connection, "SELECT * FROM topic ORDER BY topic_id"
                    ),
                    "classification-coverage.json": query_rows(
                        connection,
                        "SELECT * FROM classification_coverage ORDER BY classification_id",
                    ),
                    "asset-topics.json": query_rows(
                        connection,
                        "SELECT * FROM asset_topic ORDER BY asset_id,topic_id,classification_id",
                    ),
                    "production-observations.json": query_rows(
                        connection,
                        "SELECT * FROM production_observation ORDER BY observation_id",
                    ),
                    "metric-snapshots.json": query_rows(
                        connection,
                        "SELECT * FROM metric_snapshots ORDER BY platform,asset_id,account_id,name,observed_at",
                    ),
                    "quality.json": quality,
                }
                for name, payload in views.items():
                    write_json(temporary / name, payload)
                connection.execute("CHECKPOINT")
            finally:
                connection.close()
            with database.open("rb") as stream:
                os.fsync(stream.fileno())
            if not inputs.unchanged():
                raise RuntimeError(
                    "Inputs changed during export; current checkpoint unchanged, retry using a stable snapshot"
                )
            files = {
                p.name: {"sha256": digest(p.read_bytes()), "bytes": p.stat().st_size}
                for p in sorted(temporary.iterdir())
                if p.is_file()
            }
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "checkpoint_id": checkpoint_id,
                "created_at": timestamp,
                "status": "validated_cached_checkpoint",
                "counts": counts,
                "quality": quality,
                "files": files,
                "source_inputs": graph["source"],
                "privacy": "allowlisted_public_profile_post_metadata_no_commenter_or_engager_records",
                "coverage": {
                    "collection": "cached_recent_profile_bundles_incomplete_history",
                    "claims": "independently_reviewed_source_statements_unknown_speaker"
                    if graph["claim"]
                    else "none_admitted_pending_independent_review",
                    "geometry": "not_retained",
                    "subscription_billing": "native_subscription_consumption_unpriced_not_zero_billing",
                    "web": "retained_extracted_public_text_unknown_publisher_subject_speaker",
                    "photos": "source_labelled_images_and_owned_account_avatars_no_depicted_identity_inference_explicit_target_gaps",
                },
            }
            write_json(temporary / "manifest.json", manifest)
            sync_dir(temporary)
            os.rename(temporary, final)
            sync_dir(versions)
            pointer = {
                "schema_version": SCHEMA_VERSION,
                "checkpoint_id": checkpoint_id,
                "manifest": str(final.relative_to(output) / "manifest.json"),
                "database": str(final.relative_to(output) / "graph.duckdb"),
                "manifest_sha256": digest((final / "manifest.json").read_bytes()),
                "created_at": timestamp,
            }
            pointer_tmp = output / (".current-" + checkpoint_id + ".json")
            write_json(pointer_tmp, pointer)
            os.replace(pointer_tmp, output / "current.json")
            sync_dir(output)
            return pointer | {"counts": counts, "quality": quality}
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--relevance-dir", type=Path)
    parser.add_argument("--identity", type=Path)
    parser.add_argument("--reviews", nargs="+", type=Path)
    parser.add_argument("--as-of")
    parser.add_argument("--checkpoint-id")
    parser.add_argument("--production-root", type=Path)
    parser.add_argument("--identity-reviews", nargs="+", type=Path)
    parser.add_argument("--label-bundle", type=Path)
    parser.add_argument("--media-index", type=Path)
    parser.add_argument("--web-supplement", type=Path)
    parser.add_argument("--image-index", type=Path)
    parser.add_argument("--election-supplement", type=Path)
    parser.add_argument("--logo-supplement", type=Path)
    args = parser.parse_args()
    result = export_checkpoint(
        args.source_root,
        output=args.output,
        relevance_dir=args.relevance_dir,
        reviews=args.reviews,
        identity_path=args.identity,
        as_of=args.as_of,
        checkpoint_id=args.checkpoint_id,
        production_root=args.production_root,
        identity_reviews=args.identity_reviews,
        label_bundle=args.label_bundle,
        media_index=args.media_index,
        web_supplement=args.web_supplement,
        image_index=args.image_index,
        election_supplement=args.election_supplement,
        logo_supplement=args.logo_supplement,
    )
    print(packed(result))


if __name__ == "__main__":
    main()
