"""X collector: up to 30 posts from the accepted account."""

from __future__ import annotations

from ..steps.base import RunContext, StepResult
from .base import Collector


class XCollector(Collector):
    id = "collect.x"
    label = "X"
    platform = "x"

    async def run(self, ctx: RunContext) -> StepResult:
        # Build here: target from ctx.accounts_for("x"), then run_actor(self.spec, {...},
        # token=ctx.credential("APIFY_TOKEN"), on_items=...) and ctx.item_arrived per item.
        raise NotImplementedError
