"""Non-additive research qualification and bounded preparation-only scheduling."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from decimal import Decimal

CHANNELS = (
    "office",
    "party_contender",
    "local_votes",
    "prior_leader",
    "public_reach",
    "public_activity",
    "list_leader",
)

RULE_VERSION = "relevance-v2"


@dataclass(frozen=True)
class Candidate:
    key: str
    city_code: str
    city_rank: int
    list_no: str
    position: int
    eligible: bool
    party_strength: float | None
    mandate_evidence: bool
    local_vote_rank: int | None
    local_vote_lift: float | None
    prior_leader: bool | None
    followers: int | None
    population: int
    activity_verified: bool | None
    historical_identity_clear: bool
    current_office_verified: bool = False
    local_role_verified: bool = False
    eligibility_kind: str = "current_candidacy"


@dataclass(frozen=True)
class Decision:
    candidate: Candidate
    components: dict[str, float | None]
    reasons: tuple[str, ...]
    winner: str | None
    score: float
    qualified: bool
    protected: bool


def qualify(candidate: Candidate) -> Decision:
    """Keep every independent spike; unknown evidence contributes no observed score."""
    c = candidate
    if c.city_rank not in range(1, 11) or c.population <= 0:
        raise ValueError("Expected a top-ten city and positive population")
    if c.eligibility_kind == "current_candidacy":
        if c.position <= 0:
            raise ValueError("Current candidacies require a positive list position")
    elif c.eligibility_kind == "reviewed_local_role":
        if c.position != 0 or not c.local_role_verified:
            raise ValueError("Noncandidate discovery requires a reviewed current local political role")
    else:
        raise ValueError("Unknown eligibility provenance")
    observed = (c.party_strength, c.local_vote_lift, c.followers)
    if any(v is not None and (not math.isfinite(v) or v < 0) for v in observed):
        raise ValueError("Observed signals must be finite and nonnegative")
    if c.local_vote_rank is not None and c.local_vote_rank <= 0:
        raise ValueError("Historical vote rank must be positive")
    historical = c.historical_identity_clear
    vote_signals = []
    if historical and c.local_vote_rank is not None:
        vote_signals.append(3 / c.local_vote_rank)
    if historical and c.local_vote_lift is not None:
        vote_signals.append(c.local_vote_lift / 1.25)
    components: dict[str, float | None] = {
        "office": max(
            1.5 * c.current_office_verified,
            float(c.mandate_evidence) if historical else 0.0,
        )
        if historical or c.current_office_verified
        else None,
        "party_contender": c.party_strength if 1 <= c.position <= 3 else 0.0,
        "local_votes": max(vote_signals) if vote_signals else None,
        # Leadership is discovery context, not an independent relevance signal.
        # Keep these slots for explanation/consumer compatibility with v1.
        "prior_leader": 0.0 if historical and c.prior_leader is not None else None,
        "public_reach": max(c.followers / 10_000, c.followers / (0.10 * c.population))
        if c.followers is not None
        else None,
        "public_activity": float(c.activity_verified) if c.activity_verified is not None else None,
        "list_leader": 0.0,
    }
    components = {k: min(2.0, max(0.0, v)) if v is not None else None for k, v in components.items()}
    score = max((v for v in components.values() if v is not None), default=0.0)
    reasons = tuple(k for k in CHANNELS if (value := components[k]) is not None and value >= 1)
    winner = next((k for k in CHANNELS if components[k] == score), None) if score > 0 else None
    qualified = c.eligible and score >= 1
    # A leader needs a separate strong signal before entering the protected pool.
    protected = (
        qualified
        and (components["party_contender"] is None or components["party_contender"] < 1)
        and (
            (components["public_activity"] is not None and components["public_activity"] >= 1)
            or (components["public_reach"] is not None and components["public_reach"] >= 1)
            or (
                (c.position == 1 or c.local_role_verified)
                and (c.party_strength is None or c.party_strength < 1)
            )
        )
    )
    return Decision(c, components, reasons, winner, score, qualified, protected)


def stable_key(decision: Decision) -> tuple:
    """Use no secondary sum or count of weak channels to break ties."""
    c = decision.candidate
    return (
        -decision.score,
        CHANNELS.index(decision.winner) if decision.winner else len(CHANNELS),
        c.position if c.position else math.inf,
        int(c.list_no),
        c.key,
    )


@dataclass(frozen=True)
class Schedule:
    selected: tuple[Decision, ...]
    deferred: tuple[Decision, ...]
    cost: Decimal
    protected_slots_requested: int
    protected_slots_filled: int
    exploratory: tuple[Decision, ...]


def schedule(
    decisions: list[Decision],
    per_city: int,
    budget: Decimal,
    costs: dict[str, Decimal],
    exploration_round: int = 0,
) -> Schedule:
    """Reserve newcomer seats first, visit cities round-robin, and never exceed the cost bound."""
    if (
        per_city < 0
        or not budget.is_finite()
        or budget < 0
        or any(not cost.is_finite() or cost < 0 for cost in costs.values())
    ):
        raise ValueError("Capacities, budgets and costs must be nonnegative")
    qualified = sorted(
        (d for d in decisions if d.qualified),
        key=lambda d: (d.candidate.city_rank, stable_key(d)),
    )
    if len({d.candidate.key for d in decisions}) != len(decisions):
        raise ValueError("Candidate keys must be unique")
    cities = sorted(
        {(d.candidate.city_rank, d.candidate.city_code) for d in decisions if d.candidate.eligible}
    )
    reserve = min(per_city, max(1, math.ceil(per_city * 0.20))) if per_city else 0
    queues: dict[str, list[Decision]] = {}
    exploratory_keys = set()
    requested = 0
    for _, code in cities:
        pool = sorted((d for d in qualified if d.candidate.city_code == code), key=stable_key)
        protected = [d for d in pool if d.protected][:reserve]
        requested += len(protected)
        protected_keys = {d.candidate.key for d in protected}
        exploration_capacity = max(1, math.floor(per_city * 0.05)) if per_city >= 5 else 0
        unknown = [
            d
            for d in decisions
            if not d.qualified
            and d.candidate.eligible
            and d.candidate.city_code == code
            and d.candidate.eligibility_kind == "current_candidacy"
            and d.candidate.position in (2, 3)
            and (d.candidate.followers is None or d.candidate.activity_verified is None)
        ]
        unknown.sort(
            key=lambda d: (
                d.candidate.position,
                hashlib.sha256(f"{exploration_round}:{d.candidate.key}".encode()).hexdigest(),
                d.candidate.key,
            )
        )
        exploratory = unknown[:exploration_capacity]
        exploratory_keys.update(d.candidate.key for d in exploratory)
        queues[code] = (protected + exploratory + [d for d in pool if d.candidate.key not in protected_keys])[
            :per_city
        ]
    selected = []
    cost = Decimal(0)
    # Reserve rounds happen before general rounds; no city can exhaust the global budget in one pass.
    for index in range(per_city):
        for _, code in cities:
            queue = queues[code]
            if index >= len(queue):
                continue
            decision = queue[index]
            price = costs[decision.candidate.key]
            if cost + price <= budget:
                selected.append(decision)
                cost += price
    keys = {d.candidate.key for d in selected}
    deferred = tuple(d for d in qualified if d.candidate.key not in keys)
    return Schedule(
        tuple(selected),
        deferred,
        cost,
        requested,
        sum(d.protected for d in selected),
        tuple(d for d in selected if d.candidate.key in exploratory_keys),
    )
