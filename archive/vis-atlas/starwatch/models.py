"""Typed records shared by every step and screen.

`Brief` and its parts follow the brief JSON schema in the build spec. `CollectedItem` is the
allowlist every collector projects raw Actor output into before anything is stored.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Platform = Literal["website", "facebook", "instagram", "tiktok", "youtube", "x"]
PLATFORMS: tuple[Platform, ...] = ("website", "facebook", "instagram", "tiktok", "youtube", "x")

GoalPreset = Literal["G1", "G2", "G3"]
RunMode = Literal["live", "cached"]
RunStatus = Literal["running", "finished", "failed", "interrupted"]
StepStatus = Literal["queued", "running", "done", "failed", "skipped", "not_implemented"]
CoverageStatus = Literal["collected", "unavailable", "not_found", "skipped"]
ReportKind = Literal["fact", "inference", "open_question", "missing_source"]
Confidence = Literal["high", "medium", "low"]


# --- Run input -------------------------------------------------------------------------------


class RunRequest(BaseModel):
    """What S1 sends. `goal_preset` empty means: map `goal_text` to the nearest preset."""

    subject: str = Field(min_length=2, max_length=200)
    anchor: str = Field(min_length=2, max_length=300)
    goal_preset: GoalPreset | None = None
    goal_text: str = Field(default="", max_length=1000)


# --- Brief schema (build spec) -----------------------------------------------------------------


class Account(BaseModel):
    platform: Platform
    url: str
    handle: str = ""
    match_basis: list[str] = []
    status: Literal["accepted", "unconfirmed"]


class Rejected(BaseModel):
    url: str
    platform: Platform | None = None
    reason: str


class Subject(BaseModel):
    name: str
    anchor: str
    accounts: list[Account] = []
    rejected: list[Rejected] = []


class Goal(BaseModel):
    preset: GoalPreset
    text: str = ""


class Evidence(BaseModel):
    url: str
    platform: Platform
    published_at: str = ""
    quote: str = ""
    timecode: float | None = None  # seconds into the video for transcript quotes


class ReportItem(BaseModel):
    id: str
    kind: ReportKind
    text: str
    evidence: list[Evidence] = []
    based_on: list[str] = []  # fact IDs an inference rests on
    confidence: Confidence  # about the claim, never about the person

    @model_validator(mode="after")
    def _cited(self) -> ReportItem:
        if self.kind == "fact" and not self.evidence:
            raise ValueError(f"fact {self.id} has no evidence")
        if self.kind == "inference" and not self.based_on:
            raise ValueError(f"inference {self.id} references no fact IDs")
        return self


class Section(BaseModel):
    title: str
    items: list[ReportItem] = []


class Coverage(BaseModel):
    platform: Platform
    status: CoverageStatus
    items: int = 0
    note: str = ""


class Costs(BaseModel):
    apify_usd: float = 0.0
    scribe_minutes: float = 0.0
    llm_tokens: int = 0


class RunInfo(BaseModel):
    started_at: str
    finished_at: str = ""
    mode: RunMode
    costs: Costs = Costs()


class Brief(BaseModel):
    subject: Subject
    goal: Goal
    sections: list[Section] = []
    coverage: list[Coverage] = []
    run: RunInfo


# --- Collected material ------------------------------------------------------------------------


class Media(BaseModel):
    kind: Literal["image", "video"]
    path: str  # relative to the run folder, e.g. "media/instagram-123.jpg"
    source_url: str = ""
    width: int | None = None
    height: int | None = None


class CollectedItem(BaseModel):
    """One post, video or page after allowlist projection. No comments, no follower lists."""

    id: str  # "<platform>:<native id>"
    platform: Platform
    kind: Literal["post", "video", "page", "profile"] = "post"
    url: str
    account_url: str = ""
    published_at: str = ""
    text: str = ""
    media: list[Media] = []
    metrics: dict[str, int] = {}  # collected counts, valid at `collected_at`
    collected_at: str
    places: list[str] = []  # Czech place names in the nominative, filled by extraction


class Transcript(BaseModel):
    item_id: str
    url: str
    language: str = ""
    duration_s: float = 0.0
    words: list[dict] = []  # Scribe word timings: {"text", "start", "end"}
    text: str = ""
