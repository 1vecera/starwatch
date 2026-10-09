"""Extract attributed statements without giving untrusted source text any tool access."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from itertools import pairwise

from ..models import Evidence, Transcript
from .base import RunContext, Step, StepResult
from .evidence import verify_items

# These labels describe public subject posts, not voters or personal traits.
TOPICS = {
    "Public finance": ("rozpoč", "deficit", "daně", "dluh"),
    "Energy and prices": ("energi", "benz", "nafty", "hypoték", "inflac"),
    "Education": ("škol", "vzděl", "univerzit"),
    "Foreign policy": ("ukrajin", "evrop", "nato", "válk", "rus"),
    "Public roles": ("poslan", "premiér", "předsed", "ods"),
}
PLACES = {
    "Praha": ("Praha", "Praze", "Prahy", "Prahu"),
    "Brno": ("Brno", "Brně", "Brna"),
    "Ostrava": ("Ostrava", "Ostravě", "Ostravy"),
    "Plzeň": ("Plzeň", "Plzni", "Plzně"),
    "Olomouc": ("Olomouc", "Olomouci", "Olomouce"),
    "Liberec": ("Liberec", "Liberci", "Liberce"),
}


def folded(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def sentence_spans(text: str) -> list[tuple[int, int]]:
    boundaries = [0]
    abbreviations = {"tzv", "tj", "např", "č", "dr", "ing", "prof", "doc", "mgr", "čr"}
    for match in re.finditer(r"(?<=[.!?])\s+|\n+", text):
        preceding = text[boundaries[-1] : match.start()]
        last_word = re.search(r"(\w+)\.$", preceding)
        if last_word and last_word[1].lower() in abbreviations:
            continue
        boundaries.append(match.end())
    boundaries.append(len(text))
    spans = []
    for start, end in pairwise(boundaries):
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        quote = text[start:end]
        if 35 <= len(quote) <= 600 and not quote.endswith("?"):
            spans.append((start, end))
    return spans


def category(quote: str, *, profile: bool = False) -> str:
    quote = re.sub(r"https?://\S+", "", quote)
    if profile or re.search(
        r"politolog|profesor|rektorem|narodil|poslancem|předsedou ODS|bývalý premiér",
        quote,
        re.IGNORECASE,
    ):
        return "roles"
    if re.search(r"bitcoin|kauz|obvin", quote, re.IGNORECASE):
        return "controversy"
    if re.search(r"\d|procent|\b(?:milion|miliard|třiceti|čtyřmi)\w*", quote, re.IGNORECASE):
        return "numeric"
    return "position"


class Extract(Step):
    id = "extract"
    label = "Extract claims"
    group = "downstream"

    async def run(self, ctx: RunContext) -> StepResult:
        asr = ctx.store.read_json(ctx.run_id, "asr-transcripts.json") or []
        existing = {(t.item_id, t.provider) for t in ctx.transcripts}
        ctx.transcripts.extend(
            Transcript.model_validate(t) for t in asr if (t["item_id"], t["provider"]) not in existing
        )
        candidates, places, topics = [], [], []
        for item in ctx.items:
            materials = [("text", item.text)] + [(t.provider, t.text) for t in ctx.transcripts if t.item_id == item.id]
            # Prefer Scribe over the platform ASR for the same spoken material; retain both for audit.
            if any(kind == "scribe" for kind, _ in materials):
                materials = [(kind, text) for kind, text in materials if kind != "tiktok_asr"]
            for kind, text in materials:
                for start, end in sentence_spans(text)[:12]:
                    quote = text[start:end]
                    key = hashlib.sha256(f"{item.id}:{kind}:{start}:{end}".encode()).hexdigest()[:12]
                    evidence = Evidence(
                        item_id=item.id,
                        url=item.url,
                        platform=item.platform,
                        published_at=item.published_at,
                        quote=quote,
                        quote_start=start,
                        quote_end=end,
                        source_kind=kind,
                        collected_at=item.collected_at,
                    )
                    labels = [name for name, stems in TOPICS.items() if any(stem in quote.lower() for stem in stems)]
                    candidates.append(
                        {
                            "id": f"F-{key}",
                            "kind": "fact",
                            "text": "Source statement: “" + quote + "”",
                            "evidence": [evidence.model_dump()],
                            "confidence": "medium",
                            "category": category(quote, profile=item.kind == "profile"),
                            "topics": labels,
                            "item_ids": [item.id],
                        }
                    )
            item.places = []
            for canonical, variants in PLACES.items():
                match = re.search(r"\b(?:" + "|".join(variants) + r")\b", item.text)
                if match:
                    item.places.append(canonical)
                    places.append(
                        {
                            "name": canonical,
                            "item_id": item.id,
                            "url": item.url,
                            "quote": match[0],
                            "quote_start": match.start(),
                            "quote_end": match.end(),
                        }
                    )
        verified, dropped = verify_items(ctx, candidates)
        metadata = {i["id"]: i for i in candidates}
        ctx.claims = [
            {
                **i.model_dump(),
                "category": metadata[i.id]["category"],
                "topics": metadata[i.id]["topics"],
                "item_ids": metadata[i.id]["item_ids"],
            }
            for i in verified
        ]
        for label in TOPICS:
            ids = {i["item_ids"][0] for i in ctx.claims if label in i["topics"]}
            if ids:
                topics.append({"name": label, "posts": len(ids), "item_ids": sorted(ids)})
        ctx.save_json("claims.json", ctx.claims)
        ctx.save_json(
            "extraction-verification.json",
            {
                "kept": len(verified),
                "dropped": len(dropped),
                "rejected": dropped,
                "generator": "extractive",
                "scope": "quote_grounding",
            },
        )
        ctx.save_json("places.json", places)
        ctx.save_json("topics.json", topics)
        ctx.save_json("items.json", ctx.items)
        await ctx.data(
            self.id,
            kept=len(verified),
            dropped=len(dropped),
            claims=ctx.claims,
            places=places,
            topics=topics,
            generator="extractive",
            summary=f"{len(verified)} exact source statements; {len(dropped)} rejected",
        )
        return StepResult(
            "done" if verified else "skipped",
            count=len(verified),
            note=f"{len(verified)} exact source statements; {len(dropped)} rejected; extractive mode",
        )
