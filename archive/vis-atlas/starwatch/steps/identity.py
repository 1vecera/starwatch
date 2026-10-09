"""Resolve identity: find the subject's official accounts from the anchor and reject namesakes.

Fills ctx.accounts (accepted or unconfirmed, each with its match basis) and ctx.rejected (with a
reason), then sends them with ctx.data(self.id, accounts=[...], rejected=[...]) for the S1 identity
panel. An account that cannot be confirmed stays "unconfirmed"; nothing is guessed."""

from __future__ import annotations

from .base import RunContext, Step, StepResult


class ResolveIdentity(Step):
    id = "identity"
    label = "Resolve identity"
    group = "identity"

    async def run(self, ctx: RunContext) -> StepResult:
        raise NotImplementedError
