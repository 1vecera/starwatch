"""Continue a retained run locally: uv run python -m starwatch.research --source ID --goals G1 G2 G3."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .config import load_settings
from .events import RunChannel, now_iso
from .models import Goal
from .pipeline import execute
from .retained import hydrate
from .steps.base import RunContext
from .store import RunStore


async def continue_run(source: str, goals: list[str], data_dir: Path, goal_text: str) -> list[dict]:
    settings = load_settings(data_dir=data_dir)
    store = RunStore(data_dir)
    original = store.read_json(source, "manifest.json")
    if original is None:
        raise ValueError("Source run is not in this data directory")
    result = []
    for preset in goals:
        run_id = store.create(
            subject=original["subject"],
            anchor=original["anchor"],
            goal_preset=preset,
            goal_text=goal_text,
            mode="cached",
        )
        ctx = RunContext(
            run_id=run_id,
            subject=original["subject"],
            anchor=original["anchor"],
            goal=Goal(preset=preset, text=goal_text),
            mode="cached",
            started_at=now_iso(),
            settings=settings,
            store=store,
            channel=RunChannel(run_id, store.run_dir(run_id) / "events.jsonl"),
        )
        hydrate(ctx, source)
        await execute(ctx, "chosen; retained collection")
        manifest = store.read_json(run_id, "manifest.json")
        result.append(
            {
                "run_id": run_id,
                "goal": preset,
                "status": manifest["status"],
                "steps": {s["id"]: s["status"] for s in manifest["steps"]},
                "verification": ctx.brief.verification if ctx.brief else None,
                "costs": ctx.costs.model_dump(),
                "overlap": store.read_json(run_id, "evidence-overlap.json"),
            }
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--goals", nargs="+", choices=("G1", "G2", "G3"), default=["G1", "G2", "G3"])
    parser.add_argument("--goal-text", default="")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(continue_run(args.source, args.goals, args.data_dir.resolve(), args.goal_text)),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
