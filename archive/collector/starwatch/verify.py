"""Verify saved research without network calls: uv run python -m starwatch.verify RUN_ID."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .collectors.subtitles import parse_vtt
from .config import load_settings
from .events import RunChannel
from .models import Brief, CollectedItem, Transcript
from .steps.base import RunContext
from .steps.evidence import verify_items
from .store import RunStore


def verify_run(data_dir: Path, run_id: str) -> dict:
    store = RunStore(data_dir)
    raw = store.read_json(run_id, "brief.json")
    if raw is None:
        raise ValueError("Run has no saved brief")
    brief = Brief.model_validate(raw)
    items = [CollectedItem.model_validate(i) for i in store.read_json(run_id, "items.json")]
    transcripts = [
        Transcript.model_validate(t)
        for name in ("transcripts.json", "asr-transcripts.json")
        for t in (store.read_json(run_id, name) or [])
    ]
    ctx = RunContext(
        run_id=run_id,
        subject=brief.subject.name,
        anchor=brief.subject.anchor,
        goal=brief.goal,
        mode=brief.run.mode,
        started_at=brief.run.started_at,
        settings=load_settings(data_dir=data_dir, _credentials={}),
        store=store,
        channel=RunChannel.from_log(run_id, store.run_dir(run_id) / "events.jsonl"),
        items=items,
        transcripts=transcripts,
    )
    candidates = [i.model_dump() for s in brief.sections for i in s.items]
    verified, errors = verify_items(ctx, candidates)
    for transcript in transcripts:
        item = next(i for i in items if i.id == transcript.item_id)
        if transcript.provider == "scribe":
            video = next((m for m in item.media if m.kind == "video"), None)
            if video is None:
                errors.append({"id": item.id, "reason": "Scribe video not retained"})
                continue
            path = (ctx.run_dir / video.path).resolve()
            if not path.is_relative_to(ctx.run_dir.resolve()) or not path.is_file():
                errors.append({"id": item.id, "reason": "Scribe video path unavailable"})
                continue
            digest = hashlib.sha256(path.read_bytes() + b"scribe_v2:cs:word:v1").hexdigest()
            if digest != transcript.source_hash:
                errors.append({"id": item.id, "reason": "Scribe input video digest mismatch"})
        else:
            track = next(
                (t for t in item.subtitle_tracks if t.get("source_hash") == transcript.source_hash),
                None,
            )
            if track is None:
                errors.append({"id": item.id, "reason": "ASR source track not retained"})
                continue
            path = (ctx.run_dir / track["path"]).resolve()
            if not path.is_relative_to(ctx.run_dir.resolve()) or not path.is_file():
                errors.append({"id": item.id, "reason": "ASR source track path unavailable"})
                continue
            rebuilt = parse_vtt(path.read_text(), item, transcript.language)
            if (
                rebuilt.text != transcript.text
                or rebuilt.words != transcript.words
                or rebuilt.source_hash != transcript.source_hash
            ):
                errors.append(
                    {
                        "id": item.id,
                        "reason": "ASR transcript differs from the retained VTT",
                    }
                )
    graph = store.read_json(run_id, "network.json")
    if graph:
        node_ids = [n["id"] for n in graph["nodes"]]
        if len(node_ids) != len(set(node_ids)):
            errors.append({"reason": "Duplicate graph node IDs"})
        if any(e["source"] not in node_ids or e["target"] not in node_ids for e in graph["edges"]):
            errors.append({"reason": "Graph has an orphan edge"})
    return {
        "run_id": run_id,
        "valid": not errors,
        "verified_items": len(verified),
        "facts": sum(i.kind == "fact" for i in verified),
        "scribe_transcripts": sum(t.provider == "scribe" for t in transcripts),
        "asr_transcripts": sum(t.provider == "tiktok_asr" for t in transcripts),
        "errors": errors,
        "scope": "retained quotes, timecodes, source digests, inference references and graph links; no network or independent truth check",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    result = verify_run(args.data_dir.resolve(), args.run_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
