"""Extract: candidate claims with exact quote spans from the minimised items and transcripts.

Code, not the model, rejects claims whose quote is not found verbatim in the retained text. Send the
kept and dropped counts with ctx.data(self.id, kept=..., dropped=...) so S1 shows the drop count."""

from __future__ import annotations

from .base import RunContext, Step, StepResult


class Extract(Step):
    id = "extract"
    label = "Extract claims"
    group = "downstream"

    async def run(self, ctx: RunContext) -> StepResult:
        raise NotImplementedError
