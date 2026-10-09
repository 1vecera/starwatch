"""Exact retained-quote verification and measurable citation overlap."""

from __future__ import annotations

import math
import re
from urllib.parse import urlsplit

from pydantic import ValidationError

from ..models import Brief, Evidence, ReportItem
from .base import RunContext


def grounded_evidence(ctx: RunContext, raw: dict | Evidence) -> Evidence:
    evidence = raw if isinstance(raw, Evidence) else Evidence.model_validate(raw)
    item = next((i for i in ctx.items if i.id == evidence.item_id), None)
    if item is None or item.url != evidence.url or item.platform != evidence.platform:
        raise ValueError("citation does not identify a retained item")
    parsed = urlsplit(item.url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username:
        raise ValueError("citation is not a public source URL")
    if evidence.source_kind == "text":
        text, words = item.text, []
        if evidence.timecode is not None or evidence.end_timecode is not None:
            raise ValueError("written text cannot carry a video timecode")
    else:
        transcript = next(
            (t for t in ctx.transcripts if t.item_id == item.id and t.provider == evidence.source_kind),
            None,
        )
        if transcript is None or transcript.url != item.url:
            raise ValueError("cited transcript is not retained")
        text, words = transcript.text, transcript.words
    if not evidence.quote.strip():
        raise ValueError("empty quote")
    start = evidence.quote_start if evidence.quote_start is not None else text.find(evidence.quote)
    end = evidence.quote_end if evidence.quote_end is not None else start + len(evidence.quote)
    if start < 0 or end <= start or text[start:end] != evidence.quote:
        raise ValueError("quote is not verbatim at the retained span")
    updates = {
        "quote_start": start,
        "quote_end": end,
        "published_at": item.published_at,
        "collected_at": item.collected_at,
    }
    if words:
        overlaps = [w for w in words if w.get("char_end", -1) > start and w.get("char_start", len(text)) < end]
        if not overlaps:
            raise ValueError("quote has no retained timestamp alignment")
        cursor = start
        for word in overlaps:
            if re.search(r"\w", text[cursor : max(cursor, word["char_start"])]):
                raise ValueError("quote contains speech without retained timing alignment")
            cursor = max(cursor, word["char_end"])
        if re.search(r"\w", text[cursor:end]):
            raise ValueError("quote ends in speech without retained timing alignment")
        first, last = float(overlaps[0]["start"]), float(overlaps[-1]["end"])
        if not math.isfinite(first) or not math.isfinite(last) or not 0 <= first <= last:
            raise ValueError("invalid retained timings")
        for supplied, actual in (
            (evidence.timecode, first),
            (evidence.end_timecode, last),
        ):
            if supplied is not None and (not math.isfinite(supplied) or abs(supplied - actual) > 0.01):
                raise ValueError("timecode does not match the quoted retained span")
        updates.update(
            timecode=first,
            end_timecode=last,
            timing_granularity=overlaps[0].get("granularity", "word"),
        )
    elif evidence.source_kind != "text":
        raise ValueError("transcript has no usable timings")
    return evidence.model_copy(update=updates)


def verify_items(ctx: RunContext, candidates: list[dict]) -> tuple[list[ReportItem], list[dict]]:
    kept, dropped, seen = [], [], set()
    for raw in candidates:
        try:
            item = ReportItem.model_validate(raw)
            if item.id in seen:
                raise ValueError("duplicate report item ID")
            item.evidence = [grounded_evidence(ctx, e) for e in item.evidence]
            # The active generator is extractive. Facts are attributed statements, not certifications of truth.
            if item.kind == "fact" and item.text != "Source statement: “" + item.evidence[0].quote + "”":
                raise ValueError("extractive fact text diverges from the quoted statement")
            seen.add(item.id)
            kept.append(item)
        except (ValueError, ValidationError, KeyError, TypeError) as error:
            dropped.append({"id": raw.get("id", ""), "reason": str(error)[:180]})
    fact_ids = {i.id for i in kept if i.kind == "fact"}
    verified = []
    for item in kept:
        if item.kind == "inference" and not set(item.based_on).issubset(fact_ids):
            dropped.append(
                {
                    "id": item.id,
                    "reason": "inference references absent or rejected facts",
                }
            )
        else:
            verified.append(item)
    return verified, dropped


def evidence_overlap(left: Brief, right: Brief) -> dict:
    """Measure cited URL overlap, plus exact source-span overlap; empty briefs never pass."""

    def urls(brief: Brief) -> set[str]:
        return {e.url for s in brief.sections for i in s.items for e in i.evidence}

    def spans(brief: Brief) -> set[tuple]:
        return {
            (e.url, e.source_kind, e.quote_start, e.quote_end)
            for s in brief.sections
            for i in s.items
            for e in i.evidence
        }

    a, b = urls(left), urls(right)
    intersection = a & b
    sa, sb = spans(left), spans(right)
    sections_differ = {s.title for s in left.sections} != {s.title for s in right.sections}
    return {
        "left_goal": left.goal.preset,
        "right_goal": right.goal.preset,
        "unit": "source_url",
        "left_citations": len(a),
        "right_citations": len(b),
        "shared": len(intersection),
        "shared_urls": sorted(intersection),
        "jaccard": len(intersection) / len(a | b) if a | b else None,
        "overlap_of_smaller": len(intersection) / min(len(a), len(b)) if a and b else None,
        "span_jaccard": len(sa & sb) / len(sa | sb) if sa | sb else None,
        "different_section_sets": sections_differ,
        "passes": bool(a and b and sections_differ and len(intersection) / min(len(a), len(b)) < 0.5),
    }
