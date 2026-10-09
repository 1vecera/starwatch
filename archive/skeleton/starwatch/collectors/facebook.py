"""Facebook collector: up to 30 posts from the accepted page, comments off."""

from __future__ import annotations

from ..steps.base import RunContext, StepResult
from .base import Collector


class FacebookCollector(Collector):
    id = "collect.facebook"
    label = "Facebook"
    platform = "facebook"

    async def run(self, ctx: RunContext) -> StepResult:
        # Build here: target from ctx.accounts_for("facebook"), then run_actor(self.spec, {...},
        # token=ctx.credential("APIFY_TOKEN"), on_items=...) and ctx.item_arrived per item.
        raise NotImplementedError
