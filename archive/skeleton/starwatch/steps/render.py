"""Render: prepare the views S2 to S4 read (brief, network, alert, coverage) from the same records."""

from __future__ import annotations

from .base import RunContext, Step, StepResult


class Render(Step):
    id = "render"
    label = "Render"
    group = "downstream"

    async def run(self, ctx: RunContext) -> StepResult:
        raise NotImplementedError
