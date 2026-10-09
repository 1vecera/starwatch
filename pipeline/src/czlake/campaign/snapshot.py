"""Read lists, cities, candidates and topics from the exported ``real.js`` snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .common import read_js


@dataclass(frozen=True)
class Candidate:
    id: str
    name: str
    position: int


@dataclass(frozen=True)
class ElectionList:
    id: str
    city_id: str
    city: str
    name: str
    short: str
    relevant: bool
    candidates: tuple[Candidate, ...]  # sorted by ballot position

    def leaders(self, count: int) -> tuple[Candidate, ...]:
        return self.candidates[:count]


@dataclass(frozen=True)
class Snapshot:
    cities: dict[str, str]
    lists: tuple[ElectionList, ...]
    topics: tuple[str, ...]  # topic ids, e.g. "production-labels-v1:housing"

    def select(self, which: str = "relevant", ids: list[str] | None = None) -> list[ElectionList]:
        """``relevant`` (default), ``rest`` (not relevant), ``all``, or explicit list ids."""
        if ids:
            wanted = set(ids)
            chosen = [item for item in self.lists if item.id in wanted]
            missing = wanted - {item.id for item in chosen}
            if missing:
                raise KeyError(f"unknown list ids: {sorted(missing)}")
            return chosen
        if which == "all":
            return list(self.lists)
        if which == "rest":
            return [item for item in self.lists if not item.relevant]
        if which == "relevant":
            return [item for item in self.lists if item.relevant]
        raise ValueError(f"unknown selection {which!r}")


def load(path: Path) -> Snapshot:
    raw = read_js(path)
    cities = {city["id"]: city["name"] for city in raw["cities"]}
    by_list: dict[str, list[Candidate]] = {}
    for cand in raw["cands"]:
        by_list.setdefault(cand["list_id"], []).append(Candidate(cand["id"], cand["name"], int(cand["position"])))
    lists = tuple(
        ElectionList(
            id=item["id"], city_id=item["city_id"], city=cities[item["city_id"]], name=item["name"],
            short=item.get("short") or item["name"], relevant=bool(item.get("relevant")),
            candidates=tuple(sorted(by_list.get(item["id"], []), key=lambda c: (c.position, c.id))),
        )
        for item in sorted(raw["lists"], key=lambda item: (not item.get("relevant"), item["city_id"], item["id"]))
    )
    topics = tuple(sorted(topic["id"] for topic in raw.get("topics", [])))
    return Snapshot(cities, lists, topics)
