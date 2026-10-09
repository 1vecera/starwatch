"""Goal presets from the build spec, and free text mapped to the nearest one."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .models import GoalPreset


@dataclass(frozen=True)
class Preset:
    id: GoalPreset
    name: str
    question: str
    sections: tuple[str, ...]
    favours: str


PRESETS: dict[str, Preset] = {
    "G1": Preset(
        "G1",
        "Debate prep",
        "What will they say on topic X, and where is it weak?",
        (
            "Stated positions with quotes",
            "Checkable numeric claims",
            "Possible inconsistencies",
            "Likely questions",
        ),
        "Video transcripts, long posts, interviews on the anchor website",
    ),
    "G2": Preset(
        "G2",
        "Respond to this post",
        "They just posted this. What is the factual context?",
        (
            "The post",
            "What is verifiable",
            "Context from earlier statements",
            "Draft response points",
            "Open questions",
        ),
        "The triggering post, items from the last 30 days, related claims",
    ),
    "G3": Preset(
        "G3",
        "Background check",
        "Who is this, and what is on the public record?",
        (
            "Identity and rejected namesakes",
            "Roles and affiliations",
            "Timeline of public activity",
            "Public controversies",
            "Missing sources",
        ),
        "Anchor website, profile bios, platform coverage, news search",
    ),
}

# Word stems in English and Czech. Czech declines, so stems match the start of a word.
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "G1": ("debat", "debate", "topic", "téma", "tema", "position", "postoj", "názor", "argument",
           "interview", "rozhovor", "duel", "prep", "příprav"),
    "G2": ("respond", "response", "reply", "react", "reakc", "odpov", "post", "příspěv", "tweet",
           "zveřejn", "napsal", "sdílel"),
    "G3": ("background", "who", "kdo", "prověř", "prover", "profil", "history", "minulost",
           "record", "životopis", "kontroverz", "controvers", "career", "kariér"),
}
_URL = re.compile(r"https?://\S+")


def map_goal(preset: str | None, text: str) -> tuple[GoalPreset, str]:
    """Return the preset and a short, human-readable basis for the choice."""
    if preset in PRESETS:
        return preset, "chosen"  # type: ignore[return-value]
    lowered = text.lower()
    words = re.findall(r"\w+", lowered)
    scores = {gid: 0 for gid in PRESETS}
    hits: dict[str, list[str]] = {gid: [] for gid in PRESETS}
    for gid, stems in _KEYWORDS.items():
        for stem in stems:
            if any(word.startswith(stem) for word in words):
                scores[gid] += 1
                hits[gid].append(stem)
    if _URL.search(text):
        scores["G2"] += 1
        hits["G2"].append("a link")
    best = max(scores, key=lambda gid: scores[gid])
    if scores[best] == 0:
        return "G3", "no goal words recognised, so the background check"
    return best, "mapped from “" + "”, “".join(hits[best]) + "”"  # type: ignore[return-value]


def presets_json() -> list[dict]:
    return [asdict(p) for p in PRESETS.values()]
