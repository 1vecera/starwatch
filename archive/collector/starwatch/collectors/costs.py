"""Apify cost: the job's real spend, read back from Apify once collection has ended.

Apify updates a run's `usageTotalUsd` and charged events a few seconds after the run stops, so the
figure a lane sees at its end can lag. This step waits for every lane and identity search, re-reads
each run the job started, and makes the run's Apify cost the sum of what Apify reports.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ..steps.base import RunContext, Step, StepResult
from .apify import API, is_settled, run_cost
from .identity import identity_board

LANES_WAIT_S = 420.0
SETTLE_ROUNDS = 6


class SettleCosts(Step):
    id = "collect.costs"
    label = "Apify cost"
    group = "downstream"  # shown with the analysis rows, under the lanes

    async def run(self, ctx: RunContext) -> StepResult:
        token = ctx.credential("APIFY_TOKEN")
        board = identity_board(ctx)
        if board is None:
            return StepResult("skipped", note="identity did not run, so no Actor ran")
        waits = [event.wait() for event in board.lanes.values()] + list(board.search_tasks)
        if waits:
            await asyncio.wait([asyncio.ensure_future(w) for w in waits], timeout=LANES_WAIT_S)
        runs: list[dict[str, Any]] = ctx.__dict__.get("apify_runs", [])
        if not runs:
            return StepResult("done", count=0, note="no Apify runs")
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(base_url=API, timeout=20, headers=headers) as client:
            for round_ in range(SETTLE_ROUNDS):
                pending = 0
                for record in runs:
                    if not record.get("run_id") or record.get("settled"):
                        continue
                    try:
                        response = await client.get(f"/actor-runs/{record['run_id']}")
                        response.raise_for_status()
                        run = response.json()["data"]
                    except (httpx.HTTPError, ValueError, KeyError):
                        pending += 1
                        continue
                    record["usage_usd"] = round(run_cost(run), 5)
                    record["usage_total_usd"] = float(run.get("usageTotalUsd") or 0.0)
                    record["status"] = record.get("status") or run.get("status")
                    if is_settled(run, int(record.get("items") or 0)):
                        record["settled"] = True
                    else:
                        pending += 1
                if not pending or round_ == SETTLE_ROUNDS - 1:
                    break
                await asyncio.sleep(2.5)
        total = round(sum(float(r.get("usage_usd") or 0.0) for r in runs), 4)
        ctx.costs.apify_usd = total
        ctx.save_json("apify_runs.json", runs)
        unsettled = sum(1 for r in runs if not r.get("settled"))
        note = f"${total:.3f} across {len(runs)} Actor runs, as Apify reports them"
        if unsettled:
            note += f" ({unsettled} still updating)"
        await ctx.data(self.id, summary=note, runs=len(runs), apify_usd=total, costs=ctx.costs.model_dump())
        return StepResult("done", count=len(runs), note=note)
