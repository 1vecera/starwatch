"""Single local run/night ledger. Money and its audit journal commit in one fsynced rename.

Only the coordinator uses this ledger. Native subscription usage is unpriced; an
explicit external accounting snapshot must conservatively cover every other lane.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

SCOPE_ID = "starwatch-ten-city-production-20261009"
CITIES = {
    "Praha",
    "Brno",
    "Ostrava",
    "Plzeň",
    "Liberec",
    "Olomouc",
    "České Budějovice",
    "Hradec Králové",
    "Pardubice",
    "Ústí nad Labem",
}
TERMINAL = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}
RUN_CAP = Decimal(100)
NIGHT_CAP = Decimal(120)
AMENDED_RUN_CAP = Decimal(110)
ZERO = Decimal(0)


class BudgetError(RuntimeError):
    """Unsafe or inconsistent ledger state."""


class CapExceeded(BudgetError):
    """A reservation would exceed either authorized ceiling."""


class AmbiguousStart(BudgetError):
    """A start may have happened; recover its run rather than retrying."""


def money(value: Any) -> Decimal:
    """Reject inexact local floats and malformed/negative/nonfinite money."""
    if isinstance(value, (float, bool)):
        raise TypeError("Use decimal strings for money")
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("Invalid decimal amount") from exc
    if not amount.is_finite() or amount < ZERO:
        raise ValueError("Money must be finite and nonnegative")
    if len(amount.as_tuple().digits) > 50 or amount.adjusted() > 20 or int(amount.as_tuple().exponent) < -30:
        raise ValueError("Money exceeds the exact ledger precision/range")
    return amount


def provider_option_check(manifest: dict, run: dict) -> tuple[list[str], Decimal | None]:
    """Compare provider-accepted limits to the durable attempt, without trusting supplied error text."""
    expected = {
        "maxTotalChargeUsd": manifest["max_total_charge_usd"],
        "maxItems": manifest["max_items"],
        "timeoutSecs": manifest["timeout_s"],
        "memoryMbytes": manifest["memory_mb"],
    }
    options = run.get("options")
    if not isinstance(options, dict):
        return list(expected), None
    mismatch, observed_cap = [], None
    for field, value in expected.items():
        try:
            if field == "maxTotalChargeUsd":
                observed_cap = money(options[field])
                same = observed_cap == money(value)
            else:
                same = type(options.get(field)) is int and options[field] == value
        except (ValueError, TypeError, KeyError):
            same = False
        if not same:
            mismatch.append(field)
    return mismatch, observed_cap


def charged_event_floor(run: dict, observations: dict | None = None) -> tuple[Decimal, bool]:
    """Retain positive counts and effective prices across lagging/missing provider observations.

    Event identifiers are hashed before persistence; source bodies and arbitrary
    identifiers never enter the ledger. An absent or zero count cannot erase an
    earlier positive charge. Missing positive-event prices stay unresolved until
    an effective price is observed for that same event.
    """
    observations = {} if observations is None else observations
    counts = run.get("chargedEventCounts")
    pricing = run.get("pricingInfo") or {}
    prices = pricing.get("pricingPerEvent", {}).get("actorChargeEvents", {}) if isinstance(pricing, dict) else {}
    if isinstance(counts, dict):
        # A later explicit complete count map can resolve a previously absent
        # map. It cannot erase retained positive or malformed event evidence.
        observations.pop("missing-event-counts", None)
        if run.get("status") in TERMINAL and all(type(count) is int and count == 0 for count in counts.values()):
            observations["observed-zero-events"] = {"count": 0, "unit_price_usd": "0"}
    elif "chargedEventCounts" in run:
        observations["unreadable-event-counts"] = {"count": None, "unit_price_usd": None}
        counts = {}
    else:
        if not observations:
            observations["missing-event-counts"] = {"count": None, "unit_price_usd": None}
        counts = {}
    if not isinstance(prices, dict):
        prices = {}
    for event, count in counts.items():
        event_key = digest(event)
        previous = observations.get(event_key)
        if type(count) is not int or count < 0:
            observations["unreadable-" + event_key] = {"count": None, "unit_price_usd": None}
            continue
        if count:
            observations[event_key] = {
                "count": max(count, previous["count"] if previous else 0),
                "unit_price_usd": previous["unit_price_usd"] if previous else None,
            }
    # Prices can resolve retained counts even when a later reply omits its count map.
    for event, price in prices.items():
        event_key = digest(event)
        if event_key not in observations:
            continue
        try:
            rate = money(price["eventPriceUsd"])
        except (ValueError, TypeError, KeyError):
            continue
        previous_rate = observations[event_key]["unit_price_usd"]
        observations[event_key]["unit_price_usd"] = str(max(rate, money(previous_rate) if previous_rate else ZERO))
    floor, complete = ZERO, True
    for event in observations.values():
        if event["count"] is None or event["unit_price_usd"] is None:
            complete = False
        else:
            floor += event["count"] * money(event["unit_price_usd"])
    return floor, complete


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp(value: str) -> float:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("A timezone is required")
    return parsed.timestamp()


def atomic_write(path: Path, content: bytes) -> None:
    """Durably replace a private file; interrupted writes leave its previous version."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def accounting_snapshot(path: Path, now: float) -> dict:
    """Import attributable settled costs and explicit unresolved provisions without guessing zero."""
    snapshot = json.loads(path.read_text())
    if (
        snapshot.get("schema_version") != 1
        or snapshot.get("scope") != "night"
        or snapshot.get("complete") is not True
        or not snapshot.get("entries")
    ):
        raise ValueError("A complete nonempty night accounting snapshot is required")
    observed = timestamp(snapshot["observed_at"])
    if observed > now + 60 or not timestamp(snapshot["period_start"]) <= observed <= timestamp(snapshot["period_end"]):
        raise ValueError("Invalid accounting observation/period")
    entries, seen = [], set()
    for entry in snapshot["entries"]:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", entry["id"]) or entry["id"] in seen:
            raise ValueError("Accounting IDs must be unique and stable")
        seen.add(entry["id"])
        actual, reserve = money(entry["settled_usd"]), money(entry["reserved_usd"])
        status = entry["status"]
        if status not in {"settled", "unresolved", "unpriced_subscription"} or not entry.get("evidence"):
            raise ValueError("Every accounting lane needs status and evidence")
        if status == "unresolved" and reserve <= ZERO:
            raise ValueError("Unresolved charges require a positive conservative reservation")
        if status == "settled" and reserve != ZERO:
            raise ValueError("Settled external charges cannot retain a reservation")
        if status == "unpriced_subscription" and (
            actual != ZERO or reserve != ZERO or entry["provider"] != "native-codex"
        ):
            raise ValueError("Only native subscription consumption may be recorded as unpriced")
        if type(entry["applies_to_production"]) is not bool:
            raise ValueError("Every lane must declare production attribution")
        entries.append(
            {key: entry[key] for key in ("id", "provider", "lane", "status", "evidence", "applies_to_production")}
            | {"settled_usd": str(actual), "reserved_usd": str(reserve)}
        )
    return {
        "schema_version": 1,
        "scope": "night",
        "complete": True,
        "observed_at": snapshot["observed_at"],
        "period_start": snapshot["period_start"],
        "period_end": snapshot["period_end"],
        "entries": entries,
        "snapshot_path": str(path.resolve()),
        "snapshot_sha256": file_hash(path),
    }


class ProductionBudget:
    """Flock protects all reservations, run bindings, observations and external accounting."""

    def __init__(self, root: Path, *, clock: Callable[[], float] = time.time):
        self.root = Path(root).resolve()
        self.state_path = self.root / "budget.json"
        self.clock = clock

    @contextmanager
    def locked(self) -> Iterator[dict]:
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / ".budget.lock").open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                with localcontext() as context:
                    context.prec = 80
                    yield json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _commit(self, state: dict, event: str, batch_id: str | None = None) -> None:
        state["sequence"] += 1
        state["journal"].append(
            {
                "sequence": state["sequence"],
                "at": self.clock(),
                "event": event,
                "batch_id": batch_id,
                "totals": self._totals(state),
            }
        )
        atomic_write(self.state_path, canonical(state) + b"\n")

    def initialize(
        self, auth_path: Path, auth_sha256: str, accounting_path: Path, *, hold_paths: tuple[Path, ...] = ()
    ) -> dict:
        """Pin the real authorization and retain every historical hold unchanged."""
        auth_path = Path(auth_path).resolve()
        if file_hash(auth_path) != auth_sha256:
            raise ValueError("Authorization hash mismatch")
        auth = json.loads(auth_path.read_text())
        if (
            auth.get("authorization_id") != "daniel-production-20261009"
            or auth.get("authorized_by") != "Daniel"
            or auth.get("status") != "authorized_for_execution"
            or money(auth["run_cap_usd"]) != RUN_CAP
            or money(auth["overall_night_cap_usd"]) != NIGHT_CAP
            or auth.get("brief") != "docs/tasks/hos-production.md"
            or auth.get("supersedes_historical_paid_hold_for_this_run_only") is not True
        ):
            raise ValueError("Authority must cover only the existing ten-city $100/$120 production run")
        authorized = timestamp(auth["recorded_at"])
        if authorized > self.clock() + 60:
            raise ValueError("Authorization was recorded in the future")
        # Always inspect the coordinator's canonical legacy hold, even if currently absent.
        paths = {self.root.parent / "paid_launch_hold.json", *(Path(p).resolve() for p in hold_paths)}
        holds = []
        for path in sorted(paths):
            if path.exists():
                hold = json.loads(path.read_text())
                held_at = hold.get("updated_at") or hold.get("held_at")
                if not held_at or timestamp(held_at) > authorized:
                    raise BudgetError("Newer or undated hold is not superseded")
                holds.append(
                    {
                        "path": str(path),
                        "sha256": file_hash(path),
                        "superseded_at": auth["recorded_at"],
                        "scope_id": SCOPE_ID,
                    }
                )
            else:
                holds.append({"path": str(path), "sha256": None})
        snapshot = accounting_snapshot(Path(accounting_path), self.clock())
        with self.locked() as state:
            if state:
                if state["auth_sha256"] != auth_sha256 or state["auth_path"] != str(auth_path):
                    raise BudgetError("This ledger is already pinned to another authority")
                self._check_authority(state)
                return self._summary(state)
            state.update(
                schema_version=1,
                scope_id=SCOPE_ID,
                auth_path=str(auth_path),
                auth_sha256=auth_sha256,
                authorization=auth,
                holds=holds,
                accounting=snapshot,
                batches={},
                sequence=0,
                journal=[],
            )
            if money(self._totals(state)["night_committed_usd"]) > NIGHT_CAP:
                raise CapExceeded("Imported night commitments already exceed $120")
            if money(self._totals(state)["run_committed_usd"]) > RUN_CAP:
                raise CapExceeded("Imported production commitments already exceed $100")
            self._commit(state, "initialized")
            return self._summary(state)

    def _check_authority(self, state: dict) -> None:
        if not state:
            raise BudgetError("Initialize the shared production ledger first")
        path = Path(state["auth_path"])
        if not path.exists() or file_hash(path) != state["auth_sha256"]:
            raise BudgetError("Pinned authorization is missing or changed")
        parent_sha = state["auth_sha256"]
        for amendment in state.get("authorization_amendments", []):
            path = Path(amendment["path"])
            if (not path.exists() or file_hash(path) != amendment["sha256"]
                    or json.loads(path.read_text()) != amendment["authorization"]
                    or amendment["authorization"]["parent_authorization_sha256"] != parent_sha):
                raise BudgetError("Pinned authorization amendment is missing, changed or unchained")
            parent_sha = amendment["sha256"]
        if any(batch.get("safety_hold") for batch in state["batches"].values()):
            raise BudgetError("Provider option verification is unresolved; no paid expansion")
        for hold in state["holds"]:
            path = Path(hold["path"])
            current = file_hash(path) if path.exists() else None
            if current != hold["sha256"]:
                raise BudgetError("A paid-launch hold changed after initialization")

    def _effective_caps(self, state: dict) -> tuple[Decimal, Decimal]:
        amendments = state.get("authorization_amendments", [])
        authority = amendments[-1]["authorization"] if amendments else state["authorization"]
        return money(authority["run_cap_usd"]), money(authority["overall_night_cap_usd"])

    def import_authorization_amendment(self, path: Path, sha256: str) -> dict:
        """Append Daniel's pinned $110/$120 extension without rewriting prior authority or holds."""
        path = Path(path).resolve()
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise ValueError("Authorization amendment hash mismatch")
        authority = json.loads(raw)
        evidence = authority.get("evidence") if isinstance(authority, dict) else None
        evidence_valid = ((isinstance(evidence, str) and bool(evidence.strip()))
            or (isinstance(evidence, dict) and set(evidence) == {"session", "user_words", "interpretation"}
                and all(isinstance(value, str) and bool(value.strip()) for value in evidence.values())))
        required = {"schema_version", "authorization_id", "amends_authorization_id",
                    "parent_authorization_sha256", "scope_id", "authorized_by", "status",
                    "run_cap_usd", "overall_night_cap_usd", "brief", "recorded_at", "evidence"}
        if (not isinstance(authority, dict) or set(authority) != required
                or type(authority["schema_version"]) is not int or authority["schema_version"] != 1
                or authority["scope_id"] != SCOPE_ID
                or authority["authorized_by"] != "Daniel" or authority["status"] != "authorized_for_execution"
                or authority["brief"] != "docs/tasks/hos-production.md"
                or money(authority["run_cap_usd"]) != AMENDED_RUN_CAP
                or money(authority["overall_night_cap_usd"]) != NIGHT_CAP
                or not isinstance(authority["authorization_id"], str)
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", authority["authorization_id"])
                or not evidence_valid
                or timestamp(authority["recorded_at"]) > self.clock() + 60):
            raise ValueError("Amendment must pin the explicitly authorized ten-city $110/$120 extension")
        with self.locked() as state:
            self._check_authority(state)
            amendments = state.get("authorization_amendments", [])
            matching = [row for row in amendments if row["authorization"]["authorization_id"] == authority["authorization_id"]]
            if matching:
                if len(matching) != 1 or matching[0]["path"] != str(path) or matching[0]["sha256"] != sha256:
                    raise BudgetError("Authorization amendment identity already belongs to another exact receipt")
                return self._summary(state)
            parent = amendments[-1] if amendments else {
                "path": state["auth_path"], "sha256": state["auth_sha256"], "authorization": state["authorization"]}
            if (str(path) in {state["auth_path"], *(row["path"] for row in amendments)}
                    or authority["authorization_id"] == state["authorization"]["authorization_id"]
                    or authority["amends_authorization_id"] != parent["authorization"]["authorization_id"]
                    or authority["parent_authorization_sha256"] != parent["sha256"]
                    or timestamp(authority["recorded_at"]) < timestamp(parent["authorization"]["recorded_at"])
                    or money(authority["run_cap_usd"]) <= self._effective_caps(state)[0]):
                raise BudgetError("Amendment must extend the exact current authority with a new immutable receipt")
            if path.read_bytes() != raw:
                raise BudgetError("Authorization amendment changed before import")
            state.setdefault("authorization_amendments", []).append({
                "path": str(path), "sha256": sha256, "authorization": authority,
                "imported_at": self.clock()})
            self._commit(state, "authorization_amended")
            return self._summary(state)

    def _totals(self, state: dict) -> dict:
        run_cap, night_cap = self._effective_caps(state)
        totals = {
            "night_actual_usd": ZERO,
            "night_reserved_usd": ZERO,
            "run_actual_usd": ZERO,
            "run_reserved_usd": ZERO,
        }
        for entry in state.get("accounting", {}).get("entries", []):
            for kind, field in (("actual", "settled_usd"), ("reserved", "reserved_usd")):
                totals[f"night_{kind}_usd"] += money(entry[field])
                if entry["applies_to_production"]:
                    totals[f"run_{kind}_usd"] += money(entry[field])
        for batch in state.get("batches", {}).values():
            for kind, field in (("actual", "actual_usd"), ("reserved", "reserved_usd")):
                totals[f"night_{kind}_usd"] += money(batch[field])
                totals[f"run_{kind}_usd"] += money(batch[field])
        totals["night_committed_usd"] = totals["night_actual_usd"] + totals["night_reserved_usd"]
        totals["run_committed_usd"] = totals["run_actual_usd"] + totals["run_reserved_usd"]
        totals["night_remaining_usd"] = max(ZERO, night_cap - totals["night_committed_usd"])
        totals["run_remaining_usd"] = max(ZERO, run_cap - totals["run_committed_usd"])
        return {key: str(value) for key, value in totals.items()}

    def _summary(self, state: dict) -> dict:
        if not state:
            raise BudgetError("Ledger is not initialized")
        totals = self._totals(state)
        run_cap, night_cap = self._effective_caps(state)
        return {
            "scope_id": state["scope_id"],
            "run_cap_usd": str(run_cap),
            "night_cap_usd": str(night_cap),
            "authorization_sha256": state["auth_sha256"],
            "authorization_amendments": copy.deepcopy(state.get("authorization_amendments", [])),
            "accounting_sha256": state["accounting"]["snapshot_sha256"],
            "sequence": state["sequence"],
            **totals,
            "over_cap": money(totals["run_committed_usd"]) > run_cap
            or money(totals["night_committed_usd"]) > night_cap,
            "unpriced_subscription": [
                e for e in state["accounting"]["entries"] if e["status"] == "unpriced_subscription"
            ],
            "batches": copy.deepcopy(state["batches"]),
        }

    def status(self) -> dict:
        with self.locked() as state:
            return self._summary(state)

    def batch(self, batch_id: str) -> dict:
        with self.locked() as state:
            return copy.deepcopy(state["batches"][batch_id])

    def reserve(self, manifest: dict) -> dict:
        """Store exact reviewed inputs/price basis and reserve before crossing a network boundary."""
        manifest = json.loads(canonical(manifest))
        batch_id = manifest["batch_id"]
        if (
            manifest["scope_id"] != SCOPE_ID
            or manifest["schema_version"] != 1
            or not manifest["cities"]
            or not set(manifest["cities"]) <= CITIES
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", batch_id)
            or manifest["input_sha256"] != digest(manifest["input"])
        ):
            raise ValueError("Reservation must pin an exact authorized scope/input/batch")
        with self.locked() as state:
            self._check_authority(state)
            if batch_id in state["batches"]:
                batch = state["batches"][batch_id]
                if batch["manifest_sha256"] != digest(manifest):
                    raise BudgetError("Idempotency ID already belongs to different exact inputs")
                return copy.deepcopy(batch)
            self._check_accounting_time(state)
            maximum = money(manifest["max_total_charge_usd"])
            if maximum <= ZERO:
                raise ValueError("A positive batch cap is required")
            totals = self._totals(state)
            run_cap, night_cap = self._effective_caps(state)
            if (
                money(totals["run_committed_usd"]) + maximum > run_cap
                or money(totals["night_committed_usd"]) + maximum > night_cap
            ):
                raise CapExceeded("Reservation exceeds the run or night ceiling")
            batch = {
                "manifest": manifest,
                "manifest_sha256": digest(manifest),
                "phase": "RESERVED",
                "actual_usd": "0",
                "reserved_usd": str(maximum),
                "reserved_at": self.clock(),
                "run_id": None,
                "status": None,
                "dataset_id": None,
                "terminal_seen_at": None,
                "billing_settled": False,
                "last_charge_change_at": None,
                "landing": None,
            }
            state["batches"][batch_id] = batch
            self._commit(state, "reserved", batch_id)
            return copy.deepcopy(batch)

    def _check_accounting_time(self, state: dict) -> None:
        snapshot = state["accounting"]
        now = self.clock()
        if not timestamp(snapshot["period_start"]) <= now <= timestamp(snapshot["period_end"]):
            raise BudgetError("Current time is outside the imported night accounting window")
        if now - timestamp(snapshot["observed_at"]) > 3600:
            raise BudgetError("External accounting is stale; refresh before paid expansion")

    def begin_start(self, batch_id: str) -> dict:
        """Persist STARTING before POST; this phase can never automatically relaunch."""
        with self.locked() as state:
            self._check_authority(state)
            self._check_accounting_time(state)
            batch = state["batches"][batch_id]
            if batch["phase"] != "RESERVED":
                raise AmbiguousStart("Existing attempt cannot be replayed")
            if self._summary(state)["over_cap"]:
                raise CapExceeded("Recorded commitments exceed an authorized cap")
            batch.update(phase="STARTING", start_boundary_at=self.clock())
            self._commit(state, "start_boundary", batch_id)
            return copy.deepcopy(batch)

    def record_diagnostic(
        self, batch_id: str, diagnostic: dict, *, exposure_cap: Decimal | None = None, safety_hold: bool = False
    ) -> None:
        """Persist only fixed diagnostic fields and conservatively cover a provider's known higher cap."""
        allowed = {"kind", "operation", "http_status", "error_type", "mismatched_options", "candidate_run_id"}
        if diagnostic.keys() - allowed:
            raise ValueError("Unreviewed diagnostic keys")
        with self.locked() as state:
            batch = state["batches"][batch_id]
            batch["last_diagnostic"] = diagnostic
            if safety_hold:
                batch["safety_hold"] = True
            if exposure_cap is not None:
                cap = max(
                    money(batch.get("exposure_cap_usd", batch["manifest"]["max_total_charge_usd"])), money(exposure_cap)
                )
                batch["exposure_cap_usd"] = str(cap)
                batch["reserved_usd"] = str(max(money(batch["reserved_usd"]), cap - money(batch["actual_usd"])))
            self._commit(state, "diagnostic_recorded", batch_id)

    def record_start_response(self, batch_id: str, run: dict) -> None:
        """Pin this POST's exact returned identity before any subsequent crash.

        Similar actor/input/time metadata is never proof that an arbitrary run
        belongs to an ambiguous attempt. Only this sanitized durable response
        receipt can authorize later binding; missing receipts keep the full hold.
        """
        run_id, actor_id, started_at = run.get("id"), run.get("actId"), run.get("startedAt")
        for value in (run_id, actor_id):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
                raise ValueError("Invalid start response identity")
        timestamp(started_at)
        with self.locked() as state:
            batch = state["batches"][batch_id]
            if batch["phase"] != "STARTING" or batch["run_id"] is not None:
                raise BudgetError("Start response requires an unbound persisted attempt")
            if any(b["run_id"] == run_id or b.get("start_response_receipt", {}).get("run_id") == run_id
                   for key, b in state["batches"].items() if key != batch_id):
                raise BudgetError("Start response run identity already belongs to another batch")
            receipt = {"schema_version": 1, "run_id": run_id, "actor_id": actor_id,
                       "started_at": started_at, "manifest_sha256": batch["manifest_sha256"],
                       "input_sha256": batch["manifest"]["input_sha256"]}
            previous = batch.get("start_response_receipt")
            if previous is not None and previous != receipt:
                raise BudgetError("Cannot replace an exact start response receipt")
            batch["start_response_receipt"] = receipt
            self._commit(state, "start_response_recorded", batch_id)

    def verify_options(self, batch_id: str, run: dict) -> None:
        batch = self.batch(batch_id)
        mismatched, cap = provider_option_check(batch["manifest"], run)
        if mismatched:
            candidate = run.get("id")
            diagnostic = {
                "kind": "provider_options_mismatch",
                "operation": "verify_run",
                "mismatched_options": mismatched,
            }
            if isinstance(candidate, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", candidate):
                diagnostic["candidate_run_id"] = candidate
            self.record_diagnostic(batch_id, diagnostic, exposure_cap=cap, safety_hold=True)
            raise BudgetError("Provider limits differ or are missing; reservation/safety hold retained")

    def bind_run(self, batch_id: str, run_id: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
            raise ValueError("Invalid run ID")
        with self.locked() as state:
            batch = state["batches"][batch_id]
            if any(b["run_id"] == run_id for key, b in state["batches"].items() if key != batch_id):
                raise BudgetError("Remote run is already bound to another batch")
            if batch["run_id"] not in (None, run_id) or batch["phase"] not in {"STARTING", "RUN_BOUND"}:
                raise BudgetError("Cannot replace an existing run binding")
            batch.update(run_id=run_id, phase="RUN_BOUND", safety_hold=False)
            self._commit(state, "run_bound", batch_id)

    def observe(self, batch_id: str, run: dict) -> dict:
        """Retain the cap until a fresh terminal bill is observed after a five-minute buffer."""
        self.verify_options(batch_id, run)
        with self.locked() as state:
            batch = state["batches"][batch_id]
            batch["safety_hold"] = False
            if run["id"] != batch["run_id"]:
                raise BudgetError("Run observation does not match its binding")
            usage = run.get("usageTotalUsd")
            events = batch.setdefault("billing_events", {})
            if batch.get("billing_prices_complete") is False and not events:
                # Earlier versions did not retain unknown event IDs/counts. Do not silently clear that gap.
                events["legacy-unresolved-events"] = {"count": None, "unit_price_usd": None}
            floor, prices_complete = charged_event_floor(run, events)
            floor = max(floor, money(batch.get("billing_floor_usd", "0")))
            batch["billing_floor_usd"] = str(floor)
            batch["billing_prices_complete"] = prices_complete
            counts = run.get("chargedEventCounts")
            batch["billing_counts_complete"] = (isinstance(counts, dict)
                and all(type(count) is int and count >= 0 for count in counts.values()))
            batch["billing_contradiction"] = usage is None or not prices_complete or money(usage) < floor
            # Neither a lagging usage total nor missing event prices can erase a known charge.
            actual = max(money(batch["actual_usd"]), floor, money(usage) if usage is not None else ZERO)
            if actual > money(batch["actual_usd"]) or batch.get("last_charge_change_at") is None:
                batch["last_charge_change_at"] = self.clock()
            batch["actual_usd"] = str(actual)
            terminal = run["status"] in TERMINAL
            if not terminal:
                batch["terminal_seen_at"] = None
            if terminal and batch["terminal_seen_at"] is None:
                batch["terminal_seen_at"] = self.clock()
            ready = (
                terminal
                and batch["billing_counts_complete"]
                and not batch["billing_contradiction"]
                and run.get("finishedAt")
                and timestamp(run["finishedAt"]) <= self.clock() - 300
                and self.clock() - batch["terminal_seen_at"] >= 300
                and self.clock() - batch["last_charge_change_at"] >= 300
            )
            batch["billing_settled"] = bool(ready)
            batch["reserved_usd"] = (
                "0"
                if ready
                else str(
                    max(
                        ZERO,
                        money(batch.get("exposure_cap_usd", batch["manifest"]["max_total_charge_usd"]))
                        - money(batch["actual_usd"]),
                    )
                )
            )
            batch.update(status=run["status"], dataset_id=run.get("defaultDatasetId"), last_observed_at=self.clock())
            self._commit(state, "run_observed", batch_id)
            return copy.deepcopy(batch)

    def record_landing(self, batch_id: str, receipt: dict) -> None:
        with self.locked() as state:
            state["batches"][batch_id]["landing"] = receipt
            self._commit(state, "dataset_landed", batch_id)

    def import_accounting(self, path: Path) -> dict:
        """Replace a complete snapshot only with stable lane IDs and evidenced settlements."""
        snapshot = accounting_snapshot(path, self.clock())
        with self.locked() as state:
            self._check_authority(state)
            previous = {e["id"]: e for e in state["accounting"]["entries"]}
            current = {e["id"]: e for e in snapshot["entries"]}
            if not previous.keys() <= current.keys() or timestamp(snapshot["observed_at"]) < timestamp(
                state["accounting"]["observed_at"]
            ):
                raise BudgetError("Accounting snapshot cannot drop lanes or move backward")
            if (snapshot["period_start"], snapshot["period_end"]) != (
                state["accounting"]["period_start"],
                state["accounting"]["period_end"],
            ):
                raise BudgetError("Cannot change this ledger's night accounting period")
            for key, old in previous.items():
                new = current[key]
                if any(new[k] != old[k] for k in ("provider", "lane", "applies_to_production")):
                    raise BudgetError("Accounting identity/attribution changed")
                if money(new["settled_usd"]) < money(old["settled_usd"]):
                    raise BudgetError("Cannot erase an observed settled charge")
                if (
                    money(new["reserved_usd"]) < money(old["reserved_usd"])
                    and new["status"] != "settled"
                    and money(new["settled_usd"]) + money(new["reserved_usd"])
                    < money(old["settled_usd"]) + money(old["reserved_usd"])
                ):
                    raise BudgetError("Cannot reduce an unresolved commitment without settlement")
                if old["status"] == "unresolved" and new["status"] == "settled" and new["evidence"] == old["evidence"]:
                    raise BudgetError("Releasing unresolved external accounting needs new settlement evidence")
            state["accounting"] = snapshot
            self._commit(state, "accounting_imported")
            return self._summary(state)
