"""Recover owned terminal datasets with authenticated GETs; never start an Actor."""
from __future__ import annotations

import argparse
import hashlib
import json

import httpx

from .. import apify_run
from ..land import manifest_append, now_iso
from ..paths import RAW
from .discover_local import stage


def recover(run_id: str) -> dict:
    rows = apify_run.ledger_rows()
    row = next(row for row in rows if row["run_id"] == run_id)
    purpose = row["purpose"]
    with httpx.Client(headers=apify_run._h(), timeout=60) as client:
        response = client.get(f"{apify_run.API}/actor-runs/{run_id}")
        response.raise_for_status()
        run = response.json()["data"]
        if run["status"] in apify_run.ACTIVE:
            return {"run_id": run_id, "status": run["status"], "still_running": True}
        response = client.get(f"{apify_run.API}/key-value-stores/{run['defaultKeyValueStoreId']}/records/INPUT")
        response.raise_for_status()
        inp = response.json()
        items = []
        while True:
            response = client.get(f"{apify_run.API}/datasets/{run['defaultDatasetId']}/items",
                                  params={"offset": len(items), "limit": 1000, "clean": "true"})
            response.raise_for_status()
            page = response.json()
            items.extend(page)
            if len(page) < 1000:
                break
    path = RAW / "apify" / "recovered" / f"{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps({"run_id": run_id, "actor": row["actor"], "purpose": row["purpose"],
            "input": inp, "status": run["status"], "usage_total_usd": run["usageTotalUsd"],
            "dataset_id": run["defaultDatasetId"], "fetched_at": now_iso(), "items": items}, ensure_ascii=False))
        manifest_append({"source": "apify_recovery", "source_url": f"{apify_run.API}/datasets/{run['defaultDatasetId']}/items",
            "apify_run_id": run_id, "fetched_at": now_iso(), "path": str(path), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    with apify_run._locked():
        rows = apify_run.ledger_rows()
        for row in rows:
            if row["run_id"] == run_id:
                row.update(items=len(items), raw_path=str(path), dataset_id=run["defaultDatasetId"],
                           status=run["status"], usage_total_usd=run["usageTotalUsd"], finished_at=run["finishedAt"])
        apify_run._rewrite_ledger(rows)
    result = {"run_id": run_id, "status": run["status"], "items": len(items), "usage_total_usd": run["usageTotalUsd"]}
    if "mapping " in purpose:
        mapping_path = RAW / "discovery_mappings" / purpose.split("mapping ", 1)[1]
        result["staging"] = stage(path, json.loads(mapping_path.read_text()))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_ids", nargs="+")
    arguments = parser.parse_args()
    print(json.dumps(apify_run.reconcile()), flush=True)
    for run_id in arguments.run_ids:
        print(json.dumps(recover(run_id)), flush=True)
