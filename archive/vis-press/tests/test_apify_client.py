"""run_actor streams dataset items while the Actor runs and enforces the item cap."""

import asyncio

import httpx

from starwatch.collectors.actors import ActorSpec
from starwatch.collectors.apify import API, run_actor


def test_items_arrive_while_running_and_cap_aborts():
    dataset = [{"n": i} for i in range(7)]
    polls = {"status": 0}
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.headers["authorization"] == "Bearer secret"
        assert "secret" not in str(request.url)
        if request.method == "POST" and request.url.path.endswith("/runs"):
            assert request.url.path == "/v2/acts/someone~actor/runs"
            assert request.url.params["maxItems"] == "5"
            return httpx.Response(201, json={"data": {"id": "r1", "defaultDatasetId": "d1"}})
        if request.url.path == "/v2/actor-runs/r1":
            polls["status"] += 1
            return httpx.Response(200, json={"data": {"status": "RUNNING", "usageTotalUsd": 0.012}})
        if request.url.path == "/v2/datasets/d1/items":
            offset = int(request.url.params["offset"])
            visible = dataset[: 3 * polls["status"]]  # three more items appear per poll
            return httpx.Response(200, json=visible[offset:])
        if request.url.path == "/v2/actor-runs/r1/abort":
            return httpx.Response(200, json={"data": {"status": "ABORTING"}})
        return httpx.Response(404)

    batches = []

    async def on_items(items):
        batches.append([i["n"] for i in items])

    async def go():
        async with httpx.AsyncClient(base_url=API, transport=httpx.MockTransport(handler)) as client:
            return await run_actor(
                ActorSpec("x", "someone/actor", max_items=5, max_charge_usd=0.05),
                {"handle": "h"},
                token="secret",
                on_items=on_items,
                poll_s=0,
                client=client,
            )

    result = asyncio.run(go())
    assert batches == [[0, 1, 2], [3, 4]]  # progressive, and capped at 5
    assert result.item_count == 5 and result.usage_usd == 0.012
    assert ("POST", "/v2/actor-runs/r1/abort") in calls  # stop paying once the cap is reached
