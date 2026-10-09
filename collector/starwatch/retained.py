"""Hydrate a cached continuation without scraping or changing the original observation."""

from __future__ import annotations

import json
import os
import shutil

from .models import Account, CollectedItem, Costs, Coverage, Rejected
from .steps.base import RunContext


def hydrate(ctx: RunContext, source_id: str) -> None:
    source = ctx.store.read_json(source_id, "manifest.json")
    items = ctx.store.read_json(source_id, "items.json")
    if source is None or items is None:
        raise ValueError("Source run has no retained collection")
    if source["subject"] != ctx.subject or source["anchor"] != ctx.anchor:
        raise ValueError("Cached source subject and anchor must match the request")
    ctx.source_run_id = source.get("source_run_id") or source_id
    ctx.source_costs = Costs.model_validate(source.get("source_costs") or source["costs"])
    ctx.items = [CollectedItem.model_validate(i) for i in items]
    ctx.coverage = {c["platform"]: Coverage.model_validate(c) for c in source["coverage"]}
    identity = ctx.store.read_json(source_id, "identity.json")
    if identity is None:
        events = ctx.store.run_dir(source_id) / "events.jsonl"
        retained = [json.loads(line) for line in events.read_text().splitlines()]
        identity = next(
            (e["data"] for e in reversed(retained) if e["type"] == "step.data" and e.get("step") == "identity"),
            {},
        )
    ctx.accounts = [Account.model_validate(a) for a in identity.get("accounts", [])]
    ctx.rejected = [Rejected.model_validate(r) for r in identity.get("rejected", [])]
    ctx.save_json("identity.json", identity)
    for name in (
        "asr-transcripts.json",
        "profiles.json",
        "apify_runs.json",
        "transcription-status.json",
    ):
        value = ctx.store.read_json(source_id, name)
        if value is not None:
            ctx.save_json(name, value)
    profiles = ctx.store.read_json(ctx.run_id, "profiles.json") or []
    ctx.profiles = {p["url"]: p for p in profiles}
    for directory in ("media", "asr"):
        source_dir = ctx.store.run_dir(source_id) / directory
        if not source_dir.exists():
            continue
        destination = ctx.run_dir / directory
        destination.mkdir(exist_ok=True)
        for file in source_dir.iterdir():
            if not file.is_file():
                continue
            target = destination / file.name
            if not target.exists():
                try:
                    os.link(file, target)
                except OSError:
                    shutil.copy2(file, target)
