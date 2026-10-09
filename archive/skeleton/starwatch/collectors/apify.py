"""Run one Apify Actor and hand its dataset items over while the run is still going.

S1 fills each lane as items arrive, so instead of waiting for the run to finish this polls the
run's default dataset every couple of seconds and passes only the new items to `on_items`.
The token travels in the Authorization header, never in a URL that could reach a log or the screen.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from .actors import ActorSpec

API = "https://api.apify.com/v2"
TERMINAL = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}

OnItems = Callable[[list[dict[str, Any]]], Awaitable[None]]


class ApifyRunFailed(RuntimeError):
    pass


@dataclass
class ActorRunResult:
    run_id: str
    status: str
    dataset_id: str
    item_count: int
    usage_usd: float
    console_url: str


async def run_actor(
    spec: ActorSpec,
    run_input: dict[str, Any],
    *,
    token: str,
    on_items: OnItems,
    poll_s: float = 2.0,
    client: httpx.AsyncClient | None = None,
) -> ActorRunResult:
    """Start `spec.actor_id` with `spec.base_input` + `run_input`, stream new items, return usage.

    Raises ApifyRunFailed when the run ends FAILED, ABORTED or TIMED-OUT; items that arrived before
    that have already been passed to `on_items`.
    """
    owns_client = client is None
    client = client or httpx.AsyncClient(base_url=API, timeout=30)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        start = await client.post(
            f"/acts/{spec.actor_id.replace('/', '~')}/runs",
            params={
                "maxItems": spec.max_items,
                "maxTotalChargeUsd": spec.max_charge_usd,
                "timeout": spec.timeout_s,
            },
            json={**spec.base_input, **run_input},
            headers=headers,
        )
        start.raise_for_status()
        run = start.json()["data"]
        run_id, dataset_id = run["id"], run["defaultDatasetId"]

        offset = 0
        deadline = asyncio.get_running_loop().time() + spec.timeout_s + 60
        while True:
            # Read status before items: once a terminal status is seen, one more read drains the rest.
            status_response = await client.get(f"/actor-runs/{run_id}", headers=headers)
            status_response.raise_for_status()
            run = status_response.json()["data"]
            items_response = await client.get(
                f"/datasets/{dataset_id}/items",
                params={"offset": offset, "limit": 100, "clean": "true", "format": "json"},
                headers=headers,
            )
            items_response.raise_for_status()
            new_items = items_response.json()[: max(spec.max_items - offset, 0)]
            if new_items:
                offset += len(new_items)
                await on_items(new_items)
            if run["status"] in TERMINAL or offset >= spec.max_items:
                break
            if asyncio.get_running_loop().time() > deadline:
                await client.post(f"/actor-runs/{run_id}/abort", headers=headers)
                raise ApifyRunFailed(f"{spec.actor_id} did not finish in {spec.timeout_s} s")
            await asyncio.sleep(poll_s)

        if run["status"] not in TERMINAL:
            # The cap was reached while the Actor kept going: stop paying for more.
            await client.post(f"/actor-runs/{run_id}/abort", headers=headers)
            run["status"] = "ABORTED (cap reached)"
        elif run["status"] != "SUCCEEDED" and offset == 0:
            raise ApifyRunFailed(f"{spec.actor_id} ended {run['status']}")

        return ActorRunResult(
            run_id=run_id,
            status=run["status"],
            dataset_id=dataset_id,
            item_count=offset,
            usage_usd=float(run.get("usageTotalUsd") or 0.0),
            console_url=f"https://console.apify.com/view/runs/{run_id}",
        )
    finally:
        if owns_client:
            await client.aclose()
