"""Smoke test: create a run over HTTP and receive its whole SSE event stream."""

import json

from fastapi.testclient import TestClient

from starwatch.app import create_app
from starwatch.config import load_settings
from starwatch.pipeline import plan_descriptors


def read_events(response) -> list[dict]:
    events = []
    for line in response.iter_lines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
            if events[-1]["type"] == "run.finished":
                break
    return events


def test_run_streams_honest_step_events(tmp_path):
    settings = load_settings(data_dir=tmp_path, _credentials={})
    with TestClient(create_app(settings)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/health").json()["missing"] == [
            "APIFY_TOKEN", "ELEVENLABS_API_KEY", "ANTHROPIC_API_KEY"
        ]

        created = client.post(
            "/api/runs",
            json={"subject": "Test Subject", "anchor": "https://example.org", "goal_text": "debata o školství"},
        )
        assert created.status_code == 201
        run = created.json()
        assert run["goal"]["preset"] == "G1"

        with client.stream("GET", run["events"]) as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            events = read_events(response)

    types = [e["type"] for e in events]
    assert types[0] == "run.started" and types[-1] == "run.finished"
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))

    final = {e["step"]: e["status"] for e in events if e["type"] == "step.status"}
    assert set(final) == {d["id"] for d in plan_descriptors()}
    # Nothing is built yet, so nothing may claim to be done.
    assert set(final.values()) == {"not_implemented"}

    coverage = events[-1]["data"]["coverage"]
    assert {c["platform"] for c in coverage} == {"website", "facebook", "instagram", "tiktok", "youtube", "x"}
    assert all(c["status"] == "skipped" for c in coverage)

    run_dir = tmp_path / "runs" / run["run_id"]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["mode"] == "live" and manifest["status"] == "finished"
    assert len((run_dir / "events.jsonl").read_text().splitlines()) == len(events)
