"""Read-only topic navigation over admitted immutable production graph records.

Topic membership is reviewed source classification. Owners, speakers, subjects and
web name mentions are separate relations. Metrics remain dated observations.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlencode

VERSION = "starwatch-topic-navigation/1.0.0"
REVIEWED = "('admitted','independently_reviewed')"
SECTIONS = {"assets", "entities", "claims", "related", "web-sources", "metrics"}
FILTERS = {"area_id", "entity_id", "asset_id", "platform", "since", "until", "q"}


class TopicGraphError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _rows(cp, sql, values=()):
    return _json_value(cp.rows(sql, values))


def _current(cp, alias):
    columns = {row[1] for row in cp.connection.execute("PRAGMA table_info('classification_coverage')").fetchall()}
    current = f'{alias}."current"=true AND ' if "current" in columns else ""
    return current + f"{alias}.review_decision='accept' AND coalesce({alias}.review_topic_errors,'[]')='[]'"


def _accepted_claims(cp):
    sql = f"SELECT c.* FROM claim c WHERE c.review_status IN {REVIEWED}"
    if "classification_coverage" in cp.tables:
        # A modern graph cannot admit a claim without its active review provenance.
        if "claim_evidence" not in cp.tables:
            return sql + " AND false"
        sql += " AND EXISTS(SELECT 1 FROM claim_evidence ce JOIN classification_coverage cc USING(classification_id) WHERE ce.claim_id=c.claim_id AND ce.claim_type='source_statement' AND cc.asset_id=c.asset_id AND " + _current(cp, "cc") + ")"
    return sql


def _accepted_links(cp):
    sql = f"SELECT c.asset_id,ct.topic_id FROM accepted_claims c JOIN claim_topic ct USING(claim_id) WHERE ct.review_status IN {REVIEWED}"
    if "asset_topic" in cp.tables:
        sql += f" UNION SELECT t.asset_id,t.topic_id FROM asset_topic t WHERE t.review_status IN {REVIEWED}"
        if "classification_coverage" in cp.tables:
            sql += " AND EXISTS(SELECT 1 FROM classification_coverage cc WHERE cc.classification_id=t.classification_id AND cc.asset_id=t.asset_id AND " + _current(cp, "cc") + ")"
    return sql


def _owners():
    # The about/depicts/quoted_speaker edges cannot enter this ownership projection.
    return """SELECT DISTINCT r.asset_id,e.entity_id,e.name,e.kind,e.area_id,e.list_id,
        a.owner_account_id AS account_id,v.handle,v.url AS account_url,
        r.evidence_url,r.evidence_span,r.source_id,r.source_pointer
        FROM verified_assets a JOIN asset_relation r USING(asset_id)
        JOIN entity e USING(entity_id)
        JOIN verified_accounts v ON v.account_id=a.owner_account_id AND v.entity_id=e.entity_id
        WHERE r.relation='published_by' AND r.status='confirmed'"""


def _observations(cp):
    sql = "SELECT asset_id,observation_id,observed_at,preview_url,video_url,coverage,source_id,source_pointer FROM asset_observation"
    if "production_observation" in cp.tables:
        sql += " UNION ALL SELECT asset_id,observation_id,observed_at,preview_url,video_url,lane AS coverage,source_id,source_pointer FROM production_observation"
    return "SELECT * FROM (" + sql + ") raw_observation QUALIFY row_number() OVER(PARTITION BY asset_id ORDER BY try_cast(observed_at AS TIMESTAMPTZ) DESC NULLS LAST,observed_at DESC NULLS LAST,observation_id,source_pointer)=1"


def _ctes(cp, p):
    where, values = [], []
    for key in ("asset_id", "platform"):
        if key in p:
            where.append(f"a.{key}=?")
            values.append(p[key])
    ownership, owner_values = [], []
    for key in ("area_id", "entity_id"):
        if key in p:
            ownership.append(f"o.{key}=?")
            owner_values.append(p[key])
    if ownership:
        where.append("EXISTS(SELECT 1 FROM owners o WHERE o.asset_id=a.asset_id AND " + " AND ".join(ownership) + ")")
        values.extend(owner_values)
    for key, operator in (("since", ">="), ("until", "<=")):
        if key in p:
            where.append(f"try_cast(a.published_at AS TIMESTAMPTZ){operator}cast(? AS TIMESTAMPTZ)")
            values.append(p[key])
    scoped = "SELECT a.* FROM verified_assets a" + (" WHERE " + " AND ".join(where) if where else "")
    ctes = "WITH accepted_claims AS (" + _accepted_claims(cp) + "), owners AS (" + _owners() + "), topic_links AS (" + _accepted_links(cp) + "), scope_assets AS (" + scoped + "), linked AS (SELECT DISTINCT l.asset_id,l.topic_id FROM topic_links l JOIN scope_assets a USING(asset_id)), topic_claims AS (SELECT DISTINCT c.claim_id,c.asset_id,ct.topic_id FROM accepted_claims c JOIN claim_topic ct USING(claim_id) JOIN scope_assets a USING(asset_id) WHERE ct.review_status IN " + REVIEWED + "), latest_observation AS (" + _observations(cp) + ") "
    return ctes, values


def _page(cp, ctes, sql, values, p):
    limit, offset = int(p.get("limit", 50)), int(p.get("offset", 0))
    if not 1 <= limit <= 200 or not 0 <= offset <= 100000:
        raise TopicGraphError(400, "invalid_pagination", "Pagination is outside allowed bounds.")
    total = _rows(cp, ctes + "SELECT count(*) total FROM (" + sql + ") result", values)[0]["total"]
    items = _rows(cp, ctes + sql + " LIMIT ? OFFSET ?", [*values, limit, offset])
    return {"checkpoint": cp.identity(), "items": items, "page": {"limit": limit, "offset": offset, "total": total, "has_more": offset + len(items) < total}, "filter_scope": _filter_scope(p), "gaps": _gaps(cp), "topic_navigation_version": VERSION}


def _gaps(cp):
    return cp.gaps() + [
        {"code": "topic_source_classification", "message": "Topics describe reviewed retained source content; they do not establish truth, the owner's position, endorsement or who spoke or is depicted."},
        {"code": "topic_cooccurrence_not_causation", "message": "Related topics share reviewed parent publications within the retained sample; co-occurrence does not establish a causal or political relationship."},
        {"code": "topic_web_mentions_unclassified", "message": "Web name mentions are source-only navigation via publication owners. They have no inherited topic, author, speaker, subject or endorsement attribution."},
    ]


def _filter_scope(p):
    return {key: p[key] for key in sorted(FILTERS - {"q"}) if key in p}


def _topic_url(cp, topic_id, section=None, p=None):
    path = "/api/topics/" + quote(topic_id, safe="")
    if section:
        path += "/" + section
    return path + "?" + urlencode({"checkpoint_id": cp.pointer["checkpoint_id"], **_filter_scope(p or {})})


def _summary_sql():
    return """SELECT t.topic_id,t.label,t.taxonomy_version,
        count(DISTINCT l.asset_id) AS verified_parent_asset_count,
        (SELECT count(DISTINCT tc.claim_id) FROM topic_claims tc WHERE tc.topic_id=t.topic_id) AS source_claim_count,
        count(DISTINCT o.entity_id) AS owner_entity_count,
        count(DISTINCT o.account_id) AS owner_account_count,
        count(DISTINCT a.platform) AS platform_count,
        count(DISTINCT CASE WHEN try_cast(a.published_at AS TIMESTAMPTZ) IS NOT NULL THEN a.asset_id END) AS known_publication_asset_count,
        count(DISTINCT CASE WHEN try_cast(a.published_at AS TIMESTAMPTZ) IS NULL THEN a.asset_id END) AS unknown_publication_asset_count,
        strftime(min(try_cast(a.published_at AS TIMESTAMPTZ)) AT TIME ZONE 'UTC','%Y-%m-%dT%H:%M:%S.%fZ') AS first_published_at,
        strftime(max(try_cast(a.published_at AS TIMESTAMPTZ)) AT TIME ZONE 'UTC','%Y-%m-%dT%H:%M:%S.%fZ') AS last_published_at,
        strftime(min(try_cast(lo.observed_at AS TIMESTAMPTZ)) AT TIME ZONE 'UTC','%Y-%m-%dT%H:%M:%S.%fZ') AS first_latest_observed_at,
        strftime(max(try_cast(lo.observed_at AS TIMESTAMPTZ)) AT TIME ZONE 'UTC','%Y-%m-%dT%H:%M:%S.%fZ') AS last_latest_observed_at
        FROM topic t JOIN linked l USING(topic_id)
        JOIN scope_assets a USING(asset_id)
        LEFT JOIN owners o USING(asset_id)
        LEFT JOIN latest_observation lo USING(asset_id)"""


def topic_listing(cp, p):
    ctes, values = _ctes(cp, p)
    sql = _summary_sql()
    if "q" in p:
        sql += " WHERE strpos(lower(t.label),lower(?))>0"
        values.append(p["q"])
    sql += " GROUP BY t.topic_id,t.label,t.taxonomy_version ORDER BY verified_parent_asset_count DESC,t.topic_id"
    result = _page(cp, ctes, sql, values, p)
    for item in result["items"]:
        item["detail_url"] = _topic_url(cp, item["topic_id"], p=p)
        item["count_grain"] = "distinct_verified_social_parent_asset"
        item["coverage"] = "retained_reviewed_sample_incomplete_history"
    return result


def _require_topic(cp, topic_id, p):
    ctes, values = _ctes(cp, p)
    rows = _rows(cp, ctes + _summary_sql() + " WHERE t.topic_id=? GROUP BY t.topic_id,t.label,t.taxonomy_version", [*values, topic_id])
    if not rows:
        raise TopicGraphError(404, "not_found", "Unknown topic with admitted publications in this scope.")
    return rows[0]


def _latest_metrics_sql():
    # Different values at one observed time remain conflicts. Values are never summed.
    return """SELECT * FROM (
        SELECT m.asset_id,m.platform,m.name,m.unit,m.observed_at,
        count(*) AS observation_count,count(DISTINCT m.observation_id) AS source_observation_count,
        CASE WHEN count(DISTINCT m.value)>1 THEN NULL ELSE max(m.value) END AS value,
        CASE WHEN count(DISTINCT m.value)>1 THEN 'conflicting_values_same_time'
             WHEN count(m.value)=0 THEN min(m.null_reason) ELSE NULL END AS null_reason,
        count(DISTINCT m.value)>1 AS conflict,
        list(DISTINCT m.source_url ORDER BY m.source_url) AS source_urls,
        list(DISTINCT m.source_id ORDER BY m.source_id) AS source_ids,
        list(DISTINCT m.source_pointer ORDER BY m.source_pointer) AS source_pointers,
        list(DISTINCT m.coverage ORDER BY m.coverage) AS coverage
        FROM metric m WHERE m.asset_id IS NOT NULL
        GROUP BY m.asset_id,m.platform,m.name,m.unit,m.observed_at
        ) snapshot QUALIFY row_number() OVER(PARTITION BY asset_id,platform,name,unit
        ORDER BY try_cast(observed_at AS TIMESTAMPTZ) DESC NULLS LAST,observed_at DESC NULLS LAST)=1"""


def _add_asset_context(cp, items):
    if not items:
        return
    ids = [item["asset_id"] for item in items]
    placeholders = ",".join("?" for _ in ids)
    owners = _rows(cp, "WITH owners AS (" + _owners() + ") SELECT * FROM owners WHERE asset_id IN (" + placeholders + ") ORDER BY asset_id,entity_id,account_id", ids)
    metrics = _rows(cp, "SELECT * FROM (" + _latest_metrics_sql() + ") m WHERE asset_id IN (" + placeholders + ") ORDER BY asset_id,platform,name,unit", ids)
    observed = _rows(cp, "SELECT * FROM (" + _observations(cp) + ") lo WHERE asset_id IN (" + placeholders + ")", ids)
    media = _rows(cp, "SELECT asset_id,count(*) AS resource_count,count(*) FILTER(WHERE status IN ('downloaded','retained')) AS retained_resource_count,count(*) FILTER(WHERE status='failed') AS failed_resource_count FROM media_resource WHERE asset_id IN (" + placeholders + ") GROUP BY asset_id", ids) if "media_resource" in cp.tables else []
    for item in items:
        asset_id = item["asset_id"]
        item["publication_owners"] = [row | {"relation": "published_by", "status": "confirmed", "attribution_scope": "publication_owner_only"} for row in owners if row["asset_id"] == asset_id]
        item["latest_metric_snapshots"] = [row for row in metrics if row["asset_id"] == asset_id]
        item["latest_observation"] = next((row for row in observed if row["asset_id"] == asset_id), None)
        item["media_retention"] = next((row for row in media if row["asset_id"] == asset_id), None)
        item["detail_url"] = "/api/assets/" + quote(asset_id, safe="") + "?" + urlencode({"checkpoint_id": cp.pointer["checkpoint_id"]})


def topic_assets(cp, topic_id, p):
    ctes, values = _ctes(cp, p)
    sql = "SELECT a.*,(SELECT count(*) FROM topic_claims tc WHERE tc.asset_id=a.asset_id AND tc.topic_id=l.topic_id) AS topic_source_claim_count FROM scope_assets a JOIN linked l USING(asset_id) WHERE l.topic_id=? ORDER BY try_cast(a.published_at AS TIMESTAMPTZ) DESC NULLS LAST,a.asset_id"
    result = _page(cp, ctes, sql, [*values, topic_id], p)
    _add_asset_context(cp, result["items"])
    result["count_grain"] = "distinct_verified_social_parent_asset"
    return result


def topic_entities(cp, topic_id, p):
    ctes, values = _ctes(cp, p)
    sql = """SELECT o.entity_id,o.name,o.kind,o.area_id,ar.name AS area_name,o.list_id,
        count(DISTINCT l.asset_id) AS verified_parent_asset_count,
        count(DISTINCT tc.claim_id) AS source_claim_count,
        list(DISTINCT o.account_id ORDER BY o.account_id) AS account_ids,
        list(DISTINCT a.platform ORDER BY a.platform) AS platforms,
        strftime(min(try_cast(a.published_at AS TIMESTAMPTZ)) AT TIME ZONE 'UTC','%Y-%m-%dT%H:%M:%S.%fZ') AS first_published_at,
        strftime(max(try_cast(a.published_at AS TIMESTAMPTZ)) AT TIME ZONE 'UTC','%Y-%m-%dT%H:%M:%S.%fZ') AS last_published_at,
        'published_by' AS relation,'confirmed' AS status,
        'publication_owner_only' AS attribution_scope
        FROM linked l JOIN scope_assets a USING(asset_id) JOIN owners o USING(asset_id)
        LEFT JOIN area ar ON ar.area_id=o.area_id
        LEFT JOIN topic_claims tc ON tc.asset_id=l.asset_id AND tc.topic_id=l.topic_id
        WHERE l.topic_id=? GROUP BY o.entity_id,o.name,o.kind,o.area_id,ar.name,o.list_id
        ORDER BY verified_parent_asset_count DESC,o.entity_id"""
    return _page(cp, ctes, sql, [*values, topic_id], p)


def topic_claims(cp, topic_id, p):
    ctes, values = _ctes(cp, p)
    evidence = ",ce.classification_id,ce.claim_type,ce.content_sha256,ce.source_url,ce.context_text,ce.offset_unit" if "claim_evidence" in cp.tables else ",NULL AS classification_id,'source_statement' AS claim_type,NULL AS content_sha256,a.url AS source_url,NULL AS context_text,'unicode_codepoint' AS offset_unit"
    join = " LEFT JOIN claim_evidence ce USING(claim_id)" if "claim_evidence" in cp.tables else ""
    sql = "SELECT c.*,a.url AS asset_source_url,a.platform,a.published_at" + evidence + " FROM topic_claims tc JOIN accepted_claims c USING(claim_id) JOIN scope_assets a ON a.asset_id=c.asset_id" + join + " WHERE tc.topic_id=? ORDER BY try_cast(a.published_at AS TIMESTAMPTZ) DESC NULLS LAST,c.asset_id,c.claim_id"
    result = _page(cp, ctes, sql, [*values, topic_id], p)
    for item in result["items"]:
        item["truth_status"] = "source_statement_not_verified_truth"
        if item["context_text"] is None:
            item["evidence_gap"] = "source_context_not_retained"
    return result


def topic_related(cp, topic_id, p):
    ctes, values = _ctes(cp, p)
    sql = """SELECT t.topic_id,t.label,t.taxonomy_version,
        count(DISTINCT right_link.asset_id) AS shared_parent_asset_count,
        (SELECT count(*) FROM linked WHERE topic_id=?) AS topic_parent_asset_count,
        (SELECT count(*) FROM linked all_right WHERE all_right.topic_id=t.topic_id) AS related_topic_parent_asset_count,
        strftime(min(try_cast(a.published_at AS TIMESTAMPTZ)) AT TIME ZONE 'UTC','%Y-%m-%dT%H:%M:%S.%fZ') AS first_shared_published_at,
        strftime(max(try_cast(a.published_at AS TIMESTAMPTZ)) AT TIME ZONE 'UTC','%Y-%m-%dT%H:%M:%S.%fZ') AS last_shared_published_at,
        count(DISTINCT CASE WHEN try_cast(a.published_at AS TIMESTAMPTZ) IS NULL THEN a.asset_id END) AS unknown_shared_publication_asset_count
        FROM linked left_link JOIN linked right_link USING(asset_id)
        JOIN topic t ON t.topic_id=right_link.topic_id JOIN scope_assets a USING(asset_id)
        WHERE left_link.topic_id=? AND right_link.topic_id<>?
        GROUP BY t.topic_id,t.label,t.taxonomy_version
        ORDER BY shared_parent_asset_count DESC,t.topic_id"""
    result = _page(cp, ctes, sql, [*values, topic_id, topic_id, topic_id], p)
    for item in result["items"]:
        union = item["topic_parent_asset_count"] + item["related_topic_parent_asset_count"] - item["shared_parent_asset_count"]
        item["union_parent_asset_count"] = union
        item["jaccard_cooccurrence"] = item["shared_parent_asset_count"] / union if union else None
        item["relation"] = "reviewed_parent_publication_cooccurrence"
        item["causal_status"] = "not_established"
        item["detail_url"] = _topic_url(cp, item["topic_id"], p=p)
    result["count_grain"] = "distinct_verified_social_parent_asset"
    return result


def _web_sql(cp):
    if not {"web_asset", "web_relation"} <= cp.tables:
        return None
    publisher = "p.name AS reported_publisher_name,p.url AS reported_publisher_url,p.kind AS reported_publisher_kind" if "publisher" in cp.tables else "NULL AS reported_publisher_name,NULL AS reported_publisher_url,NULL AS reported_publisher_kind"
    join = " LEFT JOIN publisher p ON p.publisher_id=w.reported_publisher_id" if "publisher" in cp.tables else ""
    # An exact stored name span is navigation evidence only; rejected proposals vanish.
    return """SELECT DISTINCT w.asset_id,w.url,w.asset_type,w.title,w.published_at,w.observed_at,
        w.reported_publisher_id,""" + publisher + """,w.publisher_status,w.subject_status,w.speaker_status,
        w.text_truncated,w.coverage,w.source_id,w.text_source_id,w.text_source_pointer,
        r.relation_id,r.entity_id,e.name AS matched_name,r.evidence_quote,r.span_start,r.span_end,
        r.content_sha256,r.reason,r.source_id AS mention_source_id,r.source_pointer AS mention_source_pointer,
        'unicode_codepoint' AS offset_unit,'source_only_exact_name_mention' AS association,
        'unknown' AS entity_identity_status,'not_classified' AS topic_status
        FROM web_asset w JOIN web_relation r USING(asset_id) JOIN entity e USING(entity_id)""" + join + """
        WHERE w.public=true AND w.publisher_status='unknown' AND w.subject_status='unknown' AND w.speaker_status='unknown'
        AND r.relation='about' AND r.status='unknown' AND r.evidence_quote=e.name
        AND r.span_start>=0 AND r.span_end>r.span_start AND r.span_end<=length(w.text)
        AND r.content_sha256=w.content_sha256
        AND r.evidence_quote=substring(w.text,r.span_start+1,r.span_end-r.span_start)
        AND EXISTS(SELECT 1 FROM linked l JOIN owners o USING(asset_id) WHERE l.topic_id=? AND o.entity_id=r.entity_id)"""


def topic_web_sources(cp, topic_id, p):
    ctes, values = _ctes(cp, p)
    sql = _web_sql(cp)
    if sql is None:
        result = {"checkpoint": cp.identity(), "items": [], "page": {"limit": int(p.get("limit", 50)), "offset": int(p.get("offset", 0)), "total": 0, "has_more": False}, "filter_scope": _filter_scope(p), "gaps": _gaps(cp), "topic_navigation_version": VERSION}
        result["gaps"].append({"code": "web_sources_not_retained", "message": "This checkpoint has no source-only web mention layer."})
    else:
        result = _page(cp, ctes, sql + " ORDER BY observed_at DESC NULLS LAST,asset_id,entity_id,relation_id", [*values, topic_id], p)
        for item in result["items"]:
            item["detail_url"] = "/api/web-assets/" + quote(item["asset_id"], safe="") + "?" + urlencode({"checkpoint_id": cp.pointer["checkpoint_id"]})
            item["navigation_basis"] = "exact_source_name_matches_registry_name_of_verified_social_publication_owner"
    result["count_grain"] = "exact_source_name_mention_relation_not_unique_article"
    result["admission_status"] = "source_only_unattributed_no_topic_classification"
    result["date_filter_scope"] = "linked_social_publication_dates_not_web_dates"
    return result


def topic_metrics(cp, topic_id, p):
    ctes, values = _ctes(cp, p)
    sql = "SELECT m.*,a.url AS asset_source_url FROM (" + _latest_metrics_sql() + ") m JOIN scope_assets a USING(asset_id) JOIN linked l USING(asset_id) WHERE l.topic_id=? ORDER BY try_cast(m.observed_at AS TIMESTAMPTZ) DESC NULLS LAST,m.asset_id,m.platform,m.name,m.unit"
    result = _page(cp, ctes, sql, [*values, topic_id], p)
    result["count_grain"] = "latest_asset_platform_metric_unit_snapshot"
    result["aggregation"] = "no_sums_latest_dated_observations_conflicts_preserved"
    return result


def topic_detail(cp, topic_id, p):
    item = _require_topic(cp, topic_id, p)
    preview = {**p, "limit": min(int(p.get("limit", 20)), 20), "offset": 0}
    for section, function in (("assets", topic_assets), ("entities", topic_entities), ("claims", topic_claims), ("related", topic_related), ("web-sources", topic_web_sources), ("metrics", topic_metrics)):
        result = function(cp, topic_id, preview)
        field = section.replace("-", "_")
        item[field + "_preview"], item[field + "_page"] = result["items"], result["page"]
    item["navigation"] = {section: _topic_url(cp, topic_id, section, p) for section in sorted(SECTIONS)}
    item["classification_scope"] = "current_accepted_reviewed_source_topics_on_verified_social_parent_assets"
    item["count_grain"] = "distinct_verified_social_parent_asset"
    item["coverage"] = "retained_reviewed_sample_incomplete_history"
    item["web_navigation_scope"] = "unclassified_source_name_mentions_via_verified_social_publication_owners"
    return {"checkpoint": cp.identity(), "item": item, "filter_scope": _filter_scope(p), "gaps": _gaps(cp), "topic_navigation_version": VERSION}


def topic_route(cp, p, topic_id=None, section=None):
    if topic_id is None:
        return topic_listing(cp, p)
    if section is None:
        return topic_detail(cp, topic_id, p)
    if section not in SECTIONS:
        raise TopicGraphError(404, "not_found", "Unknown topic navigation route.")
    _require_topic(cp, topic_id, p)
    return {"assets": topic_assets, "entities": topic_entities, "claims": topic_claims, "related": topic_related, "web-sources": topic_web_sources, "metrics": topic_metrics}[section](cp, topic_id, p)


def export_summary(cp):
    """Return a JSON-safe summary; the coordinator owns checkpoint/export promotion."""
    result = topic_listing(cp, {"limit": 200, "offset": 0})
    result["export_schema"] = "starwatch-topic-summary/1.0.0"
    result["relations"] = []
    for item in result["items"]:
        related = topic_related(cp, item["topic_id"], {"limit": 200, "offset": 0})
        for relation in related["items"]:
            if item["topic_id"] < relation["topic_id"]:
                result["relations"].append({"left_topic_id": item["topic_id"], "right_topic_id": relation["topic_id"], **{key: relation[key] for key in ("shared_parent_asset_count", "topic_parent_asset_count", "related_topic_parent_asset_count", "union_parent_asset_count", "jaccard_cooccurrence", "first_shared_published_at", "last_shared_published_at", "unknown_shared_publication_asset_count", "relation", "causal_status")}})
    return result


def main():
    parser = argparse.ArgumentParser(description="Export a local read-only topic summary from one pinned production checkpoint.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--checkpoint-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from czlake.production_api import PinnedCheckpoint
    with PinnedCheckpoint(args.root, args.checkpoint_id) as cp:
        result = export_summary(cp)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
