"""Website collector: the anchor website, crawled to depth 1 for pages and official social links."""

from __future__ import annotations

from ..steps.base import RunContext, StepResult
from .base import Collector


class WebsiteCollector(Collector):
    id = "collect.website"
    label = "Website"
    platform = "website"

    async def run(self, ctx: RunContext) -> StepResult:
        # Build here: target from ctx.accounts_for("website"), then run_actor(self.spec, {...},
        # token=ctx.credential("APIFY_TOKEN"), on_items=...) and ctx.item_arrived per item.
        raise NotImplementedError
