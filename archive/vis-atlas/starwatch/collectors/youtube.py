"""YouTube collector: up to 10 videos with thumbnails."""

from __future__ import annotations

from ..steps.base import RunContext, StepResult
from .base import Collector


class YoutubeCollector(Collector):
    id = "collect.youtube"
    label = "YouTube"
    platform = "youtube"

    async def run(self, ctx: RunContext) -> StepResult:
        # Build here: target from ctx.accounts_for("youtube"), then run_actor(self.spec, {...},
        # token=ctx.credential("APIFY_TOKEN"), on_items=...) and ctx.item_arrived per item.
        raise NotImplementedError
