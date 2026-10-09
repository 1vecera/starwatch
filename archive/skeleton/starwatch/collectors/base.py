"""Base class for the per-platform collectors.

A collector finds its accepted account in `ctx.accounts_for(self.platform)`, runs its Actor through
`run_actor` (which applies the caps in `actors.py`), projects each raw item into a `CollectedItem`,
downloads its image or cover with `ctx.download_media`, and calls `ctx.item_arrived` so the item
reaches its lane on S1 straight away. It may set `ctx.coverage[self.platform]` itself, for example
to "unavailable" with the reason; otherwise the runner derives the coverage row from the step result.
"""

from __future__ import annotations

from typing import ClassVar

from ..steps.base import Step
from .actors import ACTORS, ActorSpec


class Collector(Step):
    group: ClassVar[str] = "collect"

    @property
    def spec(self) -> ActorSpec:
        assert self.platform is not None
        return ACTORS[self.platform]

    def describe(self) -> dict:
        return {**super().describe(), "actor": self.spec.actor_id, "max_items": self.spec.max_items}
