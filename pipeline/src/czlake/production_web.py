"""Explicit retained public web text, with ownership and subject links kept unknown."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

WEB_TABLES = ("publisher", "web_asset", "web_relation")
WEB_DDL = """
CREATE TABLE publisher(publisher_id VARCHAR PRIMARY KEY,name VARCHAR NOT NULL,url VARCHAR NOT NULL,kind VARCHAR NOT NULL,identity_status VARCHAR NOT NULL CHECK(identity_status='unknown'),source_id VARCHAR NOT NULL REFERENCES source(source_id),source_pointer VARCHAR NOT NULL);
CREATE TABLE web_asset(asset_id VARCHAR PRIMARY KEY,url VARCHAR NOT NULL,asset_type VARCHAR NOT NULL,public BOOLEAN NOT NULL CHECK(public),published_at VARCHAR,publication_evidence VARCHAR,observed_at VARCHAR NOT NULL,title VARCHAR NOT NULL,text VARCHAR NOT NULL,content_sha256 VARCHAR NOT NULL,retained_text_path VARCHAR NOT NULL,retained_text_sha256 VARCHAR NOT NULL,text_source_pointer VARCHAR NOT NULL,reported_publisher_id VARCHAR REFERENCES publisher(publisher_id),publisher_status VARCHAR NOT NULL CHECK(publisher_status='unknown'),subject_status VARCHAR NOT NULL CHECK(subject_status='unknown'),speaker_status VARCHAR NOT NULL CHECK(speaker_status='unknown'),text_truncated BOOLEAN NOT NULL,coverage VARCHAR NOT NULL,source_id VARCHAR NOT NULL REFERENCES source(source_id),text_source_id VARCHAR NOT NULL REFERENCES source(source_id),source_pointer VARCHAR NOT NULL);
CREATE TABLE web_relation(relation_id VARCHAR PRIMARY KEY,asset_id VARCHAR NOT NULL REFERENCES web_asset(asset_id),relation VARCHAR NOT NULL CHECK(relation IN ('published_by','about')),publisher_id VARCHAR REFERENCES publisher(publisher_id),entity_id VARCHAR REFERENCES entity(entity_id),status VARCHAR NOT NULL CHECK(status IN ('unknown','rejected')),reason VARCHAR NOT NULL,evidence_quote VARCHAR,span_start INTEGER,span_end INTEGER,content_sha256 VARCHAR NOT NULL,reviewed_at VARCHAR,review_source_id VARCHAR REFERENCES source(source_id),source_id VARCHAR NOT NULL REFERENCES source(source_id),source_pointer VARCHAR NOT NULL,CHECK((relation='published_by' AND publisher_id IS NOT NULL AND entity_id IS NULL) OR (relation='about' AND entity_id IS NOT NULL AND publisher_id IS NULL)));
"""


def serialized(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha(value):
    return hashlib.sha256(
        value if isinstance(value, bytes) else value.encode()
    ).hexdigest()


def public_url(value):
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return (
        value
        if parsed.scheme in {"http", "https"}
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        else None
    )


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(UTC).isoformat() if parsed.tzinfo else None
    except ValueError:
        return None


def import_web_supplement(rows, inputs, path, pin_file):
    """Read source-only rows; a confirmed relationship flag cannot bypass review."""
    selected = Path(path)
    selected = selected if selected.is_absolute() else inputs.root / selected
    selected = selected.resolve()
    document, source_id = inputs.read(selected)
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != "production-web-supplement-v1"
    ):
        raise ValueError("Explicit production web supplement required")
    if any(
        not isinstance(document.get(name, []), list)
        for name in ("assets", "publishers", "relations")
    ):
        raise TypeError("Web supplement records must be arrays")

    def original(reference):
        if not isinstance(reference, dict) or not isinstance(
            reference.get("path"), str
        ):
            raise TypeError("Original extraction/review path and hash required")
        source = Path(reference["path"])
        source = source if source.is_absolute() else selected.parent / source
        source = source.resolve()
        pinned = pin_file(inputs, source, reference.get("sha256"))
        data, loaded = inputs.read(source)
        if loaded != pinned or not isinstance(data, dict):
            raise ValueError("Pinned extraction/review changed or is malformed")
        return source, data, pinned

    publishers = {}
    for index, item in enumerate(document.get("publishers", [])):
        if not isinstance(item, dict):
            raise TypeError("Web publisher context must be an object")
        identifier = item.get("publisher_id")
        if (
            not isinstance(identifier, str)
            or not identifier.startswith("publisher:")
            or identifier in publishers
        ):
            raise ValueError("Unique explicit publisher context ID required")
        if (
            not isinstance(item.get("name"), str)
            or not item["name"].strip()
            or not public_url(item.get("url"))
            or item.get("kind")
            not in {"publisher", "municipality", "local_political_organization"}
        ):
            raise ValueError("Public organizational publisher context required")
        if item.get("identity_status", "unknown") != "unknown":
            raise ValueError(
                "Publisher ownership needs a separate independent review contract"
            )
        publishers[identifier] = {
            "publisher_id": identifier,
            "name": item["name"],
            "url": item["url"],
            "kind": item["kind"],
            "identity_status": "unknown",
            "source_id": source_id,
            "source_pointer": f"/publishers/{index}",
        }
    rows["publisher"] = list(publishers.values())
    assets = {}
    for index, item in enumerate(document.get("assets", [])):
        if not isinstance(item, dict):
            raise TypeError("Web source asset must be an object")
        source_url = public_url(item.get("url"))
        asset_id = item.get("asset_id")
        if not source_url or asset_id != "web:" + sha(source_url) or asset_id in assets:
            raise ValueError(
                "Unique web asset ID must bind the exact selected public URL"
            )
        if item.get("public") is not True or item.get("asset_type") not in {
            "programme",
            "article",
            "official_record",
            "official_website",
            "news",
        }:
            raise ValueError("Explicit public source type required")
        text = item.get("text")
        if (
            not isinstance(text, str)
            or not text.strip()
            or sha(text) != item.get("content_sha256")
        ):
            raise ValueError("Exact nonempty retained web text/hash required")
        if item.get("text_source_pointer") != "/main_text":
            raise ValueError(
                "Web text must bind the sanitized extraction main_text field"
            )
        source, extraction, text_source = original(
            {
                "path": item.get("retained_text_path"),
                "sha256": item.get("retained_text_sha256"),
            }
        )
        observed_at = timestamp(item.get("observed_at"))
        if (
            extraction.get("main_text") != text
            or extraction.get("main_text_sha256") != sha(text)
            or source_url
            not in {extraction.get("source_url"), extraction.get("final_url")}
            or observed_at is None
            or observed_at != timestamp(extraction.get("fetched_at"))
        ):
            raise ValueError(
                "Web text, URL or observation time differs from its retained extraction"
            )
        if not isinstance(item.get("title"), str) or item["title"] != extraction.get(
            "title"
        ):
            raise ValueError("Web title must match the retained source")
        published_at, publication_evidence = (
            item.get("published_at"),
            item.get("publication_evidence"),
        )
        if published_at is not None and (
            not isinstance(published_at, str)
            or not isinstance(publication_evidence, dict)
            or publication_evidence.get("value") != published_at
            or publication_evidence
            not in extraction.get("explicit_publication_dates", [])
        ):
            raise ValueError(
                "Web publication date needs exact retained extraction evidence"
            )
        if published_at is None and publication_evidence is not None:
            raise ValueError(
                "Publication evidence cannot imply an undated publication date"
            )
        reported_publisher = item.get("publisher_id")
        if reported_publisher is not None and reported_publisher not in publishers:
            raise ValueError("Unknown publisher context reference")
        if (
            item.get("source_statement_speaker") is not None
            or item.get("publisher_status", "unknown") != "unknown"
            or item.get("subject_status", "unknown") != "unknown"
        ):
            raise ValueError(
                "Web publisher, subject and speaker stay separate unknowns"
            )
        truncated = extraction.get("text_truncated", False)
        if type(truncated) is not bool:
            raise TypeError("Web extraction truncation must be explicit boolean")
        assets[asset_id] = {
            "asset_id": asset_id,
            "url": source_url,
            "asset_type": item["asset_type"],
            "public": True,
            "published_at": published_at,
            "publication_evidence": serialized(publication_evidence)
            if publication_evidence
            else None,
            "observed_at": observed_at,
            "title": item["title"],
            "text": text,
            "content_sha256": sha(text),
            "retained_text_path": str(source),
            "retained_text_sha256": inputs.sources[source]["sha256"],
            "text_source_pointer": "/main_text",
            "reported_publisher_id": reported_publisher,
            "publisher_status": "unknown",
            "subject_status": "unknown",
            "speaker_status": "unknown",
            "text_truncated": truncated,
            "coverage": "retained_extracted_public_text_only_no_identity_or_speaker_promotion",
            "source_id": source_id,
            "text_source_id": text_source,
            "source_pointer": f"/assets/{index}",
        }
    rows["web_asset"] = list(assets.values())
    entities = {row["entity_id"] for row in rows["entity"]}
    relations = {}
    for index, item in enumerate(document.get("relations", [])):
        if not isinstance(item, dict):
            raise TypeError("Web relationship proposal must be an object")
        asset = assets.get(item.get("asset_id"))
        relation, status = item.get("relation"), item.get("status")
        if (
            asset is None
            or relation not in {"published_by", "about"}
            or status not in {"unknown", "rejected"}
        ):
            raise ValueError(
                "Web relations remain unknown/rejected pending independent registered review"
            )
        publisher, entity = item.get("publisher_id"), item.get("entity_id")
        if (
            relation == "published_by"
            and (publisher not in publishers or entity is not None)
        ) or (
            relation == "about" and (entity not in entities or publisher is not None)
        ):
            raise ValueError(
                "Web publisher and exact existing subject entity must be separate"
            )
        if (
            not isinstance(item.get("reason"), str)
            or not item["reason"].strip()
            or item.get("source_sha256") != asset["content_sha256"]
        ):
            raise ValueError(
                "Web relationship reason and exact source text hash required"
            )
        quote, start, end = (
            item.get("evidence_quote"),
            item.get("start"),
            item.get("end"),
        )
        if quote is not None and (
            not isinstance(quote, str)
            or not quote
            or type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(asset["text"])
            or asset["text"][start:end] != quote
        ):
            raise ValueError("Web proposal span must match exact Unicode source text")
        if quote is None and (start is not None or end is not None):
            raise ValueError("Missing web evidence cannot claim source offsets")
        review_source = None
        if item.get("review_source_path") is not None:
            _, _, review_source = original(
                {
                    "path": item["review_source_path"],
                    "sha256": item.get("review_source_sha256"),
                }
            )
        reviewed_at = timestamp(item.get("reviewed_at"))
        if item.get("reviewed_at") is not None and (
            reviewed_at is None or review_source is None
        ):
            raise ValueError("Dated web rejection requires retained review evidence")
        identifier = (
            "web_relation:"
            + sha(
                serialized(
                    [asset["asset_id"], relation, publisher, entity, source_id, index]
                )
            )[:24]
        )
        relations[identifier] = {
            "relation_id": identifier,
            "asset_id": asset["asset_id"],
            "relation": relation,
            "publisher_id": publisher,
            "entity_id": entity,
            "status": status,
            "reason": item["reason"],
            "evidence_quote": quote,
            "span_start": start,
            "span_end": end,
            "content_sha256": asset["content_sha256"],
            "reviewed_at": reviewed_at,
            "review_source_id": review_source,
            "source_id": source_id,
            "source_pointer": f"/relations/{index}",
        }
    rows["web_relation"] = list(relations.values())
