"""Prepare a new category-based accounting snapshot from cached provider evidence.

No network, launch, reconciliation or ledger mutation occurs. Root independently
imports the resulting pinned snapshot through ProductionBudget.import_accounting.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from decimal import Decimal, localcontext
from pathlib import Path

from .production_budget import canonical, money, timestamp

ACTOR_CATEGORIES = {"PAID_ACTORS_PER_EVENT", "ACTOR_COMPUTE_UNITS"}
OVERHEAD_ID = "production.storage_http_provision"


def _category_amounts(observation: dict) -> dict[str, dict[str, Decimal]]:
    days = observation.get("daily_control")
    if not isinstance(days, list) or not days:
        raise ValueError("Complete dated provider service categories are required")
    result = {}
    for day in days:
        date = day.get("date")
        if not isinstance(date, str) or date in result:
            raise ValueError("Unique provider category dates are required")
        timestamp(date)
        services = day.get("serviceUsage")
        if not isinstance(services, dict) or not services:
            raise ValueError("Provider serviceUsage must be a nonempty object")
        result[date] = {}
        for category, item in services.items():
            if not isinstance(category, str) or not category or not isinstance(item, dict):
                raise ValueError("Malformed provider service category")
            result[date][category] = money(item["baseAmountUsd"])
    return result


def _prepare_accounting_refresh(ledger_path: Path, baseline_path: Path,
                               observation_path: Path, output_directory: Path) -> dict:
    """Retain every provision and add positive nonactor category increments only."""
    input_paths = [Path(path).resolve() for path in (ledger_path, baseline_path, observation_path)]
    raw = {path: path.read_bytes() for path in input_paths}
    ledger, baseline, observation = [json.loads(raw[path], parse_float=str) for path in input_paths]
    accounting = ledger["accounting"]
    snapshot_path = Path(accounting["snapshot_path"])
    if hashlib.sha256(snapshot_path.read_bytes()).hexdigest() != accounting["snapshot_sha256"]:
        raise ValueError("Pinned current accounting snapshot changed")
    matches = [entry for entry in accounting["entries"] if entry["id"] == OVERHEAD_ID]
    if len(matches) != 1:
        raise ValueError("Exact production overhead provision required")
    old_entry = matches[0]
    evidence = old_entry.get("evidence")
    if (not isinstance(evidence, dict) or evidence.get("refresh_path") != str(input_paths[1])
            or evidence.get("refresh_sha256") != hashlib.sha256(raw[input_paths[1]]).hexdigest()
            or old_entry["status"] != "unresolved" or old_entry["provider"] != "apify"
            or old_entry["applies_to_production"] is not True):
        raise ValueError("Current overhead must bind the exact latest provider baseline")
    observed_at = observation["observed_at"]
    if (timestamp(observed_at) < timestamp(baseline["observed_at"])
            or timestamp(observed_at) < timestamp(accounting["observed_at"])
            or not timestamp(accounting["period_start"]) <= timestamp(observed_at) <= timestamp(accounting["period_end"])):
        raise ValueError("Observation must move forward within the same authorized accounting period")
    previous, current = _category_amounts(baseline), _category_amounts(observation)
    # Carry maxima separately from the latest raw reply. A disappeared/decreased
    # category later returning to its old amount is not a second new charge.
    retained = baseline.get("category_floors", {})
    if not isinstance(retained, dict):
        raise ValueError("Malformed retained category floors")
    for date, services in retained.items():
        if not isinstance(services, dict):
            raise ValueError("Malformed retained category day")
        previous.setdefault(date, {})
        for category, amount in services.items():
            previous[date][category] = max(previous[date].get(category, Decimal(0)), money(amount))
    if current.keys() != previous.keys():
        raise ValueError("Complete unchanged daily category scope is required")
    floors = copy.deepcopy(previous)
    deltas = {}
    increment = Decimal(0)
    for date, services in current.items():
        for category, amount in services.items():
            before = previous[date].get(category, Decimal(0))
            floors[date][category] = max(before, amount)
            if category not in ACTOR_CATEGORIES and amount > before:
                deltas.setdefault(date, {})[category] = str(amount - before)
                increment += amount - before
    known_production = {}
    for batch in ledger["batches"].values():
        run_id = batch.get("run_id")
        actor = batch.get("manifest", {}).get("actor")
        if run_id and isinstance(actor, str) and "/" in actor:
            if run_id in known_production:
                raise ValueError("Duplicate bound actor run ID")
            known_production[run_id] = money(batch["actual_usd"])
    legacy_actor = sum((money(entry["settled_usd"]) for entry in accounting["entries"]
        if entry["provider"] == "apify" and entry["id"].startswith("legacy.apify.")
        and entry["id"] != "legacy.apify.account_daily_usage_residual"), Decimal(0))
    actor_control = sum((amount for services in current.values() for category, amount in services.items()
                         if category in ACTOR_CATEGORIES), Decimal(0))
    production_actor = sum(known_production.values(), Decimal(0))
    output_directory = Path(output_directory).absolute()
    if output_directory.exists() or str(output_directory.resolve()) != str(output_directory):
        raise ValueError("A new canonical output directory is required")
    if any(path.read_bytes() != value for path, value in raw.items()):
        raise ValueError("Accounting refresh input changed during preparation")
    output_directory.mkdir(parents=True)
    evidence_path = output_directory / "evidence.json"
    prepared_evidence = {
        "schema_version": "production-nonactor-refresh-v1", "observed_at": observed_at,
        "source_url": observation.get("source_url"), "daily_control": observation["daily_control"],
        "category_floors": {date: {key: str(amount) for key, amount in services.items()}
                            for date, services in floors.items()},
        "nonactor_positive_deltas": deltas, "nonactor_increment_usd": str(increment),
        "prior_conservative_overhead_floor_usd": old_entry["settled_usd"],
        "new_conservative_overhead_floor_usd": str(money(old_entry["settled_usd"]) + increment),
        "actor_observation": {"provider_actor_category_total_usd": str(actor_control),
            "known_legacy_actor_run_usd": str(legacy_actor),
            "known_production_bound_actor_usd": str(production_actor),
            "provider_minus_known_actor_run_usd": str(actor_control - legacy_actor - production_actor),
            "ledger_addition_usd": "0", "status": "asynchronous actor control diagnostic; not an extra charge"},
        "input_hashes": {str(path): hashlib.sha256(value).hexdigest() for path, value in raw.items()},
        "method": "Only positive nonactor category increments; existing floors/reserves unchanged; actor lag journaled separately."}
    evidence_bytes = canonical(prepared_evidence) + b"\n"
    evidence_path.write_bytes(evidence_bytes)
    prepared = {key: copy.deepcopy(accounting[key]) for key in
                ("schema_version", "scope", "complete", "observed_at", "period_start", "period_end", "entries")}
    prepared["observed_at"] = observed_at
    entry = next(entry for entry in prepared["entries"] if entry["id"] == OVERHEAD_ID)
    entry["settled_usd"] = prepared_evidence["new_conservative_overhead_floor_usd"]
    entry["evidence"] = {**copy.deepcopy(evidence), "refresh_path": str(evidence_path),
        "refresh_sha256": hashlib.sha256(evidence_bytes).hexdigest(), "observed_at": observed_at,
        "basis": prepared_evidence["method"], "nonactor_increment_usd": str(increment),
        "retained_prior_control_floor_usd": old_entry["settled_usd"], "unresolved_reserve_retained": True}
    snapshot_path = output_directory / "accounting.json"
    snapshot_path.write_bytes(canonical(prepared) + b"\n")
    return {"accounting": str(snapshot_path), "accounting_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
            "evidence": str(evidence_path), "evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
            "nonactor_increment_usd": str(increment), "shared_writes": False}


def prepare_accounting_refresh(ledger_path: Path, baseline_path: Path,
                               observation_path: Path, output_directory: Path) -> dict:
    """Prepare only new artifacts using the same exact precision as the locked ledger."""
    with localcontext() as context:
        context.prec = 80
        return _prepare_accounting_refresh(ledger_path, baseline_path, observation_path, output_directory)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("ledger", "baseline", "observation", "output-directory"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare_accounting_refresh(args.ledger, args.baseline, args.observation, args.output_directory)))


if __name__ == "__main__":
    main()
