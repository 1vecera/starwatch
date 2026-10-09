"""Ledger-guarded Apify runs. Every run sets maxTotalChargeUsd and is recorded in data/ledger.csv.

Hard cap: committed spend (finished runs' usageTotalUsd + in-flight reservations at their
maxTotalChargeUsd) never exceeds CAP_USD. Concurrent callers serialise through a file lock.
The token comes from the APIFY_TOKEN environment variable and is never printed or stored.
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx

from .land import manifest_append, now_iso
from .paths import DATA, LEDGER, RAW

CAP_USD = float(os.environ.get("CZLAKE_APIFY_CAP_USD", "20"))
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
    STATE.write_text(json.dumps(s, indent=1))


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


def _append_ledger(row: dict) -> None:
    new = not LEDGER.exists()
    with LEDGER.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


class CapExceeded(RuntimeError):
    pass


def run_actor(actor: str, run_input: dict, max_usd: float, purpose: str, *, memory_mb: int = 1024,
              timeout_s: int = 900, landing: str | None = None, poll_s: float = 5.0,
              item_limit: int | None = None) -> dict:
    """Start an Actor with maxTotalChargeUsd, wait, land its dataset in raw/, write the ledger row."""
    actor_path = actor.replace("/", "~")
    key = f"pending-{os.getpid()}-{time.time_ns()}"
    with _locked():
        if committed_usd() + max_usd > CAP_USD + 1e-9:
            raise CapExceeded(f"cap {CAP_USD} would be exceeded: committed {committed_usd():.4f} + {max_usd}")
        s = _state()
        s["reservations"][key] = {"max": max_usd, "actor": actor, "purpose": purpose, "time": now_iso()}
        _save_state(s)
    started = now_iso()
    run_id, status, usage, ds, items, raw_path = "", "FAILED_TO_START", 0.0, "", 0, ""
    try:
        params = {"maxTotalChargeUsd": max_usd, "memory": memory_mb, "timeout": timeout_s}
        if item_limit:
            params["maxItems"] = item_limit
        r = httpx.post(f"{API}/acts/{actor_path}/runs", params=params, json=run_input, headers=_h(), timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"Apify start failed {r.status_code}: {r.text[:500]}")
        run = r.json()["data"]
        run_id = run["id"]
        with _locked():
            s = _state()
            s["reservations"][key]["run_id"] = run_id
            _save_state(s)
        while run["status"] in ("READY", "RUNNING", "TIMING-OUT", "ABORTING"):
            time.sleep(poll_s)
            run = httpx.get(f"{API}/actor-runs/{run_id}", headers=_h(), timeout=60).json()["data"]
        status = run["status"]
        usage = float(run.get("usageTotalUsd") or 0.0)
        ds = run.get("defaultDatasetId") or ""
        data = []
        if ds:
            offset = 0
            while True:
                page = httpx.get(f"{API}/datasets/{ds}/items", params={"offset": offset, "limit": 1000, "clean": "true"},
                                 headers=_h(), timeout=120).json()
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
            if run_id and status in ("READY", "RUNNING", "FAILED_TO_START"):
                # we were interrupted while the run may still be going: record max as provisional usage
                try:
                    run = httpx.get(f"{API}/actor-runs/{run_id}", headers=_h(), timeout=60).json()["data"]
                    status, usage = run["status"], float(run.get("usageTotalUsd") or max_usd)
                except Exception:
                    usage = max_usd
            if run_id or status != "FAILED_TO_START":
                total = spent_usd() + usage
                _append_ledger({"time": started, "finished_at": now_iso(), "actor": actor, "purpose": purpose,
                                "run_id": run_id, "status": status, "max_total_charge_usd": max_usd,
                                "usage_total_usd": round(usage, 6), "running_total_usd": round(total, 6),
                                "items": items, "dataset_id": ds, "raw_path": raw_path})
            s = _state()
            s["reservations"].pop(key, None)
            _save_state(s)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run an Apify Actor under the ledger cap")
    ap.add_argument("actor")
    ap.add_argument("--input", required=True, help="JSON file with the Actor input")
    ap.add_argument("--max-usd", type=float, required=True)
    ap.add_argument("--purpose", required=True)
    ap.add_argument("--landing")
    ap.add_argument("--memory", type=int, default=1024)
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()
    inp = json.loads(Path(a.input).read_text())
    res = run_actor(a.actor, inp, a.max_usd, a.purpose, memory_mb=a.memory, timeout_s=a.timeout, landing=a.landing)
    print(json.dumps({k: v for k, v in res.items() if k != "items"} | {"n_items": len(res["items"])}))


if __name__ == "__main__":
    if sys.argv[1:2] == ["status"]:
        print(json.dumps({"cap_usd": CAP_USD, "spent_usd": round(spent_usd(), 4),
                          "committed_usd": round(committed_usd(), 4), "runs": len(ledger_rows())}))
    else:
        main()
