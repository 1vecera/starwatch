"""Plan and write: goal preset -> section plan -> Brief citing evidence, then the verifier pass.

Sets ctx.brief (models.Brief) and saves brief.json. Facts without evidence and inferences without
fact IDs cannot be constructed (ReportItem validates them); the verifier drops and logs them."""

from __future__ import annotations

from .base import RunContext, Step, StepResult


class PlanAndWrite(Step):
    id = "write"
    label = "Plan and write"
    group = "downstream"

    async def run(self, ctx: RunContext) -> StepResult:
        raise NotImplementedError
