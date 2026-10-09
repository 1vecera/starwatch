"""TikTok collector: up to 20 videos with covers, at most 3 video files for transcription."""

from __future__ import annotations

from ..steps.base import RunContext, StepResult
from .base import Collector


class TiktokCollector(Collector):
    id = "collect.tiktok"
    label = "TikTok"
    platform = "tiktok"

    async def run(self, ctx: RunContext) -> StepResult:
        # Build here: target from ctx.accounts_for("tiktok"), then run_actor(self.spec, {...},
        # token=ctx.credential("APIFY_TOKEN"), on_items=...) and ctx.item_arrived per item.
        raise NotImplementedError
