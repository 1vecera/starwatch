"""Goal-specific extractive briefs: every statement is quoted, every inference is labelled."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from ..events import now_iso
from ..goals import PRESETS
from ..models import Brief, RunInfo, Section, Subject
from .base import RunContext, Step, StepResult
from .evidence import verify_items
from .extract import folded, sentence_spans

LIMITATIONS = [
    "Extractive mode: quoted source statements are verified against retained text, not independently certified as true.",
    "Tool-free signed-in Codex inference has not been established; no LLM synthesis or model tokens were used.",
    "Video transcripts can contain multiple speakers; a quote from a subject's video is not speaker identification.",
    "Independent news, numeric-claim checking and contradiction adjudication are unavailable in this collection.",
]


def dated(value: str) -> datetime | None:
    try:
        result = datetime.fromisoformat(value) if value else None
        return result if result is None or result.tzinfo is not None else None
    except ValueError:
        return None


def select_claims(claims: list[dict], *, limit: int, used: set[str], key, per_item: int = 2) -> list[dict]:
    selected, counts = [], {}
    for claim in sorted(claims, key=key, reverse=True):
        quote = folded(claim["evidence"][0]["quote"])
        item_id = claim["item_ids"][0]
        quote_key = "quote:" + quote
        if claim["id"] in used or quote_key in used or counts.get(item_id, 0) >= per_item:
            continue
        selected.append(claim)
        counts[item_id] = counts.get(item_id, 0) + 1
        used.add(quote_key)
        used.add(claim["id"])
        if len(selected) >= limit:
            break
    return selected


def gap(gid: str, tag: str, text: str, *, kind: str = "missing_source") -> dict:
    return {
        "id": f"{gid}-{tag}",
        "kind": kind,
        "text": text,
        "evidence": [],
        "based_on": [],
        "confidence": "low",
    }


def relevance(claim: dict, text: str) -> int:
    meaningful = [
        w
        for w in re.findall(r"\w+", folded(text))
        if len(w) > 4
        and w
        not in {
            "debate",
            "respond",
            "background",
            "fiala",
            "petr",
            "positions",
            "topic",
            "their",
            "statement",
        }
    ]
    quote = folded(claim["evidence"][0]["quote"])
    score = sum(w[:5] in quote for w in meaningful)
    aliases = {
        "Education": ("school", "education", "skol", "vzdel"),
        "Energy and prices": ("energy", "price", "energi", "cen", "fuel", "benzin"),
        "Public finance": ("budget", "finance", "rozpoc", "deficit"),
    }
    for name, words in aliases.items():
        if name in claim.get("topics", []) and any(w in folded(text) for w in words):
            score += 3
    return score


class PlanAndWrite(Step):
    id = "write"
    label = "Plan and write"
    group = "downstream"

    async def run(self, ctx: RunContext) -> StepResult:
        gid = ctx.goal.preset
        planned = {title: [] for title in PRESETS[gid].sections}
        titles = list(planned)
        used: set[str] = set()
        claims = ctx.claims
        by_id = {i.id: i for i in ctx.items}

        def recent(c):
            return c["evidence"][0]["published_at"]

        def g1_rank(c):
            e = c["evidence"][0]
            return (
                relevance(c, ctx.goal.text),
                {"scribe": 3, "tiktok_asr": 1, "text": 2}[e["source_kind"]],
                len(c.get("topics", [])),
                recent(c),
                -len(e["quote"]),
            )

        if gid == "G1":
            positions = [c for c in claims if c["category"] == "position"]
            substantive = [c for c in positions if set(c.get("topics", [])) - {"Public roles"}]
            planned[titles[0]] = select_claims(substantive or positions, limit=6, used=used, key=g1_rank)
            planned[titles[1]] = select_claims(
                [c for c in claims if c["category"] == "numeric"],
                limit=3,
                used=used,
                key=lambda c: (
                    relevance(c, ctx.goal.text),
                    bool(
                        re.search(
                            r"procent|korun|milion|miliard|třiceti",
                            c["evidence"][0]["quote"],
                            re.IGNORECASE,
                        )
                    ),
                    g1_rank(c),
                ),
                per_item=1,
            )
            planned[titles[1]].append(
                gap(
                    gid,
                    "numeric-check",
                    "Which original datasets support these numbers? The quoted figures have not been independently checked.",
                    kind="open_question",
                )
            )
            pairs = []
            comparison_facts = [c for c in planned[titles[0]] + planned[titles[1]] if c["kind"] == "fact"]
            for left in comparison_facts:
                for right in comparison_facts:
                    a, b = left["evidence"][0], right["evidence"][0]
                    if (
                        a["url"] != b["url"]
                        and a["published_at"]
                        and b["published_at"]
                        and a["published_at"] != b["published_at"]
                        and (set(left.get("topics", [])) & set(right.get("topics", []))) - {"Public roles"}
                    ):
                        pairs = [left, right]
                        break
                if pairs:
                    break
            if len(pairs) == 2:
                planned[titles[2]].append(
                    {
                        "id": f"{gid}-comparison",
                        "kind": "inference",
                        "confidence": "low",
                        "text": "Comparison for review: read the two dated source statements with their context and speakers. This is not an established contradiction.",
                        "evidence": [p["evidence"][0] for p in pairs],
                        "based_on": [p["id"] for p in pairs],
                    }
                )
            planned[titles[2]].append(
                gap(
                    gid,
                    "contradiction",
                    "No self-inconsistency has been established from this bounded collection; a contradiction needs compatible context and identified speakers.",
                )
            )
            if planned[titles[0]]:
                first = planned[titles[0]][0]
                planned[titles[3]].append(
                    {
                        "id": f"{gid}-question",
                        "kind": "inference",
                        "confidence": "low",
                        "text": "Likely follow-up question: what primary evidence supports the quoted position, and what qualifications apply?",
                        "evidence": [],
                        "based_on": [first["id"]],
                    }
                )
        elif gid == "G2":
            urls = re.findall(r"https?://[^\s<>]+", ctx.goal.text)
            posts = [i for i in ctx.items if i.kind in ("post", "video") and dated(i.published_at)]
            trigger = (
                next((i for i in posts if i.url.rstrip("/") == urls[0].rstrip("/")), None)
                if urls
                else max(posts, key=lambda i: i.published_at, default=None)
            )
            if trigger is None:
                planned[titles[0]].append(
                    gap(
                        gid,
                        "trigger",
                        "The requested triggering post is not retained. Collect or select that public post before preparing a response.",
                    )
                )
            else:
                current = [c for c in claims if c["item_ids"] == [trigger.id]]
                planned[titles[0]] = select_claims(
                    current,
                    limit=1,
                    used=used,
                    key=lambda c: (
                        c["evidence"][0]["source_kind"] == "text",
                        -c["evidence"][0]["quote_start"],
                    ),
                )
                planned[titles[1]] = select_claims(current, limit=2, used=used, key=g1_rank)
                current_topics = {t for c in current for t in c.get("topics", []) if t != "Public roles"}
                spans = sentence_spans(trigger.text)
                topic_text = trigger.text[slice(*spans[0])] if spans else trigger.text
                context_words = {w[:6] for w in re.findall(r"\w+", folded(topic_text)) if len(w) > 5}
                related = [
                    c
                    for c in claims
                    if c["item_ids"] != [trigger.id]
                    and set(c.get("topics", [])) & current_topics
                    and any(w in folded(c["evidence"][0]["quote"]) for w in context_words)
                    and recent(c)
                    and recent(c) < trigger.published_at
                ]
                within30 = [
                    c
                    for c in related
                    if dated(recent(c)) and dated(recent(c)) >= dated(trigger.published_at) - timedelta(days=30)
                ]
                planned[titles[2]] = select_claims(
                    within30 or related,
                    limit=3,
                    used=used,
                    key=lambda c: (
                        bool(set(c.get("topics", [])) & current_topics),
                        recent(c),
                    ),
                )
                if not within30:
                    planned[titles[2]].append(
                        gap(
                            gid,
                            "recency",
                            "No related earlier statement from the 30 days before the trigger is retained; any shown context is older.",
                        )
                    )
                if planned[titles[0]]:
                    first = planned[titles[0]][0]
                    planned[titles[3]].append(
                        {
                            "id": f"{gid}-draft",
                            "kind": "inference",
                            "confidence": "low",
                            "text": "Draft response point for manual review: quote the statement accurately and ask for its original supporting source and relevant qualifications.",
                            "evidence": [],
                            "based_on": [first["id"]],
                        }
                    )
            planned[titles[4]].append(
                gap(
                    gid,
                    "questions",
                    "What evidence beyond the subject's own account corroborates the triggering statement?",
                    kind="open_question",
                )
            )
        else:
            websites = [c for c in claims if c["evidence"][0]["platform"] == "website"]
            home = [
                c
                for c in websites
                if by_id[c["item_ids"][0]].url.rstrip("/")
                in {a.url.rstrip("/") for a in ctx.accounts if a.platform == "website"}
            ]
            planned[titles[0]] = select_claims(
                home or websites,
                limit=1,
                used=used,
                key=lambda c: (
                    c["category"] == "roles",
                    -c["evidence"][0]["quote_start"],
                ),
            )
            planned[titles[0]].append(
                gap(
                    gid,
                    "identity-record",
                    f"Identity resolution retained {len(ctx.accounts)} accounts and {len(ctx.rejected)} rejected look-alikes; inspect the match basis and rejection reasons in the subject record.",
                    kind="open_question",
                )
            )
            roles = [c for c in websites if c["category"] == "roles"]
            planned[titles[1]] = select_claims(
                roles,
                limit=4,
                used=used,
                key=lambda c: (
                    any(part in c["evidence"][0]["url"] for part in ("/o-mne", "/bio", "/about", "/profil")),
                    len(c["evidence"][0]["quote"]),
                    recent(c),
                ),
            )
            # Timeline favours dated written public activity; G1 favours spoken topic positions.
            timeline = [c for c in claims if c["evidence"][0]["source_kind"] == "text" and recent(c)]
            platforms, activities = set(), set()
            for c in sorted(timeline, key=recent, reverse=True):
                platform = c["evidence"][0]["platform"]
                activity = folded(by_id[c["item_ids"][0]].text[:140])
                if platform in platforms or activity in activities or c["id"] in used:
                    continue
                platforms.add(platform)
                activities.add(activity)
                used.add(c["id"])
                planned[titles[2]].append(c)
                if len(planned[titles[2]]) >= 3:
                    break
            planned[titles[3]] = select_claims(
                [c for c in websites if c["category"] == "controversy"],
                limit=2,
                used=used,
                key=lambda c: len(c["evidence"][0]["quote"]),
            )
            planned[titles[3]].append(
                gap(
                    gid,
                    "independent-news",
                    "Only statements retained on the subject's own website are available here; independent reporting and adjudication of controversies are missing.",
                )
            )
            for row in ctx.coverage.values():
                if row.status != "collected":
                    planned[titles[4]].append(
                        gap(
                            gid,
                            f"coverage-{row.platform}",
                            f"{row.platform}: {row.status}. {row.note}",
                        )
                    )
            planned[titles[4]].append(
                gap(
                    gid,
                    "sources",
                    "Independent news search and primary public-register checks were not performed in this retained collection.",
                )
            )
        for title, items in planned.items():
            if not items:
                items.append(
                    gap(
                        gid,
                        "empty-" + str(titles.index(title)),
                        "No retained evidence meets this section's criteria.",
                    )
                )
        all_candidates = [i for values in planned.values() for i in values]
        verified, dropped = verify_items(ctx, all_candidates)
        kept = {i.id: i for i in verified}
        sections = [
            Section(title=title, items=[kept[i["id"]] for i in values if i["id"] in kept])
            for title, values in planned.items()
        ]
        validation = {
            "scope": "exact_retained_quotes_and_inference_links",
            "kept": len(verified),
            "dropped": len(dropped),
            "rejected": dropped,
            "facts": sum(i.kind == "fact" for i in verified),
            "video_quotes": sum(any(e.source_kind != "text" for e in i.evidence) for i in verified if i.kind == "fact"),
            "independent_truth_check": False,
            "all_evidence_available": "claims.json",
        }
        transcript_coverage = ctx.store.read_json(ctx.run_id, "transcription-coverage.json") or {}
        limitations = list(LIMITATIONS)
        limitations.append(
            "Place and topic detection uses a small explicit keyword lexicon; other mentions were not assessed."
        )
        if transcript_coverage.get("missing_item_ids"):
            limitations.append(
                f"{len(transcript_coverage['missing_item_ids'])} collected videos have no retained timed transcript."
            )
        ctx.brief = Brief(
            subject=Subject(
                name=ctx.subject,
                anchor=ctx.anchor,
                accounts=ctx.accounts,
                rejected=ctx.rejected,
            ),
            goal=ctx.goal,
            sections=sections,
            coverage=list(ctx.coverage.values()),
            run=RunInfo(
                started_at=ctx.started_at,
                finished_at=now_iso(),
                mode=ctx.mode,
                costs=ctx.costs,
                source_run_id=ctx.source_run_id,
                source_costs=ctx.source_costs,
            ),
            generator="extractive",
            limitations=limitations,
            verification=validation,
        )
        ctx.save_json("brief.json", ctx.brief)
        ctx.save_json("brief-verification.json", validation)
        await ctx.data(
            self.id,
            brief=ctx.brief.model_dump(),
            claims=[i.model_dump() for i in verified],
            kept=len(verified),
            dropped=len(dropped),
            summary=f"{gid}: {len(sections)} sections, {validation['facts']} quoted statements, {len(dropped)} rejected",
        )
        return StepResult(
            "done",
            count=len(verified),
            note=f"{gid}: {len(sections)} sections; extractive, verified citations",
        )
