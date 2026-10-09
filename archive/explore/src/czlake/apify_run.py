"""Ledger-guarded Apify runs. Every run sets maxTotalChargeUsd and is recorded in data/ledger.csv.

Hard cap: committed spend (finished runs' usageTotalUsd + in-flight reservations at their
maxTotalChargeUsd) never exceeds CAP_USD. Concurrent callers serialise through a file lock.
The token comes from the APIFY_TOKEN environment variable and is never printed or stored.
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import math
import os
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .land import manifest_append, now_iso
from .paths import DATA, LEDGER, RAW

CAP_USD = min(20.0, float(os.environ.get("CZLAKE_APIFY_CAP_USD", "20")))
ACTIVE = {"READY", "RUNNING", "TIMING-OUT", "ABORTING"}
TERMINAL = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}
STATE = DATA / "ledger_state.json"
LOCK = DATA / ".ledger.lock"
API = "https://api.apify.com/v2"
FIELDS = ["time", "finished_at", "actor", "purpose", "run_id", "status", "max_total_charge_usd",
          "usage_total_usd", "running_total_usd", "items", "dataset_id", "raw_path"]


def _h() -> dict:
    return {"Authorization": f"Bearer {os.environ['APIFY_TOKEN']}"}


@contextmanager
def _locked():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"reservations": {}}


def _save_state(s: dict) -> None:
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(s, indent=1))
    temporary.replace(STATE)


def ledger_rows() -> list[dict]:
    if not LEDGER.exists():
        return []
    with LEDGER.open() as f:
        return list(csv.DictReader(f))


def spent_usd() -> float:
    return sum(float(r["usage_total_usd"] or 0) for r in ledger_rows())


def committed_usd() -> float:
    s = _state()
    return spent_usd() + sum(v["max"] for v in s["reservations"].values())


def _rewrite_ledger(rows: list[dict]) -> None:
    """Replace the ledger atomically and recalculate cumulative actual charges."""
    total = 0.0
    temporary = LEDGER.with_suffix(".tmp")
    with temporary.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            total += float(row["usage_total_usd"] or 0)
            row["running_total_usd"] = round(total, 6)
            writer.writerow(row)
    temporary.replace(LEDGER)


def reconcile() -> dict:
    """Refresh owned runs; retain the full cap while active or billing is settling.

    Apify can post the last result's charge after terminal status. Keep that
    run's unspent cap reserved for five minutes. Failed reads leave reservations
    intact and fail closed: callers must reconcile successfully before launching.
    """
    with _locked():
        rows, state = ledger_rows(), _state()
        by_id = {row["run_id"]: row for row in rows if row["run_id"]}
        for reservation in state["reservations"].values():
            rid = reservation.get("run_id")
            if rid and rid not in by_id:
                row: dict = {field: "" for field in FIELDS}
                row.update(time=reservation["time"], actor=reservation["actor"], purpose=reservation["purpose"],
                           run_id=rid, status="READY", max_total_charge_usd=reservation["max"], usage_total_usd=0)
                rows.append(row)
                by_id[rid] = row
        with httpx.Client(headers=_h(), timeout=30) as client:
            for rid, row in by_id.items():
                response = client.get(f"{API}/actor-runs/{rid}")
                response.raise_for_status()
                run = response.json()["data"]
                usage = float(run.get("usageTotalUsd") or 0)
                row.update(status=run["status"], usage_total_usd=round(usage, 6),
                           finished_at=run.get("finishedAt") or "", dataset_id=run.get("defaultDatasetId") or "")
                maximum = float(row["max_total_charge_usd"])
                finished = run.get("finishedAt")
                settling = finished and (datetime.now(UTC) - datetime.fromisoformat(finished)).total_seconds() < 300
                keys = [key for key, value in state["reservations"].items() if value.get("run_id") == rid]
                for key in keys:
                    del state["reservations"][key]
                if run["status"] not in TERMINAL or settling:
                    state["reservations"][rid] = {"max": max(0.0, maximum - usage), "run_id": rid,
                        "actor": row["actor"], "purpose": row["purpose"], "time": row["time"],
                        "kind": "active" if run["status"] not in TERMINAL else "billing_settlement"}
        _rewrite_ledger(rows)
        _save_state(state)
        return {"cap_usd": CAP_USD, "spent_usd": round(spent_usd(), 6),
                "reserved_usd": round(sum(v["max"] for v in state["reservations"].values()), 6),
                "committed_usd": round(committed_usd(), 6), "runs": len(rows),
                "active_runs": [row["run_id"] for row in rows if row["status"] not in TERMINAL]}


class CapExceeded(RuntimeError):
    pass


def input_digest(run_input: dict) -> str:
    return hashlib.sha256(json.dumps(run_input, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _authorization(path: Path | None, actor: str, run_input: dict, max_usd: float, purpose: str) -> dict | None:
    if path is None:
        return None
    if path.resolve().parent != (DATA / "authorizations").resolve():
        raise ValueError("Authorization must be recorded in the local authorization directory")
    auth = json.loads(path.read_text())
    if (auth.get("status") != "authorized_prepared" or auth.get("authorized_by") != "Daniel"
            or auth.get("actor") != actor or auth.get("input_sha256") != input_digest(run_input)
            or float(auth.get("max_total_charge_usd", 0)) != max_usd or auth.get("purpose") != purpose
            or not auth.get("supersedes_hold_for_exact_input_only") or not auth.get("authorization_id")):
        raise ValueError("Actor, exact input, purpose or cap does not match the recorded authorization")
    return auth


def _check_hold(auth: dict | None) -> None:
    hold_path = DATA / "paid_launch_hold.json"
    if not hold_path.exists():
        return
    hold = json.loads(hold_path.read_text())
    if auth is None:
        raise RuntimeError("Paid launches held: " + hold["reason"])
    updated = hold.get("updated_at") or hold.get("held_at")
    if updated and datetime.fromisoformat(updated) > datetime.fromisoformat(auth["authorized_at"]):
        raise RuntimeError("A newer paid-launch hold supersedes this authorization")


def run_actor(actor: str, run_input: dict, max_usd: float, purpose: str, *, memory_mb: int = 1024,
              timeout_s: int = 900, landing: str | None = None, poll_s: float = 5.0,
              item_limit: int | None = None, authorization_path: Path | None = None) -> dict:
    """Start an Actor with maxTotalChargeUsd, wait, land its dataset in raw/, write the ledger row."""
    if not math.isfinite(max_usd) or max_usd <= 0:
        raise ValueError("A finite positive run cap is required")
    auth = _authorization(authorization_path, actor, run_input, max_usd, purpose)
    _check_hold(auth)
    reconcile()
    actor_path = actor.replace("/", "~")
    key = f"pending-{os.getpid()}-{time.time_ns()}"
    with _locked():
        s = _state()
        if auth and auth["authorization_id"] in s.get("authorizations", {}):
            raise RuntimeError("Authorization already attempted; recover its existing run without relaunching")
        if committed_usd() + max_usd > CAP_USD + 1e-9:
            raise CapExceeded(f"cap {CAP_USD} would be exceeded: committed {committed_usd():.4f} + {max_usd}")
        s["reservations"][key] = {"max": max_usd, "actor": actor, "purpose": purpose, "time": now_iso()}
        if auth:
            s.setdefault("authorizations", {})[auth["authorization_id"]] = {
                "reservation_key": key, "actor": actor, "purpose": purpose, "time": now_iso(),
                "input_sha256": input_digest(run_input), "max": max_usd, "authorization_path": str(authorization_path)}
        _save_state(s)
    started = now_iso()
    run: dict = {}
    run_id, status, usage, ds, items, raw_path = "", "FAILED_TO_START", 0.0, "", 0, ""
    try:
        try:
            if _authorization(authorization_path, actor, run_input, max_usd, purpose) != auth:
                raise ValueError("Authorization changed after reservation")
            _check_hold(auth)
        except (RuntimeError, ValueError):
            status = "REJECTED_BEFORE_START"
            raise
        params = {"maxTotalChargeUsd": max_usd, "memory": memory_mb, "timeout": timeout_s}
        if item_limit:
            params["maxItems"] = item_limit
        r = httpx.post(f"{API}/acts/{actor_path}/runs", params=params, json=run_input, headers=_h(), timeout=60)
        if r.status_code >= 400:
            # A 5xx response or request timeout can occur after the server starts
            # the Actor. Only explicit client rejection safely frees the cap.
            if 400 <= r.status_code < 500 and r.status_code != 408:
                status = "REJECTED_BEFORE_START"
            raise RuntimeError(f"Apify start failed {r.status_code}")
        run = r.json()["data"]
        run_id = run["id"]
        with _locked():
            s = _state()
            s["reservations"][key]["run_id"] = run_id
            if auth:
                s["authorizations"][auth["authorization_id"]]["run_id"] = run_id
            _save_state(s)
        while run["status"] in ACTIVE:
            time.sleep(poll_s)
            response = httpx.get(f"{API}/actor-runs/{run_id}", headers=_h(), timeout=60)
            response.raise_for_status()
            run = response.json()["data"]
        status = run["status"]
        usage = float(run.get("usageTotalUsd") or 0.0)
        ds = run.get("defaultDatasetId") or ""
        data = []
        if ds:
            offset = 0
            while True:
                response = httpx.get(f"{API}/datasets/{ds}/items", params={"offset": offset, "limit": 1000, "clean": "true"},
                                     headers=_h(), timeout=120)
                response.raise_for_status()
                page = response.json()
                if not page:
                    break
                data.extend(page)
                offset += len(page)
                if len(page) < 1000:
                    break
        items = len(data)
        land_dir = RAW / "apify" / (landing or actor_path)
        land_dir.mkdir(parents=True, exist_ok=True)
        p = land_dir / f"{run_id}.json"
        fetched = now_iso()
        p.write_text(json.dumps({"run_id": run_id, "actor": actor, "purpose": purpose, "input": run_input,
                                 "status": status, "usage_total_usd": usage, "fetched_at": fetched,
                                 "dataset_id": ds, "items": data}, ensure_ascii=False))
        raw_path = str(p)
        manifest_append({"source": f"apify/{actor}", "source_url": f"{API}/datasets/{ds}/items",
                         "final_url": f"https://console.apify.com/view/runs/{run_id}", "fetched_at": fetched,
                         "path": raw_path, "bytes": p.stat().st_size, "sha256": None,
                         "content_type": "application/json", "apify_run_id": run_id})
        return {"run_id": run_id, "status": status, "usage_total_usd": usage, "items": data, "raw_path": raw_path}
    finally:
        with _locked():
            if run_id and status in ACTIVE | {"FAILED_TO_START"}:
                try:
                    response = httpx.get(f"{API}/actor-runs/{run_id}", headers=_h(), timeout=60)
                    response.raise_for_status()
                    run = response.json()["data"]
                    status, usage = run["status"], float(run.get("usageTotalUsd") or 0)
                except (httpx.HTTPError, KeyError, ValueError):
                    status = "UNKNOWN"
            if run_id:
                rows = ledger_rows()
                rows = [row for row in rows if row["run_id"] != run_id]
                rows.append({"time": started, "finished_at": run.get("finishedAt") or "", "actor": actor, "purpose": purpose,
                                "run_id": run_id, "status": status, "max_total_charge_usd": max_usd,
                                "usage_total_usd": round(usage, 6), "running_total_usd": "",
                                "items": items, "dataset_id": ds, "raw_path": raw_path})
                _rewrite_ledger(rows)
            s = _state()
            if auth:
                s["authorizations"][auth["authorization_id"]].update(run_id=run_id, status=status)
            if run_id:
                s["reservations"].pop(key, None)
                s["reservations"][run_id] = {"max": max(0, max_usd - usage), "run_id": run_id,
                    "actor": actor, "purpose": purpose, "time": started,
                    "kind": "active" if status in ACTIVE | {"UNKNOWN"} else "billing_settlement"}
            elif status == "REJECTED_BEFORE_START":
                s["reservations"].pop(key, None)
            # A network timeout during POST is ambiguous: retain the pending cap.
            _save_state(s)


def recover_authorized_start(authorization_path: Path) -> dict:
    """Resolve an uncertain POST using matching remote INPUT; never replay it."""
    auth = json.loads(authorization_path.read_text())
    inp = json.loads(Path(auth["input_path"]).read_text())
    _authorization(authorization_path, auth["actor"], inp, float(auth["max_total_charge_usd"]), auth["purpose"])
    with _locked():
        attempt = _state().get("authorizations", {}).get(auth["authorization_id"])
    if not attempt:
        raise RuntimeError("No recorded attempt to recover")
    run_id = attempt.get("run_id")
    if not run_id:
        matches = []
        with httpx.Client(headers=_h(), timeout=60) as client:
            response = client.get(f"{API}/acts/{auth['actor'].replace('/', '~')}/runs", params={"desc": "true", "limit": 100})
            response.raise_for_status()
            for run in response.json()["data"]["items"]:
                if datetime.fromisoformat(run["startedAt"]) < datetime.fromisoformat(attempt["time"]):
                    continue
                response = client.get(f"{API}/key-value-stores/{run['defaultKeyValueStoreId']}/records/INPUT")
                response.raise_for_status()
                if input_digest(response.json()) == attempt["input_sha256"]:
                    matches.append(run)
        if len(matches) != 1:
            raise RuntimeError(f"Uncertain launch has {len(matches)} exact matches; reservation retained, no retry")
        run_id = matches[0]["id"]
        with _locked():
            state = _state()
            state["authorizations"][auth["authorization_id"]]["run_id"] = run_id
            state["reservations"][attempt["reservation_key"]]["run_id"] = run_id
            _save_state(state)
    reconciliation = reconcile()
    from .build.recover_runs import recover
    return {"reconciliation": reconciliation, "recovered": recover(run_id)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Run an Apify Actor under the ledger cap")
    ap.add_argument("actor")
    ap.add_argument("--input", required=True, help="JSON file with the Actor input")
    ap.add_argument("--max-usd", type=float, required=True)
    ap.add_argument("--purpose", required=True)
    ap.add_argument("--landing")
    ap.add_argument("--memory", type=int, default=1024)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--authorization", type=Path)
    a = ap.parse_args()
    inp = json.loads(Path(a.input).read_text())
    res = run_actor(a.actor, inp, a.max_usd, a.purpose, memory_mb=a.memory, timeout_s=a.timeout, landing=a.landing,
                    authorization_path=a.authorization)
    print(json.dumps({k: v for k, v in res.items() if k != "items"} | {"n_items": len(res["items"])}))


if __name__ == "__main__":
    if sys.argv[1:2] == ["reconcile"]:
        print(json.dumps(reconcile()))
    elif sys.argv[1:2] == ["status"]:
        print(json.dumps({"cap_usd": CAP_USD, "spent_usd": round(spent_usd(), 4),
                          "committed_usd": round(committed_usd(), 4), "runs": len(ledger_rows())}))
    else:
        main()
