"""Retain public TikTok ASR tracks before their signed CDN links expire."""

from __future__ import annotations

import hashlib
import html
import math
import re
from urllib.parse import urlsplit

import httpx

from ..events import now_iso
from ..models import CollectedItem, Transcript
from ..steps.base import RunContext

CUE = re.compile(
    r"(?P<start>(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3})\s*-->\s*(?P<end>(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3})[^\n]*\n(?P<text>.*?)(?=\n\s*\n|\Z)",
    re.DOTALL,
)
MAX_TRACK_BYTES = 512 * 1024


def project_tracks(raw: dict) -> list[dict]:
    tracks = (raw.get("videoMeta") or {}).get("subtitleLinks") or raw.get("subtitleLinks") or []
    return [
        {
            "language": str(t.get("language", "")),
            "source": "ASR",
            "url": t.get("downloadLink") or t.get("tiktokLink"),
        }
        for t in tracks
        if isinstance(t, dict)
        and t.get("source") == "ASR"
        and isinstance(t.get("downloadLink") or t.get("tiktokLink"), str)
    ][:2]


def seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    return sum(float(part) * 60**i for i, part in enumerate(reversed(parts)))


def parse_vtt(content: str, item: CollectedItem, language: str) -> Transcript:
    chunks, words, offset = [], [], 0
    for cue in CUE.finditer(content):
        text = html.unescape(re.sub(r"<[^>]*>", "", cue["text"])).strip()
        start, end = seconds(cue["start"]), seconds(cue["end"])
        if not text or not all(math.isfinite(v) for v in (start, end)) or not 0 <= start < end:
            continue
        if chunks:
            offset += 1
        # ASR tracks have cue timings, not independently observed word timings.
        words.append(
            {
                "text": text,
                "start": start,
                "end": end,
                "char_start": offset,
                "char_end": offset + len(text),
                "granularity": "cue",
            }
        )
        chunks.append(text)
        offset += len(text)
    if not words:
        raise ValueError("ASR track has no usable timed cues")
    return Transcript(
        item_id=item.id,
        url=item.url,
        provider="tiktok_asr",
        language=language,
        words=words,
        text=" ".join(chunks),
        duration_s=words[-1]["end"],
        source_hash=hashlib.sha256(content.encode()).hexdigest(),
        collected_at=now_iso(),
    )


async def capture_asr(ctx: RunContext, item: CollectedItem, client: httpx.AsyncClient) -> None:
    tracks = sorted(item.subtitle_tracks, key=lambda t: t["language"] not in ("ces-CZ", "cs", "ces"))
    for track in tracks[:1]:
        host = urlsplit(track["url"]).hostname or ""
        if urlsplit(track["url"]).scheme != "https" or not any(
            host == domain or host.endswith("." + domain)
            for domain in ("tiktokcdn.com", "tiktokcdn-us.com", "tiktok.com")
        ):
            track.update(status="unavailable", note="ASR URL is outside the public TikTok CDN")
            continue
        try:
            async with client.stream("GET", track["url"], follow_redirects=False) as response:
                response.raise_for_status()
                content = bytearray()
                async for part in response.aiter_bytes():
                    content.extend(part)
                    if len(content) > MAX_TRACK_BYTES:
                        raise ValueError("ASR track exceeds the retention cap")
            text = content.decode("utf-8-sig")
            transcript = parse_vtt(text, item, track["language"])
            filename = hashlib.sha256(item.id.encode()).hexdigest()[:16]
            relative = f"asr/{filename}.vtt"
            destination = ctx.run_dir / relative
            destination.parent.mkdir(exist_ok=True)
            destination.write_text(text, encoding="utf-8")
            track.update(
                status="retained",
                path=relative,
                source_hash=transcript.source_hash,
                collected_at=transcript.collected_at,
            )
            transcripts = ctx.__dict__.setdefault("asr_transcripts", [])
            transcripts.append(transcript)
            ctx.save_json("asr-transcripts.json", transcripts)
        except (httpx.HTTPError, ValueError, UnicodeError):
            track.update(status="unavailable", note="ASR track could not be retained")
