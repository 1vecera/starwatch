"""The research run: an ordered plan of stages, each a list of steps run concurrently.

Builders implement a step in its own module (`steps/*.py`, `collectors/*.py`); this file only
orders them and turns their outcome into honest status events.
"""

from __future__ import annotations

import asyncio
import logging

from .collectors import COLLECTORS
from .config import MissingCredential
from .events import now_iso
from .models import Coverage
from .steps.base import RunContext, Step, StepResult
from .steps.extract import Extract
from .steps.identity import ResolveIdentity
from .steps.render import Render
from .steps.transcribe import Transcribe
from .steps.write import PlanAndWrite

log = logging.getLogger("starwatch.pipeline")

PLAN: list[list[Step]] = [
    [ResolveIdentity()],
    COLLECTORS,  # one lane per Actor, all at once
    [Transcribe()],
    [Extract()],
    [PlanAndWrite()],
    [Render()],
]


def plan_descriptors() -> list[dict]:
    return [{**step.describe(), "stage": index} for index, stage in enumerate(PLAN) for step in stage]


def manifest(ctx: RunContext, steps: dict[str, dict], status: str, finished_at: str = "") -> dict:
    return {
        "run_id": ctx.run_id,
        "subject": ctx.subject,
        "anchor": ctx.anchor,
        "goal": ctx.goal.model_dump(),
        "mode": ctx.mode,
        "status": status,
        "started_at": ctx.started_at,
        "finished_at": finished_at,
        "step_pause_s": ctx.settings.step_pause_s,
        "steps": list(steps.values()),
        "coverage": [c.model_dump() for c in ctx.coverage.values()],
        "costs": ctx.costs.model_dump(),
        "credentials": ctx.settings.credential_presence(),
    }


async def execute(ctx: RunContext, goal_basis: str) -> None:
    steps = {
        d["id"]: {**d, "status": "queued", "count": None, "note": ""} for d in plan_descriptors()
    }
    ctx.save_json("manifest.json", manifest(ctx, steps, "running"))
    await ctx.channel.emit(
        "run.started",
        data={
            "subject": ctx.subject,
            "anchor": ctx.anchor,
            "goal": ctx.goal.model_dump(),
            "goal_basis": goal_basis,
            "mode": ctx.mode,
            "started_at": ctx.started_at,
            "step_pause_s": ctx.settings.step_pause_s,
            "credentials": ctx.settings.credential_presence(),
            "plan": list(steps.values()),
        },
    )

    async def run_step(step: Step) -> None:
        await ctx.channel.emit("step.status", step=step.id, status="running")
        steps[step.id]["status"] = "running"
        try:
            result = await step.run(ctx)
        except NotImplementedError:
            result = StepResult("not_implemented")
        except MissingCredential as missing:
            result = StepResult("skipped", note=f"{missing.name} missing")
        except Exception as error:  # a failed step never stops the run
            log.exception("step %s failed", step.id)
            result = StepResult("failed", note=f"{type(error).__name__}: {error}"[:300])
        if ctx.settings.step_pause_s:
            await asyncio.sleep(ctx.settings.step_pause_s)
        if step.platform and step.platform not in ctx.coverage:
            ctx.coverage[step.platform] = coverage_from(step, result, ctx)
        steps[step.id].update(status=result.status, count=result.count, note=result.note)
        await ctx.channel.emit(
            "step.status", step=step.id, status=result.status, count=result.count, note=result.note
        )

    run_status = "finished"
    try:
        for stage in PLAN:
            await asyncio.gather(*(run_step(step) for step in stage))
    except Exception:
        log.exception("run %s failed", ctx.run_id)
        run_status = "failed"
    finally:
        finished_at = now_iso()
        if ctx.items:
            ctx.save_json("items.json", ctx.items)
        ctx.save_json("manifest.json", manifest(ctx, steps, run_status, finished_at))
        ctx.store.finish(ctx.run_id, run_status)
        await ctx.channel.emit(
            "run.finished",
            status=run_status,
            data={
                "finished_at": finished_at,
                "coverage": [c.model_dump() for c in ctx.coverage.values()],
                "costs": ctx.costs.model_dump(),
            },
        )


def coverage_from(step: Step, result: StepResult, ctx: RunContext) -> Coverage:
    """A platform is never a silent zero: every outcome becomes a labelled coverage row."""
    assert step.platform is not None
    count = sum(1 for item in ctx.items if item.platform == step.platform)
    match result.status:
        case "done":
            status = "collected" if count else "not_found"
        case "failed":
            status = "unavailable"
        case _:
            status = "skipped"
    note = result.note or ("collector not built yet" if result.status == "not_implemented" else "")
    return Coverage(platform=step.platform, status=status, items=count, note=note)

