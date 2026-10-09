"""Bounded Scribe v2 transcription with durable reservations and content-addressed reuse."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import math
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

from ..collectors.actors import MAX_TRANSCRIBED_VIDEOS, MAX_VIDEO_SECONDS
from ..config import MissingCredential
from ..events import now_iso
from ..models import Transcript
from .base import RunContext, Step, StepResult

SCRIBE_URL = "https://api.elevenlabs.io/v1/speech-to-text"
MAX_VIDEO_BYTES = 40 * 1024 * 1024


@contextmanager
def locked_json(path: Path) -> Iterator[dict]:
    """Lock a separate inode so atomic JSON replacement cannot invalidate the lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = json.loads(path.read_text()) if path.exists() else {}
        yield record
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


async def video_duration(path: Path) -> float:
    process = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=15)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise ValueError("video duration probe timed out") from None
    if process.returncode:
        raise ValueError("video duration unavailable")
    duration = float(json.loads(stdout)["format"]["duration"])
    if not math.isfinite(duration) or not 0.1 <= duration <= MAX_VIDEO_SECONDS:
        raise ValueError("video exceeds the bounded spoken-clip duration")
    return duration


def transcript_from_scribe(raw: dict, *, item_id: str, url: str, duration: float, digest: str) -> Transcript:
    """Retain only transcript text and usable word timings, with exact character offsets."""
    text = raw.get("text", "")
    if not isinstance(text, str) or len(text.split()) < 3:
        raise ValueError("Scribe returned no usable speech")
    words, cursor = [], 0
    for word in raw.get("words", []):
        token = word.get("text", "")
        if not isinstance(token, str) or not token.strip() or word.get("type", "word") != "word":
            continue
        start, end = float(word["start"]), float(word["end"])
        char_start = text.find(token, cursor)
        if char_start < 0 or not all(math.isfinite(v) for v in (start, end)):
            continue
        if not 0 <= start <= end <= duration + 1 or (words and start < words[-1]["start"]):
            continue
        cursor = char_start + len(token)
        words.append(
            {
                "text": token,
                "start": start,
                "end": end,
                "char_start": char_start,
                "char_end": cursor,
            }
        )
    if not words:
        raise ValueError("Scribe returned no usable word timestamps")
    return Transcript(
        item_id=item_id,
        url=url,
        language=str(raw.get("language_code", "")),
        duration_s=duration,
        words=words,
        text=text,
        provider="scribe",
        source_hash=digest,
        collected_at=now_iso(),
    )


class Transcribe(Step):
    id = "transcribe"
    label = "Transcribe"
    group = "downstream"

    async def run(self, ctx: RunContext) -> StepResult:
        cache_dir = ctx.settings.data_dir / "transcript-cache"
        ledger_path = ctx.settings.data_dir / "scribe-ledger.json"
        origin = ctx.source_run_id or ctx.run_id
        outcomes, kept = [], []
        candidates = []
        for item in sorted(ctx.items, key=lambda i: i.published_at, reverse=True):
            media = next((m for m in item.media if m.kind == "video"), None)
            if media:
                candidates.append((item, media))
        cache_dir.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=180) as client:
            for item, media in candidates[:MAX_TRANSCRIBED_VIDEOS]:
                outcome = {"item_id": item.id, "url": item.url, "provider": "scribe"}
                path = (ctx.run_dir / media.path).resolve()
                try:
                    if not path.is_relative_to(ctx.run_dir.resolve()) or not path.is_file():
                        raise ValueError("local video unavailable")
                    if path.stat().st_size > MAX_VIDEO_BYTES:
                        raise ValueError("video exceeds the local size cap")
                    digest = hashlib.sha256(path.read_bytes() + b"scribe_v2:cs:word:v1").hexdigest()
                    cache = cache_dir / f"{digest}.json"
                    if cache.exists():
                        transcript = Transcript.model_validate_json(cache.read_text())
                        transcript = transcript.model_copy(update={"item_id": item.id, "url": item.url, "cached": True})
                        ctx.costs.scribe_reused_minutes += transcript.duration_s / 60
                        outcome["status"] = "cached"
                    else:
                        token = ctx.credential("ELEVENLABS_API_KEY")
                        duration = await video_duration(path)
                        with locked_json(ledger_path) as ledger:
                            attempts = ledger.setdefault(origin, {})
                            if digest in attempts:
                                raise ValueError(
                                    "prior Scribe submission has no reusable result; automatic retry blocked"
                                )
                            if len(attempts) >= MAX_TRANSCRIBED_VIDEOS:
                                raise ValueError("five-video Scribe authorization exhausted for the source run")
                            # Persist before POST. A timeout still consumes a slot and possible minutes.
                            attempts[digest] = {
                                "item_id": item.id,
                                "status": "reserved",
                                "minutes": duration / 60,
                                "submitted_at": now_iso(),
                                "run_id": ctx.run_id,
                            }
                        ctx.costs.scribe_minutes += duration / 60
                        await ctx.data(self.id, costs=ctx.costs.model_dump(), reserved=item.id)
                        with path.open("rb") as video:
                            response = await client.post(
                                SCRIBE_URL,
                                headers={"xi-api-key": token},
                                data={
                                    "model_id": "scribe_v2",
                                    "language_code": "cs",
                                    "timestamps_granularity": "word",
                                    "diarize": "false",
                                    "tag_audio_events": "false",
                                    "no_verbatim": "false",
                                    "webhook": "false",
                                },
                                files={"file": (path.name, video, "video/mp4")},
                            )
                        if response.status_code >= 400:
                            raise ValueError(f"Scribe HTTP {response.status_code}; provider payload withheld")
                        transcript = transcript_from_scribe(
                            response.json(),
                            item_id=item.id,
                            url=item.url,
                            duration=duration,
                            digest=digest,
                        )
                        cache.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
                        with locked_json(ledger_path) as ledger:
                            ledger[origin][digest]["status"] = "done"
                        outcome["status"] = "transcribed"
                    kept.append(transcript)
                    outcome["duration_s"] = transcript.duration_s
                    await ctx.data(
                        self.id,
                        transcript=transcript.model_dump(),
                        costs=ctx.costs.model_dump(),
                    )
                except (
                    ValueError,
                    OSError,
                    httpx.HTTPError,
                    MissingCredential,
                    KeyError,
                    TypeError,
                ) as error:
                    # No response bodies, credential-bearing URLs or provider messages in events.
                    if isinstance(error, (ValueError, FileNotFoundError)):
                        note = str(error)
                    else:
                        note = f"{type(error).__name__}: transcription unavailable"
                    outcome.update(status="unavailable", note=note)
                outcomes.append(outcome)
                ctx.transcripts = kept
                ctx.save_json("transcripts.json", kept)
                ctx.save_json("transcription-status.json", outcomes)
                await ctx.progress(
                    self.id,
                    len(kept),
                    f"{len(kept)} timestamped transcripts; {len(outcomes) - len(kept)} gaps",
                )
        unsaved = sum(i.kind == "video" and not any(m.kind == "video" for m in i.media) for i in ctx.items)
        asr = ctx.store.read_json(ctx.run_id, "asr-transcripts.json") or []
        covered = {t.item_id for t in kept} | {t["item_id"] for t in asr}
        missing = [i.id for i in ctx.items if i.kind == "video" and i.id not in covered]
        ctx.save_json(
            "transcription-coverage.json",
            {
                "scribe": len(kept),
                "asr": len(asr),
                "covered_videos": len(covered),
                "missing_item_ids": missing,
            },
        )
        note = f"{len(kept)} Scribe transcripts; {unsaved} videos have no retained media; new minutes {ctx.costs.scribe_minutes:.3f}"
        await ctx.data(
            self.id,
            summary=note,
            outcomes=outcomes,
            missing_video_files=unsaved,
            asr_retained=len(asr),
            missing_transcripts=len(missing),
            costs=ctx.costs.model_dump(),
        )
        return StepResult("done" if kept else "skipped", count=len(kept), note=note)
