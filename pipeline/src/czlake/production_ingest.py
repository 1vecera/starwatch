"""Read-only incremental public metadata and explicit independently reviewed labels.

All observations retain their input digest. Raw identity assertions are ignored.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    from .production_facebook_binding import confirmed_facebook_binding
except ImportError:
    from production_facebook_binding import confirmed_facebook_binding

try:
    from .production_web import WEB_DDL, WEB_TABLES, import_web_supplement
    from .production_images import IMAGE_DDL, IMAGE_TABLES, import_image_index
    from .production_elections import ELECTION_DDL, ELECTION_TABLES, import_election_supplement
    from .production_logos import LOGO_DDL, LOGO_TABLES, import_logo_supplement
except ImportError:
    from production_web import WEB_DDL, WEB_TABLES, import_web_supplement
    from production_images import IMAGE_DDL, IMAGE_TABLES, import_image_index
    from production_elections import ELECTION_DDL, ELECTION_TABLES, import_election_supplement
    from production_logos import LOGO_DDL, LOGO_TABLES, import_logo_supplement

try:
    from .production_new_platforms import NEW_ACTORS, PLATFORM_HOSTS, account_identity, independent_new_owner, normalize_new_asset, source_input, allowed_new_media_url, validate_new_media_entry
except ImportError:
    from production_new_platforms import NEW_ACTORS, PLATFORM_HOSTS, account_identity, independent_new_owner, normalize_new_asset, source_input, allowed_new_media_url, validate_new_media_entry

EXTENSION_TABLES = (
    "production_observation",
    "classification_coverage",
    "asset_topic",
    "claim_evidence",
    "media_resource",
)
EXTENSION_DDL = """
CREATE TABLE production_observation(observation_id VARCHAR PRIMARY KEY, asset_id VARCHAR NOT NULL REFERENCES asset(asset_id), platform VARCHAR NOT NULL, lane VARCHAR NOT NULL, observed_account_id VARCHAR REFERENCES account(account_id), reported_owner_account_id VARCHAR REFERENCES account(account_id), owner_status VARCHAR NOT NULL, observed_at VARCHAR, published_at VARCHAR, text VARCHAR, content_sha256 VARCHAR, preview_url VARCHAR, video_url VARCHAR, run_id VARCHAR, batch_id VARCHAR, source_id VARCHAR NOT NULL REFERENCES source(source_id), source_sha256 VARCHAR NOT NULL, source_pointer VARCHAR NOT NULL);
CREATE TABLE classification_coverage(classification_id VARCHAR PRIMARY KEY, asset_id VARCHAR NOT NULL REFERENCES asset(asset_id), content_sha256 VARCHAR NOT NULL, review_status VARCHAR NOT NULL, review_decision VARCHAR NOT NULL, review_reason VARCHAR NOT NULL, review_topic_errors VARCHAR NOT NULL, abstain_reason VARCHAR, claim_limit INTEGER NOT NULL, claims_truncated BOOLEAN NOT NULL, omitted_claims_count INTEGER, basis VARCHAR NOT NULL, note VARCHAR NOT NULL, packet_assets INTEGER NOT NULL, packet_id VARCHAR NOT NULL, classification_assignment VARCHAR NOT NULL, classification_session VARCHAR NOT NULL, review_assignment VARCHAR NOT NULL, review_session VARCHAR NOT NULL, label_sha256 VARCHAR NOT NULL, cards_source_id VARCHAR NOT NULL REFERENCES source(source_id), labels_source_id VARCHAR NOT NULL REFERENCES source(source_id), review_source_id VARCHAR NOT NULL REFERENCES source(source_id), registry_source_id VARCHAR NOT NULL REFERENCES source(source_id), current BOOLEAN NOT NULL, supersedes_classification_id VARCHAR);
CREATE TABLE asset_topic(asset_id VARCHAR NOT NULL REFERENCES asset(asset_id), topic_id VARCHAR NOT NULL REFERENCES topic(topic_id), classification_id VARCHAR NOT NULL REFERENCES classification_coverage(classification_id), review_status VARCHAR NOT NULL, PRIMARY KEY(asset_id,topic_id,classification_id));
CREATE TABLE claim_evidence(claim_id VARCHAR PRIMARY KEY REFERENCES claim(claim_id), classification_id VARCHAR NOT NULL REFERENCES classification_coverage(classification_id), claim_type VARCHAR NOT NULL CHECK(claim_type='source_statement'), content_sha256 VARCHAR NOT NULL, source_url VARCHAR, context_text VARCHAR NOT NULL, offset_unit VARCHAR NOT NULL CHECK(offset_unit='unicode_codepoint'));
CREATE TABLE media_resource(media_id VARCHAR PRIMARY KEY,asset_id VARCHAR NOT NULL REFERENCES asset(asset_id),kind VARCHAR NOT NULL,status VARCHAR NOT NULL,local_path VARCHAR,sha256 VARCHAR,bytes BIGINT,content_type VARCHAR,fetched_at VARCHAR,source_url VARCHAR,final_url VARCHAR,source_envelope VARCHAR NOT NULL,source_envelope_sha256 VARCHAR NOT NULL,source_item_index INTEGER NOT NULL,source_id VARCHAR NOT NULL REFERENCES source(source_id),blob_source_id VARCHAR REFERENCES source(source_id),failure_reason VARCHAR,source_pointer VARCHAR NOT NULL);
CREATE VIEW active_quarantine AS SELECT q.* FROM quarantine q LEFT JOIN asset a ON q.record_id=a.asset_id LEFT JOIN classification_coverage c ON q.grain='classification' AND c.asset_id=q.record_id AND c.labels_source_id=q.source_id WHERE (q.grain <> 'asset' OR a.verification_status='quarantined') AND (q.grain <> 'classification' OR (c.current AND c.review_status='reviewed_rejected'));
CREATE VIEW metric_snapshots AS SELECT account_id,asset_id,platform,name,observed_at,count(*) observation_count,
  CASE WHEN count(DISTINCT value) > 1 THEN NULL ELSE max(value) END AS value,
  CASE WHEN count(DISTINCT value) > 1 THEN 'conflicting_values_same_time' WHEN count(value)=0 THEN min(null_reason) ELSE NULL END AS null_reason,
  count(DISTINCT value)>1 AS conflict
  FROM metric GROUP BY account_id,asset_id,platform,name,observed_at;
"""
EXTENSION_TABLES += WEB_TABLES
EXTENSION_DDL += WEB_DDL
EXTENSION_TABLES += IMAGE_TABLES
EXTENSION_DDL += IMAGE_DDL
EXTENSION_TABLES += ELECTION_TABLES
EXTENSION_DDL += ELECTION_DDL
EXTENSION_TABLES += LOGO_TABLES
EXTENSION_DDL += LOGO_DDL


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha(value):
    return hashlib.sha256(
        value if isinstance(value, bytes) else value.encode()
    ).hexdigest()


def ident(prefix, *values):
    return prefix + ":" + sha(canonical(values))[:24]


def url(value):
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return (
        value
        if parsed.scheme in {"https", "http"}
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        else None
    )


def at(value):
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, UTC).isoformat()
        date = datetime.fromisoformat(value)
        return date.astimezone(UTC).isoformat() if date.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def scalar(value):
    return value if value is None or type(value) in {str, bool, int, float} else None


def identity_documents(inputs, paths):
    """Expand explicit coordinator inputs; bundles pin the original review bytes."""
    for path in paths or []:
        bundle_path = Path(path)
        if not bundle_path.is_absolute():
            bundle_path = inputs.root / bundle_path
        document, source_id = inputs.read(bundle_path)
        if not isinstance(document, dict):
            raise TypeError("Identity review must be an object")
        if document.get("schema_version") != "production-identity-bundle-v1":
            yield document, source_id
            continue
        references = document.get("reviews")
        if not isinstance(references, list) or not references:
            raise ValueError("Identity bundle requires original hashed reviews")
        for reference in references:
            if not isinstance(reference, dict) or not isinstance(
                reference.get("path"), str
            ):
                raise TypeError("Identity review path/hash required")
            selected = Path(reference["path"])
            selected = (
                selected if selected.is_absolute() else bundle_path.parent / selected
            )
            pinned = pin_file(inputs, selected, reference.get("sha256"))
            review, loaded = inputs.read(selected)
            if loaded != pinned or not isinstance(review, dict):
                raise ValueError("Pinned identity review changed or is malformed")
            if review.get("schema_version") == "production-identity-bundle-v1":
                raise ValueError("Nested identity bundles are forbidden")
            yield review, loaded


def extend_graph(
    rows,
    inputs,
    as_of,
    *,
    production_root=None,
    identity_reviews=None,
    label_bundle=None,
    media_index=None,
    web_supplement=None,
    image_index=None,
    election_supplement=None,
    logo_supplement=None,
    helpers=None,
):
    """Extend a cached graph in memory; the caller remains the sole atomic writer."""
    if helpers is None:
        raise ValueError("Graph helpers are required for normalized ingestion")
    h = helpers
    for table in EXTENSION_TABLES:
        rows[table] = []
    accounts = {r["account_id"]: r for r in rows["account"]}
    entities = {r["entity_id"]: r for r in rows["entity"]}
    assets = {r["asset_id"]: r for r in rows["asset"]}
    cached_observations_by_asset = defaultdict(list)
    for observation in rows["asset_observation"]:
        cached_observations_by_asset[observation["asset_id"]].append(observation)
    quarantine_ids = {row["quarantine_id"] for row in rows["quarantine"]}
    confirmed = {
        r["account_id"]: r["entity_id"]
        for r in rows["account_relation"]
        if r["status"] == "confirmed"
    }
    blocked = {
        r["account_id"]: r["reason"]
        for r in rows["account_relation"]
        if r["status"] == "conflicted" or r["reason"] == "raw_profile_is_private"
    }

    def block_owner_relations():
        for account_id, reason in blocked.items():
            confirmed.pop(account_id, None)
            accounts[account_id]["identity_status"] = (
                "unknown" if reason == "raw_profile_is_private" else "conflicted"
            )
            if reason == "raw_profile_is_private":
                accounts[account_id]["public"] = False
            for relation in rows["account_relation"]:
                if relation["account_id"] == account_id:
                    relation.update(
                        status="unknown"
                        if reason == "raw_profile_is_private"
                        else "conflicted",
                        reason=reason,
                    )

    def quarantine(grain, record_id, reason, source_id, pointer):
        record = {
            "quarantine_id": ident(
                "quarantine", grain, record_id, reason, source_id, pointer
            ),
            "grain": grain,
            "record_id": record_id,
            "reason": reason,
            "source_id": source_id,
            "source_pointer": pointer,
        }
        if record["quarantine_id"] not in quarantine_ids:
            rows["quarantine"].append(record)
            quarantine_ids.add(record["quarantine_id"])

    def account(platform, owner):
        owner = account_identity(platform, owner) if platform in PLATFORM_HOSTS else h["handle"](owner)
        if not owner:
            return None
        key = f"{platform}:{owner}"
        accounts.setdefault(
            key,
            {
                "account_id": key,
                "platform": platform,
                "handle": owner,
                "url": f"https://www.{platform}.com/{owner}/",
                "public": None,
                "identity_status": "unknown",
            },
        )
        return key

    # Additional independently reviewed exact proofs are explicit coordinator inputs.
    for document, source_id in identity_documents(inputs, identity_reviews):
        for group in ("candidates", "lists"):
            if not isinstance(document.get(group, {}), dict):
                raise TypeError("Identity review groups must be keyed proof objects")
            for entity_id, proof in document.get(group, {}).items():
                if not isinstance(proof, dict):
                    raise TypeError("Identity proof must be an object")
                entity = entities.get(entity_id)
                platform = proof.get("platform", "instagram")
                profile_url = url(proof.get("profile_url"))
                owner = (
                    proof.get("page_id")
                    if platform == "facebook"
                    else proof.get("handle")
                )
                if platform == "facebook" and not owner and profile_url:
                    owner = urlparse(profile_url).path.strip("/")
                account_id = (
                    account(platform, owner)
                    if platform in {"instagram", "facebook", *PLATFORM_HOSTS}
                    else None
                )
                reason, accepted = "independent_exact_anchor_missing", False
                if platform == "instagram":
                    accepted, reason = h["confirmed_owner"](
                        proof,
                        {
                            "handle": owner,
                            "public": accounts.get(account_id, {}).get("public"),
                        },
                        entity,
                        as_of,
                        require_profile_public=False,
                    )
                elif platform in PLATFORM_HOSTS:
                    accepted, reason = independent_new_owner(proof, entity, as_of, platform)
                    if account_id and profile_url:
                        accounts[account_id]["url"] = profile_url
                elif entity and account_id and profile_url:
                    anchor = url(proof.get("source_url"))
                    date = at(proof.get("observed_at"))
                    age = (
                        (
                            datetime.fromisoformat(as_of) - datetime.fromisoformat(date)
                        ).total_seconds()
                        if date
                        else -1
                    )
                    accepted = all(
                        (
                            proof.get("adjudication") == "confirmed",
                            proof.get("identity_confirmed") is True,
                            proof.get("anchor_links_account") is True,
                            proof.get("public") is True,
                            anchor,
                            urlparse(anchor).hostname
                            not in {
                                "facebook.com",
                                "www.facebook.com",
                                "instagram.com",
                                "www.instagram.com",
                            },
                            urlparse(profile_url).hostname
                            in {"facebook.com", "www.facebook.com"},
                            0 <= age <= 30 * 86400,
                        )
                    )
                    page_id = proof.get("page_id")
                    bridge_accepted = (
                        confirmed_facebook_binding(
                            inputs, proof, entity_id, as_of, pin_file,
                            document.get("reviewer_identity"),
                        )
                        if proof.get("facebook_binding") is not None
                        else False
                    )
                    if (
                        not isinstance(page_id, str)
                        or not page_id.isdigit()
                        or proof.get("page_id_link_confirmed") is not True
                        or urlparse(profile_url).path.strip("/") != page_id
                        or urlparse(profile_url).query
                        or urlparse(profile_url).fragment
                    ):
                        accepted = False
                    exact_href = proof.get("exact_href")
                    if exact_href is not None:
                        parsed_href = urlparse(url(exact_href) or "")
                        href_id = parsed_href.path.strip("/")
                        if href_id == "profile.php":
                            ids = parse_qs(parsed_href.query).get("id", [])
                            href_id = ids[0] if len(ids) == 1 else None
                        if (
                            parsed_href.hostname
                            not in {"facebook.com", "www.facebook.com"}
                            or (href_id != page_id and not bridge_accepted)
                        ):
                            accepted = False
                    if entity["kind"] == "local_list" and (
                        proof.get("scope") != "city_political_organization"
                        or str(proof.get("list_no")) != entity_id.split(":")[-1]
                    ):
                        accepted = False
                    reason = (
                        "independently_reviewed_official_vanity_metadata_numeric_bridge"
                        if accepted and bridge_accepted
                        else "independently_reviewed_exact_page_and_numeric_id"
                        if accepted
                        else "independent_exact_facebook_page_id_anchor_missing"
                    )
                if not entity or not account_id:
                    quarantine(
                        "account_relation",
                        entity_id,
                        "unsupported_or_missing_identity",
                        source_id,
                        f"/{group}/{entity_id}",
                    )
                    continue
                if (
                    accepted
                    and account_id in confirmed
                    and confirmed[account_id] != entity_id
                ):
                    blocked[account_id] = "conflicting_independent_owner_reviews"
                    accepted, reason = False, "conflicting_independent_owner_reviews"
                if account_id in blocked:
                    accepted, reason = False, blocked[account_id]
                rows["account_relation"].append(
                    {
                        "relation_id": ident(
                            "owner_review", source_id, entity_id, account_id
                        ),
                        "entity_id": entity_id,
                        "account_id": account_id,
                        "relation": "owns_account",
                        "status": "confirmed"
                        if accepted
                        else "conflicted"
                        if account_id in blocked
                        else "unknown",
                        "reason": reason,
                        "evidence_url": url(proof.get("source_url")),
                        "evidence_span": scalar(proof.get("excerpt")),
                        "reviewed_at": at(proof.get("observed_at")),
                        "source_id": source_id,
                        "source_pointer": f"/{group}/{entity_id}",
                    }
                )
                if accepted:
                    confirmed[account_id] = entity_id
                    accounts[account_id]["identity_status"] = "confirmed"
    block_owner_relations()

    def metric(
        value,
        name,
        obs_id,
        observed_at,
        source_id,
        pointer,
        source_url,
        platform,
        asset_id,
        account_id=None,
    ):
        normalized, reason = h["normalize_metric"](scalar(value), observed_at)
        rows["metric"].append(
            {
                "metric_id": ident("metric", obs_id, name),
                "account_id": account_id,
                "asset_id": asset_id,
                "observation_id": obs_id,
                "platform": platform,
                "name": name,
                "value": normalized,
                "unit": "count",
                "raw_value": canonical(scalar(value))
                if not isinstance(value, float) or math.isfinite(value)
                else None,
                "null_reason": reason,
                "observed_at": observed_at,
                "source_url": url(source_url),
                "source_id": source_id,
                "source_pointer": pointer,
                "coverage": "bounded_production_sample_not_complete_history",
            }
        )

    pending = []
    if production_root:
        raw_dir = Path(production_root).resolve() / "raw/apify"
        for path in sorted(raw_dir.glob("*.json")):
            envelope, source_id = inputs.read(path)
            if (
                envelope.get("schema_version") != 1
                or envelope.get("policy_version") != "public-metadata-v1"
                or not isinstance(envelope.get("items"), list)
                or len(envelope["items"]) > 10000
            ):
                raise ValueError("Unrecognized production raw envelope/policy")
            actor = envelope.get("actor")
            observed_at = at(envelope.get("fetched_at_epoch"))
            if observed_at is None:
                raise ValueError(
                    "Production envelope requires actual fetched-at timestamp"
                )
            source_sha = inputs.sources[path.resolve()]["sha256"]
            for index, item in enumerate(envelope["items"]):
                if not isinstance(item, dict):
                    raise TypeError("Production metadata record must be an object")
                records = [(item, None, f"/items/{index}")]
                if actor == "apify/instagram-profile-scraper":
                    if item.get("private") is not False:
                        private_account = account("instagram", item.get("username"))
                        if item.get("private") is True and private_account:
                            blocked[private_account] = "raw_profile_is_private"
                        quarantine(
                            "raw_profile",
                            str(item.get("username")),
                            "public_profile_not_confirmed",
                            source_id,
                            f"/items/{index}",
                        )
                        continue
                    observed_profile = account("instagram", item.get("username"))
                    if observed_profile:
                        accounts[observed_profile]["public"] = True
                        profile_pointer = f"/items/{index}"
                        profile_observation_id = ident(
                            "production_profile_observation", source_id, profile_pointer
                        )
                        rows["account_observation"].append(
                            {
                                "observation_id": profile_observation_id,
                                "account_id": observed_profile,
                                "display_name": item.get("fullName")
                                if isinstance(item.get("fullName"), str)
                                else None,
                                "biography": item.get("biography")
                                if isinstance(item.get("biography"), str)
                                else None,
                                "external_url": url(item.get("externalUrl")),
                                "avatar_url": url(
                                    item.get("profilePicUrlHD")
                                    or item.get("profilePicUrl")
                                ),
                                "observed_at": observed_at,
                                "run_id": scalar(envelope.get("run_id")),
                                "source_id": source_id,
                                "source_pointer": profile_pointer,
                                "coverage": "public_profile_snapshot_not_growth_or_local_audience",
                            }
                        )
                        metric(
                            item.get("followersCount"),
                            "followers",
                            profile_observation_id,
                            observed_at,
                            source_id,
                            profile_pointer + "/followersCount",
                            accounts[observed_profile]["url"],
                            "instagram",
                            None,
                            account_id=observed_profile,
                        )
                    records = [
                        (p, observed_profile, f"/items/{index}/latestPosts/{j}")
                        for j, p in enumerate(item.get("latestPosts", []))
                        if isinstance(p, dict)
                    ]
                for record, observed_profile, pointer in records:
                    if actor in {
                        "apify/instagram-scraper",
                        "apify/instagram-profile-scraper",
                    }:
                        platform = "instagram"
                        lane = (
                            "standalone_reported_owner"
                            if actor == "apify/instagram-scraper"
                            else "profile_bundle"
                        )
                        raw_id, text, owner = (
                            scalar(record.get("id")),
                            scalar(record.get("caption")),
                            account(platform, record.get("ownerUsername")),
                        )
                        public_source, published_at, kind = (
                            url(record.get("url")),
                            at(record.get("timestamp")),
                            scalar(record.get("type")),
                        )
                        preview, video = (
                            url(record.get("displayUrl")),
                            url(record.get("videoUrl")),
                        )
                        values = {
                            "likes": record.get("likesCount"),
                            "comments_count": record.get("commentsCount"),
                            "views": record.get("videoViewCount"),
                            "plays": record.get("videoPlayCount"),
                            "shares": None,
                        }
                        owner_status = "reported_owner" if owner else "owner_unknown"
                    elif actor == "apify/facebook-posts-scraper":
                        platform, lane = "facebook", "facebook_post"
                        raw_id, text = (
                            scalar(record.get("postId") or record.get("id")),
                            scalar(record.get("text")),
                        )
                        candidates = []
                        for name in ("user", "owner", "author"):
                            value = record.get(name)
                            if isinstance(value, dict):
                                candidates.append(
                                    scalar(value.get("id"))
                                    or scalar(value.get("username"))
                                )
                        candidates.append(scalar(record.get("userId")))
                        owners = {
                            account(platform, v) for v in candidates if v is not None
                        }
                        owners.discard(None)
                        owner = next(iter(owners)) if len(owners) == 1 else None
                        permalink = url(record.get("topLevelUrl"))
                        page_id = (
                            urlparse(permalink).path.strip("/").split("/")[0]
                            if permalink
                            else None
                        )
                        owner_status = "reported_owner" if owner else "owner_unknown"
                        if len(owners) > 1 or (
                            owner
                            and page_id
                            and page_id.isdigit()
                            and owner != f"facebook:{page_id}"
                        ):
                            owner_status = "author_page_mismatch"
                        public_source = url(record.get("url") or record.get("postUrl"))
                        published_at, kind = (
                            at(record.get("time")) or at(record.get("timestamp")),
                            "Video" if record.get("isVideo") is True else "Post",
                        )
                        media = next(
                            (m for m in record.get("media", []) if isinstance(m, dict)),
                            {},
                        )
                        preview, video = (
                            url(
                                record.get("thumbnailUrl")
                                or record.get("imageUrl")
                                or media.get("thumbnail")
                                or media.get("imageUrl")
                            ),
                            url(record.get("videoUrl") or media.get("videoUrl")),
                        )
                        values = {
                            "likes": record.get("likes"),
                            "comments_count": record.get("comments"),
                            "views": record.get("views")
                            if record.get("views") is not None
                            else record.get("videoViews"),
                            "shares": record.get("shares"),
                        }
                    elif actor in NEW_ACTORS:
                        try:
                            normalized = normalize_new_asset(actor, record, source_input(envelope))
                        except ValueError:
                            quarantine("raw_asset", str(record.get("id")), "new_platform_public_asset_policy_rejected", source_id, pointer)
                            continue
                        platform, lane = normalized["platform"], normalized["lane"]
                        raw_id, text = normalized["raw_id"], normalized["text"]
                        owner = account(platform, normalized["owner"])
                        if owner and normalized["owner_url"]:
                            accounts[owner]["url"] = normalized["owner_url"]
                        public_source, published_at, kind = normalized["public_source"], at(normalized["published_at"]), normalized["kind"]
                        preview, video = url(normalized["preview"]), url(normalized["video"])
                        values = normalized["values"]
                        owner_status = "reported_owner" if owner else "owner_unknown"
                    else:
                        quarantine(
                            "raw_envelope",
                            str(envelope.get("batch_id")),
                            "unsupported_discovery_actor_not_an_asset",
                            source_id,
                            pointer,
                        )
                        continue
                    if type(raw_id) is int and raw_id > 0:
                        raw_id = str(raw_id)
                    if (
                        not isinstance(raw_id, str)
                        or not raw_id.strip()
                        or not isinstance(text, (str, type(None)))
                        or not public_source
                        or urlparse(public_source).hostname
                        not in {
                            f"{platform}.com",
                            f"www.{platform}.com",
                            *(["m.facebook.com"] if platform == "facebook" else []),
                            *PLATFORM_HOSTS.get(platform, set()),
                        }
                    ):
                        quarantine(
                            "raw_asset",
                            str(raw_id),
                            "missing_public_asset_id_url_or_scalar_text",
                            source_id,
                            pointer,
                        )
                        continue
                    asset_id = f"{platform}:{raw_id}"
                    obs_id = ident("production_observation", source_id, pointer)
                    observation = {
                        "observation_id": obs_id,
                        "asset_id": asset_id,
                        "platform": platform,
                        "lane": lane,
                        "observed_account_id": observed_profile,
                        "reported_owner_account_id": owner,
                        "owner_status": owner_status,
                        "observed_at": observed_at,
                        "published_at": published_at,
                        "text": text,
                        "content_sha256": sha(text) if isinstance(text, str) else None,
                        "preview_url": preview,
                        "video_url": video,
                        "run_id": scalar(envelope.get("run_id")),
                        "batch_id": scalar(envelope.get("batch_id")),
                        "source_id": source_id,
                        "source_sha256": source_sha,
                        "source_pointer": pointer,
                    }
                    rows["production_observation"].append(observation)
                    pending.append(
                        (
                            asset_id,
                            platform,
                            kind,
                            public_source,
                            published_at,
                            text,
                            owner,
                            observation,
                        )
                    )
                    for name, value in values.items():
                        metric(
                            value,
                            name,
                            obs_id,
                            observed_at,
                            source_id,
                            pointer,
                            public_source,
                            platform,
                            asset_id,
                        )

    seen = defaultdict(list)
    for values in pending:
        seen[values[0]].append(values)
    block_owner_relations()
    # Recheck cached records too when a new identity proof conflicts with their owner.
    for asset_id, old in list(assets.items()):
        if old["owner_account_id"] in blocked:
            old.update(
                verification_status="quarantined",
                verification_reason=blocked[old["owner_account_id"]],
            )
            rows["asset_relation"] = [
                r for r in rows["asset_relation"] if r["asset_id"] != asset_id
            ]
            proof = next(
                (
                    r
                    for r in rows["account_relation"]
                    if r["account_id"] == old["owner_account_id"]
                ),
                None,
            )
            if proof is None:
                proof = next(
                    r
                    for r in rows["quarantine"]
                    if r["grain"] == "raw_profile"
                    and r["record_id"] == accounts[old["owner_account_id"]]["handle"]
                )
            quarantine(
                "asset",
                asset_id,
                blocked[old["owner_account_id"]],
                proof["source_id"],
                proof["source_pointer"],
            )
        elif (
            asset_id not in seen
            and old["owner_account_id"] in confirmed
            and old["verification_reason"] == "independent_owner_anchor_missing"
        ):
            direct_observations = [
                r
                for r in cached_observations_by_asset[asset_id]
                if r["observed_account_id"] == old["owner_account_id"]
                and r["reported_owner_account_id"] == old["owner_account_id"]
            ]
            if direct_observations:
                observation = max(
                    direct_observations,
                    key=lambda r: (r["observed_at"] or "", r["observation_id"]),
                )
                proof = next(
                    r
                    for r in rows["account_relation"]
                    if r["account_id"] == old["owner_account_id"]
                    and r["status"] == "confirmed"
                )
                old.update(
                    verification_status="verified_publication_owner",
                    verification_reason="independent_anchor_and_direct_reported_owner",
                )
                rows["asset_relation"].append(
                    {
                        "relation_id": ident(
                            "asset_relation",
                            asset_id,
                            confirmed[old["owner_account_id"]],
                            "published_by",
                        ),
                        "asset_id": asset_id,
                        "entity_id": confirmed[old["owner_account_id"]],
                        "relation": "published_by",
                        "status": "confirmed",
                        "reason": old["verification_reason"],
                        "evidence_url": proof["evidence_url"],
                        "evidence_span": None,
                        "reviewed_at": proof["reviewed_at"],
                        "source_id": observation["source_id"],
                        "source_pointer": observation["source_pointer"],
                    }
                )
    for asset_id, observations in seen.items():
        old = assets.get(asset_id)
        owners = {v[6] for v in observations if v[6]}
        texts = {v[5] for v in observations if v[5] is not None}
        cached_observations = cached_observations_by_asset[asset_id]
        owners.update(
            r["reported_owner_account_id"]
            for r in cached_observations
            if r["reported_owner_account_id"]
        )
        texts.update(
            r["text"] for r in cached_observations if r.get("text") is not None
        )
        if old:
            if old["owner_account_id"]:
                owners.add(old["owner_account_id"])
            if old["text"] is not None:
                texts.add(old["text"])
        owner = next(iter(owners)) if len(owners) == 1 else None
        reason = "independent_owner_anchor_missing"
        if len(owners) > 1:
            reason = "reported_publication_owner_conflict"
        elif len(texts) > 1:
            reason = "content_contradiction"
        elif old and old["verification_reason"] in {
            "reported_publication_owner_conflict",
            "content_contradiction",
            "facebook_author_page_mismatch",
            "conflicting_independent_owner_reviews",
            "raw_profile_is_private",
        }:
            reason = old["verification_reason"]
        elif any(v[7]["owner_status"] == "author_page_mismatch" for v in observations):
            reason = "facebook_author_page_mismatch"
        elif owner in blocked:
            reason = blocked[owner]
        elif owner in confirmed:
            direct = any(
                v[7]["lane"] in {"standalone_reported_owner", "facebook_post", "youtube_public_video", "x_public_post", "tiktok_public_video"}
                or v[7]["observed_account_id"] == owner
                for v in observations
            )
            if direct:
                reason = "independent_anchor_and_standalone_reported_owner"
            elif old and old["verification_status"] == "verified_publication_owner":
                reason = old["verification_reason"]
            else:
                reason = "other_owner_in_profile_bundle_not_owned"
        verified = reason in {
            "independent_anchor_and_standalone_reported_owner",
            "independent_anchor_and_direct_reported_owner",
        }
        latest = max(
            observations,
            key=lambda v: (v[7]["observed_at"] or "", v[7]["observation_id"]),
        )
        _, platform, kind, public_source, published_at, text, _, observation = latest
        asset = old or {
            "asset_id": asset_id,
            "platform": platform,
            "asset_type": kind,
            "url": public_source,
            "published_at": published_at,
            "text": text,
            "owner_account_id": owner,
            "verification_status": "quarantined",
            "verification_reason": reason,
            "claim_status": "unreviewed_no_claims_admitted",
        }
        asset.update(
            owner_account_id=owner,
            verification_status="verified_publication_owner"
            if verified
            else "quarantined",
            verification_reason=reason,
        )
        assets[asset_id] = asset
        rows["asset_relation"] = [
            r for r in rows["asset_relation"] if r["asset_id"] != asset_id
        ]
        if verified:
            proof = next(
                r
                for r in rows["account_relation"]
                if r["account_id"] == owner and r["status"] == "confirmed"
            )
            rows["asset_relation"].append(
                {
                    "relation_id": ident(
                        "asset_relation", asset_id, confirmed[owner], "published_by"
                    ),
                    "asset_id": asset_id,
                    "entity_id": confirmed[owner],
                    "relation": "published_by",
                    "status": "confirmed",
                    "reason": reason,
                    "evidence_url": proof["evidence_url"],
                    "evidence_span": None,
                    "reviewed_at": proof["reviewed_at"],
                    "source_id": observation["source_id"],
                    "source_pointer": observation["source_pointer"],
                }
            )
        else:
            quarantine(
                "asset",
                asset_id,
                reason,
                observation["source_id"],
                observation["source_pointer"],
            )
    rows["account"], rows["asset"] = list(accounts.values()), list(assets.values())
    if label_bundle:
        import_label_bundle(rows, inputs, label_bundle)
    if media_index:
        import_media_index(rows, inputs, media_index)
    if web_supplement:
        import_web_supplement(rows, inputs, web_supplement, pin_file)
    if image_index:
        import_image_index(rows, inputs, image_index, pin_file)
    if election_supplement:
        import_election_supplement(rows, inputs, election_supplement, pin_file)
    if logo_supplement:
        import_logo_supplement(rows, inputs, logo_supplement, pin_file)
    rows["source"] = list(inputs.sources.values())
    return rows


def pin_file(inputs, path, expected):
    """Pin bytes before interpreting a coordinator's reference; detect later changes."""
    path = Path(path).resolve()
    data = path.read_bytes()
    actual = sha(data)
    if not isinstance(expected, str) or actual != expected:
        raise ValueError(f"Original artifact hash mismatch: {path.name}")
    previous = inputs.sources.get(path)
    if previous and previous["sha256"] != actual:
        raise ValueError("Referenced artifact changed within export")
    source_id = ident("source", str(path), actual)
    inputs.sources[path] = {
        "source_id": source_id,
        "path": str(path),
        "sha256": actual,
        "bytes": len(data),
    }
    return source_id


def import_label_bundle(rows, inputs, path):
    """Re-run the existing production_labels gates against original registered files."""
    from czlake.production_labels import (
        VERSION,
        digest,
        registered_output,
        reviewed_records,
        text_digest,
        validate_labels,
    )

    bundle_path = Path(path).resolve()
    bundle, _ = inputs.read(bundle_path)
    if bundle.get("schema_version") not in (
        1,
        "production-label-bundle-v1",
    ) or not isinstance(bundle.get("packets"), list):
        raise ValueError(
            "Coordinator label packet manifest required; naked verified flags are forbidden"
        )

    def reference(item, expected=None):
        if isinstance(item, str):
            selected = Path(item)
            selected = (
                selected if selected.is_absolute() else bundle_path.parent / selected
            )
            item = {
                "path": str(selected),
                "sha256": expected or sha(selected.read_bytes()),
            }
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise TypeError("Exact original artifact path required")
        selected = Path(item["path"])
        selected = selected if selected.is_absolute() else bundle_path.parent / selected
        if expected is not None and expected != item.get("sha256"):
            raise ValueError("Packet raw hash disagrees with artifact reference")
        source_id = pin_file(inputs, selected, item.get("sha256"))
        document, loaded_source = inputs.read(selected)
        if loaded_source != source_id:
            raise ValueError("Pinned reference changed while loading")
        return selected.resolve(), document, source_id

    assets = {a["asset_id"]: a for a in rows["asset"]}
    topics = {r["topic_id"]: r for r in rows["topic"]}
    for registry_reference in bundle.get("source_registries", []):
        reference(registry_reference)
    seen_packets = set()
    seen_bindings = set()
    for packet in bundle["packets"]:
        if not isinstance(packet, dict):
            raise TypeError("Packet object required")
        _, registry, registry_source = reference(
            packet.get("registry") or bundle.get("registry"),
            packet.get("registry_sha256"),
        )
        if not isinstance(registry, dict) or not isinstance(
            registry.get("assignments"), list
        ):
            raise TypeError("Frozen coordinator assignment registry required")
        cards_path, cards, cards_source = reference(
            packet.get("cards"), packet.get("cards_sha256")
        )
        labels_path, labels, labels_source = reference(
            packet.get("labels"), packet.get("labels_sha256")
        )
        review_path, review, review_source = reference(
            packet.get("review"), packet.get("review_sha256")
        )
        binding = (cards_source, labels_source, review_source)
        if binding in seen_bindings:
            raise ValueError("Original classification/review packet repeated")
        seen_bindings.add(binding)
        registered_labels = registered_output(labels_path, registry, "classification")
        registered_review = registered_output(
            review_path, registry, "independent_review"
        )
        if digest(registered_labels) != digest(labels) or digest(
            registered_review
        ) != digest(review):
            raise ValueError("Registered output changed during validation")
        packet_id = packet.get("packet_id", labels.get("assignment_id"))
        if not isinstance(packet_id, str) or packet_id in seen_packets:
            raise ValueError("Unique packet IDs required")
        seen_packets.add(packet_id)
        classifier = next(
            r
            for r in registry["assignments"]
            if r["assignment_id"] == labels["assignment_id"]
        )
        reviewer = next(
            r
            for r in registry["assignments"]
            if r["assignment_id"] == review["assignment_id"]
        )
        for assignment in (classifier, reviewer):
            pin_file(inputs, Path(assignment["brief"]), assignment["brief_sha256"])
            if assignment.get("cards_sha256") != inputs.sources[cards_path]["sha256"]:
                raise ValueError(
                    "Original source packet differs from the registered assignment"
                )
            if (
                assignment.get("session_binding", {}).get("source")
                == "native:collaboration"
            ):
                from czlake.production_labels import validate_assignment_provenance

                if not validate_assignment_provenance(assignment, registry):
                    raise ValueError("Unbound native classification/review assignment")
                if Path(assignment["cards_path"]).resolve() != cards_path:
                    raise ValueError(
                        "Native review uses a different original source packet"
                    )
                continue
            receipt = assignment.get("prompt_receipt", {})
            receipt = receipt.get("result", receipt)
            if receipt.get("type") != "agent_prompted" or receipt.get("agent", {}).get(
                "pane_id"
            ) != assignment.get("pane"):
                raise ValueError(
                    "Registry lacks a matching coordinator-observed prompt receipt"
                )
            recorded_session = (
                receipt.get("agent", {}).get("agent_session", {}).get("value")
            )
            if recorded_session and recorded_session != assignment["session_id"]:
                raise ValueError("Prompt receipt session disagrees with registry")
        if (
            classifier.get("session_binding", {}).get("source")
            != "native:collaboration"
            and cards_path.parent != Path(classifier["brief"]).resolve().parent
        ):
            raise ValueError(
                "Original cards must be in the registered classifier directory"
            )
        if not isinstance(cards, list):
            raise TypeError("Original cards array required")
        for card in cards:
            if not isinstance(card, dict):
                raise TypeError("Malformed original source card")
            asset = assets.get(card.get("asset_id"))
            limit = card.get("claim_limit", 3)
            if type(limit) is not int or not 1 <= limit <= 20:
                raise ValueError("Unsupported explicit source-packet claim limit")
            owners = {
                r["entity_id"]
                for r in rows["asset_relation"]
                if r["asset_id"] == card.get("asset_id")
                and r["relation"] == "published_by"
                and r["status"] == "confirmed"
            }
            if (
                not asset
                or asset["verification_status"] != "verified_publication_owner"
                or owners != {card.get("entity_id")}
            ):
                raise ValueError(
                    "Label card owner is not verified in the current graph"
                )
            text = asset.get("text")
            if (
                not isinstance(text, str)
                or card.get("text") != text
                or card.get("content_sha256") != text_digest(text)
            ):
                raise ValueError(
                    "Label card text/hash differs from the current exact graph text"
                )
            if (
                card.get("source_url") != asset["url"]
                or card.get("platform") != asset["platform"]
            ):
                raise ValueError("Label card source/platform differs from the graph")
            if (
                card.get("speaker_entity_id") is not None
                or card.get("speaker_status") != "unknown"
            ):
                raise ValueError(
                    "Named speaker cannot be inherited from a publication owner"
                )
        validation = validate_labels(cards, labels)
        result = reviewed_records(cards, labels, review, registry)
        if (
            not validation["valid"]
            or result["batch_hold"]
            or result["counts"]["reviewed"] != len(cards)
        ):
            raise ValueError(
                "Invalid, stale, incomplete or nonindependent label/review packet"
            )
        verdicts = {v["asset_id"]: v for v in review["items"]}
        for item in labels["items"]:
            verdict = verdicts[item["asset_id"]]
            if verdict["decision"] == "accept" and sorted(
                verdict["reviewed_claim_indexes"]
            ) != list(range(len(item["claims"]))):
                raise ValueError("Accepted label lacks complete claim verdicts")
        labels_by_asset = {
            item["asset_id"]: (index, item)
            for index, item in enumerate(labels["items"])
        }
        verified_assets = {item["asset_id"] for item in result["verified"]}
        for asset_id, (item_index, item) in labels_by_asset.items():
            coverage = item["coverage"]
            classification_id = ident(
                "classification", asset_id, labels_source, review_source
            )
            accepted = asset_id in verified_assets
            status = (
                "reviewed_claims"
                if item["claims"]
                else "reviewed_topics_only"
                if item["topics"]
                else "reviewed_abstention"
            )
            if not accepted:
                status = "reviewed_rejected"
            prior = next(
                (
                    c
                    for c in rows["classification_coverage"]
                    if c["asset_id"] == asset_id and c["current"]
                ),
                None,
            )
            label_hash = digest(item)
            if prior:
                supersedes = packet.get("supersedes", {})
                identical = (
                    prior["label_sha256"] == label_hash
                    and prior["review_status"] == status
                    and prior["review_decision"] == verdicts[asset_id]["decision"]
                    and prior["review_topic_errors"]
                    == canonical(verdicts[asset_id]["topic_errors"])
                )
                if not identical and (
                    not isinstance(supersedes, dict)
                    or supersedes.get(asset_id) != prior["label_sha256"]
                ):
                    raise ValueError(
                        "Changed classification overlap requires exact supersedes label hash"
                    )
                prior["current"] = False
                removed_claims = {
                    c["claim_id"] for c in rows["claim"] if c["asset_id"] == asset_id
                }
                rows["claim"] = [
                    c for c in rows["claim"] if c["claim_id"] not in removed_claims
                ]
                rows["claim_evidence"] = [
                    c
                    for c in rows["claim_evidence"]
                    if c["claim_id"] not in removed_claims
                ]
                rows["claim_topic"] = [
                    c
                    for c in rows["claim_topic"]
                    if c["claim_id"] not in removed_claims
                ]
                rows["asset_topic"] = [
                    c for c in rows["asset_topic"] if c["asset_id"] != asset_id
                ]
            assets[asset_id]["claim_status"] = status
            if not accepted:
                rows["quarantine"].append(
                    {
                        "quarantine_id": ident("label_quarantine", classification_id),
                        "grain": "classification",
                        "record_id": asset_id,
                        "reason": "independent_review_rejected_or_topic_error",
                        "source_id": labels_source,
                        "source_pointer": f"/items/{item_index}",
                    }
                )
            rows["classification_coverage"].append(
                {
                    "classification_id": classification_id,
                    "asset_id": asset_id,
                    "content_sha256": item["content_sha256"],
                    "review_status": status,
                    "review_decision": verdicts[asset_id]["decision"],
                    "review_reason": verdicts[asset_id]["reason"],
                    "review_topic_errors": canonical(
                        verdicts[asset_id]["topic_errors"]
                    ),
                    "abstain_reason": item.get("abstain_reason"),
                    "claim_limit": coverage["claim_limit"],
                    "claims_truncated": coverage["claims_truncated"],
                    "omitted_claims_count": coverage["omitted_claims_count"],
                    "basis": coverage["basis"],
                    "note": coverage["note"],
                    "packet_assets": len(cards),
                    "packet_id": packet_id,
                    "classification_assignment": labels["assignment_id"],
                    "classification_session": labels["session_id"],
                    "review_assignment": review["assignment_id"],
                    "review_session": review["session_id"],
                    "label_sha256": label_hash,
                    "cards_source_id": cards_source,
                    "labels_source_id": labels_source,
                    "review_source_id": review_source,
                    "registry_source_id": registry_source,
                    "current": True,
                    "supersedes_classification_id": prior["classification_id"]
                    if prior
                    else None,
                }
            )
            if not accepted:
                continue
            asset = assets[asset_id]
            asset["claim_status"] = status
            for topic in set(item["topics"]) | {
                t for c in item["claims"] for t in c["topics"]
            }:
                topic_id = f"{VERSION}:{topic}"
                topics.setdefault(
                    topic_id,
                    {"topic_id": topic_id, "label": topic, "taxonomy_version": VERSION},
                )
            for topic in item["topics"]:
                rows["asset_topic"].append(
                    {
                        "asset_id": asset_id,
                        "topic_id": f"{VERSION}:{topic}",
                        "classification_id": classification_id,
                        "review_status": "independently_reviewed",
                    }
                )
            for claim_index, claim in enumerate(item["claims"]):
                claim_id = ident("claim", classification_id, claim_index)
                rows["claim"].append(
                    {
                        "claim_id": claim_id,
                        "asset_id": asset_id,
                        "text": claim["text"],
                        "evidence_quote": claim["text"],
                        "span_start": claim["start"],
                        "span_end": claim["end"],
                        "time_start": None,
                        "time_end": None,
                        "speaker_entity_id": None,
                        "speaker_status": "unknown",
                        "review_status": "independently_reviewed",
                        "source_id": labels_source,
                        "source_pointer": f"/items/{item_index}/claims/{claim_index}",
                    }
                )
                rows["claim_evidence"].append(
                    {
                        "claim_id": claim_id,
                        "classification_id": classification_id,
                        "claim_type": "source_statement",
                        "content_sha256": item["content_sha256"],
                        "source_url": asset["url"],
                        "context_text": asset["text"],
                        "offset_unit": "unicode_codepoint",
                    }
                )
                for topic in claim["topics"]:
                    rows["claim_topic"].append(
                        {
                            "claim_id": claim_id,
                            "topic_id": f"{VERSION}:{topic}",
                            "review_status": "independently_reviewed",
                        }
                    )
    active_topics = {r["topic_id"] for r in rows["asset_topic"] + rows["claim_topic"]}
    rows["topic"] = [v for k, v in topics.items() if k in active_topics]


def import_media_index(rows, inputs, path):
    """Join retained bytes locally; never download or invent a served media URL."""
    from czlake.production_media import allowed_url, media_type
    from czlake.production_facebook_media import allowed_facebook_image_url, validate_facebook_media_entry

    document, source_id = inputs.read(path)
    if document.get("schema_version") != "production-media-v1" or not isinstance(
        document.get("records"), list
    ):
        raise ValueError("Coordinator source-bound media index required")
    assets = {r["asset_id"]: r for r in rows["asset"]}
    seen, verified_snapshots = set(), set()
    for index, record in enumerate(document["records"]):
        if (
            not isinstance(record, dict)
            or record.get("kind") not in {"image", "video"}
            or record.get("status") not in {"downloaded", "failed", "skipped"}
        ):
            raise ValueError("Unknown media record kind/status")
        media_id, asset_id = record.get("media_id"), record.get("asset_id")
        if not isinstance(media_id, str) or not media_id or media_id in seen:
            raise ValueError("Unique media IDs required")
        seen.add(media_id)
        source = Path(record["source_envelope"]).resolve()
        source_doc, _ = inputs.read(source)
        source_sha = inputs.sources[source]["sha256"]
        source_index = record.get("source_item_index")
        if (
            source_sha != record.get("source_envelope_sha256")
            or source_doc.get("schema_version") != 1
            or source_doc.get("policy_version") != "public-metadata-v1"
            or type(source_index) is not int
            or not 0 <= source_index < len(source_doc.get("items", []))
        ):
            raise ValueError("Media source envelope hash/index changed")
        original = source_doc["items"][source_index]
        pointer = f"/items/{source_index}"
        actor = source_doc.get("actor")
        if actor == "apify/instagram-profile-scraper":
            from czlake.production_collect import public_metadata

            post_index = record.get("source_post_index")
            if (
                not isinstance(original, dict)
                or original.get("private") is not False
                or type(post_index) is not int
                or not isinstance(original.get("latestPosts"), list)
                or not 0 <= post_index < len(original["latestPosts"])
            ):
                raise ValueError(
                    "Media profile source requires an exact public post index"
                )
            lineage = source_doc.get("original_source")
            if lineage is not None:
                if not isinstance(lineage, dict) or not isinstance(
                    lineage.get("path"), str
                ):
                    raise ValueError(
                        "Sanitized media source requires original path/hash lineage"
                    )
                original_path = Path(lineage["path"]).resolve()
                pinned = pin_file(inputs, original_path, lineage.get("sha256"))
                original_doc, loaded = inputs.read(original_path)
                if (
                    loaded != pinned
                    or original_doc.get("actor") != actor
                    or source_index >= len(original_doc.get("items", []))
                    or public_metadata(actor, original_doc["items"][source_index])
                    != original
                ):
                    raise ValueError(
                        "Sanitized media source differs from its original projection"
                    )
            original = original["latestPosts"][post_index]
            pointer += f"/latestPosts/{post_index}"
        if actor in NEW_ACTORS:
            validate_new_media_entry(actor, original, pointer, {**record, "url": record.get("source_url")}, source_input(source_doc))
            media_pointer = record["source_media_pointer"]
        elif actor == "apify/facebook-posts-scraper":
            facebook_owner = validate_facebook_media_entry(original, pointer, record)
            evidence = record["verified_asset_evidence"]
            evidence_key = (str(Path(evidence["path"]).resolve()), evidence["sha256"])
            if evidence_key not in verified_snapshots:
                pin_file(inputs, Path(evidence_key[0]), evidence_key[1])
                verified_snapshots.add(evidence_key)
            media_pointer = record["source_media_pointer"]
        else:
            field = "displayUrl" if record["kind"] == "image" else "videoUrl"
            media_pointer = record.get("source_media_pointer", pointer + "/" + field)
            if not isinstance(media_pointer, str) or not media_pointer.startswith(
                pointer + "/"
            ):
                raise ValueError("Media pointer must stay within its exact source asset")
            suffix = media_pointer[len(pointer) + 1 :]
            allowed_leaf = (
                r"(?:displayUrl|images/[0-9]+)"
                if record["kind"] == "image"
                else r"videoUrl"
            )
            if re.fullmatch(r"(?:childPosts/[0-9]+/){0,3}" + allowed_leaf, suffix) is None:
                raise ValueError("Only exact public asset media fields may be selected")
            selected_media = original
            try:
                for component in suffix.split("/"):
                    selected_media = (
                        selected_media[int(component)]
                        if isinstance(selected_media, list)
                        else selected_media[component]
                    )
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ValueError("Source media pointer is missing") from exc
            if (
                actor not in {"apify/instagram-scraper", "apify/instagram-profile-scraper"}
                or not isinstance(original, dict)
                or f"instagram:{original.get('id')}" != asset_id
                or selected_media != record.get("source_url")
                or not allowed_url(record.get("source_url"))
            ):
                raise ValueError(
                    "Media URL/asset differs from its allowlisted source record"
                )
        fetched_at = at(record.get("fetched_at"))
        if fetched_at is None:
            raise ValueError("Media index requires actual observation timestamp")
        asset = assets.get(asset_id)
        if not asset or asset["verification_status"] != "verified_publication_owner":
            rows["quarantine"].append(
                {
                    "quarantine_id": ident("media_quarantine", source_id, media_id),
                    "grain": "media",
                    "record_id": media_id,
                    "reason": "media_asset_owner_not_verified",
                    "source_id": source_id,
                    "source_pointer": f"/records/{index}",
                }
            )
            continue
        if actor == "apify/facebook-posts-scraper" and asset.get("owner_account_id") != facebook_owner:
            raise ValueError("Facebook retained media owner differs from graph admitted owner")
        local_path, blob_source, size, content_type = None, None, None, None
        if record["status"] == "downloaded":
            local = Path(record["path"]).resolve()
            blob_source = pin_file(inputs, local, record.get("sha256"))
            size = local.stat().st_size
            if (
                type(record.get("bytes")) is not int
                or size != record["bytes"]
                or size <= 0
            ):
                raise ValueError("Downloaded media byte count differs from actual file")
            with local.open("rb") as stream:
                content_type = media_type(stream.read(32), record["kind"])
            if (
                content_type is None
                or content_type != record.get("content_type")
                or not allowed_url(record.get("final_url"))
                or (actor == "apify/facebook-posts-scraper" and not allowed_facebook_image_url(record.get("final_url")))
                or (actor in NEW_ACTORS and not allowed_new_media_url(record.get("final_url"), asset["platform"]))
            ):
                raise ValueError(
                    "Downloaded media type/final URL differs from the retained record"
                )
            local_path = str(local)
        elif any(record.get(name) is not None for name in ("path", "sha256", "bytes")):
            raise ValueError("Failed/skipped media cannot claim retained bytes")
        rows["media_resource"].append(
            {
                "media_id": media_id,
                "asset_id": asset_id,
                "kind": record["kind"],
                "status": record["status"],
                "local_path": local_path,
                "sha256": record.get("sha256") if local_path else None,
                "bytes": size,
                "content_type": content_type,
                "fetched_at": fetched_at,
                "source_url": record.get("source_url"),
                "final_url": url(record.get("final_url")) if local_path else None,
                "source_envelope": str(source),
                "source_envelope_sha256": source_sha,
                "source_item_index": source_index,
                "source_id": source_id,
                "blob_source_id": blob_source,
                "failure_reason": scalar(
                    record.get("reason") or record.get("error_type")
                ),
                "source_pointer": media_pointer,
            }
        )
