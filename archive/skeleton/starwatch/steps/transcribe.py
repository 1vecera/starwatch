"""Transcribe: ElevenLabs Scribe v2 on at most 5 subject videos (MAX_TRANSCRIBED_VIDEOS).

Fills ctx.transcripts with word timings, saves transcripts.json, adds Scribe minutes to ctx.costs and
reports progress with ctx.progress(self.id, videos_done)."""

from __future__ import annotations

from .base import RunContext, Step, StepResult


class Transcribe(Step):
    id = "transcribe"
    label = "Transcribe"
    group = "downstream"

    async def run(self, ctx: RunContext) -> StepResult:
        raise NotImplementedError
