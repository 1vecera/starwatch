"""Run one Apify Actor and hand its dataset items over while the run is still going.

S1 fills each lane as items arrive, so instead of waiting for the run to finish this polls the
run's default dataset every couple of seconds and passes only the new items to `on_items`.
The token travels in the Authorization header, never in a URL that could reach a log or the screen.

On stage a lane must never freeze: a poll that fails is retried, a run that outlives its timeout is
aborted and keeps the items it already delivered, and a cancelled run (server stopping) is aborted
so Apify stops charging. Cost is read from the run itself: `usageTotalUsd`, settled for a few
seconds after the run ends because Apify updates it with a lag, and never below the run's charged
pay-per-event count times its event prices.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from .actors import ActorSpec

API = "https://api.apify.com/v2"
TERMINAL = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}
POLL_FAILURES_ALLOWED = 5

log = logging.getLogger("starwatch.apify")

OnItems = Callable[[list[dict[str, Any]]], Awaitable[None]]


class StopRun(Exception):
    """Raised by `on_items` to stop the run now (for example: the account is not the subject's)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ApifyRunFailed(RuntimeError):
    """The run ended without items. Carries what the run cost so it still lands in the run costs."""

    def __init__(self, message: str, *, run_id: str = "", usage_usd: float = 0.0, status: str = ""):
        super().__init__(message)
        self.run_id = run_id
        self.usage_usd = usage_usd
        self.status = status


@dataclass
class ActorRunResult:
    run_id: str
    status: str
    dataset_id: str
    item_count: int
    usage_usd: float
    console_url: str
    usage_total_usd: float = 0.0  # as Apify reported it
    charged_usd: float = 0.0  # charged events times their prices (pay-per-event Actors)
    status_message: str = ""
    duration_s: float = 0.0


def charged_usd(run: dict[str, Any]) -> float:
    """Charged pay-per-event events times their prices, from the run object itself."""
    events = ((run.get("pricingInfo") or {}).get("pricingPerEvent") or {}).get("actorChargeEvents") or {}
    counts = run.get("chargedEventCounts") or {}
    total = 0.0
    for name, count in counts.items():
        price = (events.get(name) or {}).get("eventPriceUsd") or 0.0
        total += float(count or 0) * float(price)
    return round(total, 6)


def run_cost(run: dict[str, Any]) -> float:
    return round(max(float(run.get("usageTotalUsd") or 0.0), charged_usd(run)), 6)


async def _request(client: httpx.AsyncClient, method: str, url: str, *, attempts: int = 3, **kwargs):
    """One API call with a short retry on network errors, 429 and 5xx."""
    for attempt in range(attempts):
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.HTTPStatusError("retryable", request=response.request, response=response)
            return response
        except (httpx.TransportError, httpx.HTTPStatusError):
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(0.8 * (attempt + 1))
    raise AssertionError("unreachable")


async def run_actor(
    spec: ActorSpec,
    run_input: dict[str, Any],
    *,
    token: str,
    on_items: OnItems,
    poll_s: float = 2.0,
    settle_s: float = 6.0,
    client: httpx.AsyncClient | None = None,
) -> ActorRunResult:
    """Start `spec.actor_id` with `spec.base_input` + `run_input`, stream new items, return usage.

    Raises ApifyRunFailed when the run ends FAILED, ABORTED or TIMED-OUT without items; items that
    arrived before that have already been passed to `on_items`. A run that ends badly after items
    arrived, or that Starwatch stops at its timeout, returns normally with what it delivered.
    """
    owns_client = client is None
    client = client or httpx.AsyncClient(base_url=API, timeout=30)
    headers = {"Authorization": f"Bearer {token}"}
    loop = asyncio.get_running_loop()
    began = loop.time()
    run_id = ""
    finished = False
    try:
        params: dict[str, Any] = {
            "maxItems": spec.max_items,
            "maxTotalChargeUsd": spec.max_charge_usd,
            "timeout": spec.timeout_s,
        }
        if spec.memory_mb:
            params["memory"] = spec.memory_mb
        start = await _request(
            client,
            "POST",
            f"/acts/{spec.actor_id.replace('/', '~')}/runs",
            params=params,
            json={**spec.base_input, **run_input},
            headers=headers,
        )
        if start.status_code >= 400:
            detail = ""
            try:
                detail = start.json().get("error", {}).get("message", "")
            except ValueError:
                pass
            raise ApifyRunFailed(f"{spec.actor_id} did not start: HTTP {start.status_code} {detail}".strip())
        run = start.json()["data"]
        run_id, dataset_id = run["id"], run["defaultDatasetId"]

        item_params: dict[str, Any] = {"limit": 100, "clean": "true", "format": "json"}
        if spec.fields:
            item_params["fields"] = ",".join(spec.fields)

        offset = 0
        last_new = loop.time()
        failures = 0
        stopped_by_us = ""
        deadline = began + spec.timeout_s + 30
        while True:
            try:
                # Read status before items: once a terminal status is seen, one more read drains the rest.
                status_response = await _request(client, "GET", f"/actor-runs/{run_id}", headers=headers)
                status_response.raise_for_status()
                run = status_response.json()["data"]
                items_response = await _request(
                    client,
                    "GET",
                    f"/datasets/{dataset_id}/items",
                    params={**item_params, "offset": offset},
                    headers=headers,
                )
                items_response.raise_for_status()
                failures = 0
            except (httpx.HTTPError, ValueError) as error:
                failures += 1
                log.warning("%s poll failed (%s/%s): %s", spec.actor_id, failures, POLL_FAILURES_ALLOWED, error)
                if failures >= POLL_FAILURES_ALLOWED:
                    stopped_by_us = "polling failed"
                    break
                await asyncio.sleep(poll_s)
                continue
            new_items = [i for i in items_response.json() if isinstance(i, dict)]
            new_items = new_items[: max(spec.max_items - offset, 0)]
            if new_items:
                last_new = loop.time()
                offset += len(new_items)
                try:
                    await on_items(new_items)
                except StopRun as stop:
                    stopped_by_us = stop.reason
                    break
            if run["status"] in TERMINAL:
                break
            if offset >= spec.max_items and spec.abort_at_cap:
                stopped_by_us = "cap reached"
                break
            if loop.time() > deadline:
                stopped_by_us = f"stopped after {spec.timeout_s} s"
                break
            if spec.idle_stop_s and offset and loop.time() - last_new > spec.idle_stop_s:
                stopped_by_us = f"no new results for {spec.idle_stop_s:.0f} s"
                break
            await asyncio.sleep(poll_s)

        if run.get("status") not in TERMINAL:
            # Stop paying for more: the cap was reached, time ran out or polling broke.
            await _abort(client, run_id, headers)
            run["status"] = f"ABORTED ({stopped_by_us})"
        finished = True

        run = await _settled(client, run_id, headers, run, settle_s, offset) if settle_s else run
        status = run.get("status", "")
        if stopped_by_us and not status.startswith("ABORTED ("):
            status = f"{status} ({stopped_by_us})"
        cost = run_cost(run)
        if not str(status).startswith("SUCCEEDED") and offset == 0:
            raise ApifyRunFailed(
                f"{spec.actor_id} ended {status}: {run.get('statusMessage') or 'no items'}",
                run_id=run_id,
                usage_usd=cost,
                status=status,
            )
        return ActorRunResult(
            run_id=run_id,
            status=status,
            dataset_id=dataset_id,
            item_count=offset,
            usage_usd=cost,
            console_url=f"https://console.apify.com/view/runs/{run_id}",
            usage_total_usd=float(run.get("usageTotalUsd") or 0.0),
            charged_usd=charged_usd(run),
            status_message=str(run.get("statusMessage") or ""),
            duration_s=round(loop.time() - began, 1),
        )
    except asyncio.CancelledError:
        if run_id and not finished:
            # The server is stopping mid-run: abort so the Actor stops charging.
            try:
                await asyncio.shield(_abort(client, run_id, headers))
            except Exception:  # noqa: BLE001 - best effort on the way out
                pass
        raise
    finally:
        if owns_client:
            await client.aclose()


async def _abort(client: httpx.AsyncClient, run_id: str, headers: dict[str, str]) -> None:
    try:
        await _request(client, "POST", f"/actor-runs/{run_id}/abort", headers=headers, attempts=2)
    except httpx.HTTPError as error:
        log.warning("abort of %s failed: %s", run_id, error)


def is_settled(run: dict[str, Any], items: int = 0) -> bool:
    """Apify charges with a lag: a run counts as settled once it is terminal, its usage covers its
    charged events and, for a pay-per-event Actor that delivered items, more than its start fee is
    charged. The `SettleCosts` step re-reads every run once more after collection."""
    if run.get("status") not in TERMINAL:
        return False
    usage = float(run.get("usageTotalUsd") or 0.0)
    if usage <= 0 or usage + 1e-9 < charged_usd(run):
        return False
    if items and (run.get("pricingInfo") or {}).get("pricingModel") == "PAY_PER_EVENT":
        counts = run.get("chargedEventCounts") or {}
        return any(int(v or 0) for k, v in counts.items() if "start" not in k)
    return True


async def _settled(
    client: httpx.AsyncClient, run_id: str, headers: dict[str, str], run: dict[str, Any], settle_s: float,
    items: int = 0,
) -> dict[str, Any]:
    """Re-read the run until Apify's usage stops lagging behind what it delivered (bounded)."""
    loop = asyncio.get_running_loop()
    until = loop.time() + settle_s
    latest = run
    while True:
        try:
            response = await _request(client, "GET", f"/actor-runs/{run_id}", headers=headers, attempts=2)
            response.raise_for_status()
            latest = response.json()["data"]
        except (httpx.HTTPError, ValueError):
            return latest
        if is_settled(latest, items):
            return latest
        if loop.time() >= until:
            return latest
        await asyncio.sleep(1.5)
