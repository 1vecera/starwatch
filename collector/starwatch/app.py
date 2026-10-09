"""FastAPI service: S1 and the other screens as static files, the run API and its SSE stream."""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, load_settings
from .events import RunChannel, now_iso
from .goals import map_goal, presets_json
from .models import Goal, RunRequest
from .pipeline import execute, plan_descriptors
from .retained import hydrate
from .steps.base import RunContext
from .store import RunStore

log = logging.getLogger("starwatch")
WEB_DIR = Path(__file__).parent / "web"
RUN_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    store = RunStore(settings.data_dir, recover_running=True)
    channels: dict[str, RunChannel] = {}
    tasks: set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        missing = settings.missing_credentials()
        if missing:
            log.warning(
                "Missing credentials: %s. Steps that need them report skipped.",
                ", ".join(missing),
            )
        yield
        for task in tasks:
            task.cancel()

    app = FastAPI(title="Starwatch", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store

    def channel_for(run_id: str) -> RunChannel:
        if not RUN_ID.match(run_id) or store.get(run_id) is None:
            raise HTTPException(404, "No such run")
        if run_id not in channels:
            channels[run_id] = RunChannel.from_log(run_id, store.run_dir(run_id) / "events.jsonl")
        return channels[run_id]

    @app.get("/api/health")
    def health() -> dict:
        return {
            "ok": True,
            "credentials": settings.credential_presence(),
            "missing": settings.missing_credentials(),
            "step_pause_s": settings.step_pause_s,
            "collection_paused": settings.collection_paused,
        }

    @app.get("/api/goals")
    def goals() -> list[dict]:
        return presets_json()

    @app.get("/api/plan")
    def plan() -> list[dict]:
        return plan_descriptors()

    @app.post("/api/runs", status_code=201)
    async def create_run(request: RunRequest) -> dict:
        if settings.collection_paused and not request.source_run_id:
            raise HTTPException(409, "Collection is paused for cost review; provide a retained source_run_id")
        preset, basis = map_goal(request.goal_preset, request.goal_text)
        goal = Goal(preset=preset, text=request.goal_text.strip())
        subject, anchor = request.subject.strip(), request.anchor.strip()
        if request.source_run_id:
            channel_for(request.source_run_id)
            source = store.read_json(request.source_run_id, "manifest.json")
            if not source or not store.read_json(request.source_run_id, "items.json"):
                raise HTTPException(409, "Source run has no retained collection")
            if source["subject"] != subject or source["anchor"] != anchor:
                raise HTTPException(409, "Source subject and anchor must match")
        mode = "cached" if request.source_run_id else "live"
        run_id = store.create(
            subject=subject,
            anchor=anchor,
            goal_preset=preset,
            goal_text=goal.text,
            mode=mode,
        )
        channel = RunChannel(run_id, store.run_dir(run_id) / "events.jsonl")
        channels[run_id] = channel
        ctx = RunContext(
            run_id=run_id,
            subject=subject,
            anchor=anchor,
            goal=goal,
            mode=mode,
            started_at=now_iso(),
            settings=settings,
            store=store,
            channel=channel,
        )
        if request.source_run_id:
            hydrate(ctx, request.source_run_id)
        task = asyncio.create_task(execute(ctx, basis))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {
            "run_id": run_id,
            "goal": goal.model_dump(),
            "goal_basis": basis,
            "events": f"/api/runs/{run_id}/events",
        }

    @app.get("/api/runs")
    def list_runs() -> list[dict]:
        return store.list()

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        channel_for(run_id)
        return store.read_json(run_id, "manifest.json") or store.get(run_id)

    @app.get("/api/runs/{run_id}/brief")
    def get_brief(run_id: str) -> dict:
        channel_for(run_id)
        brief = store.read_json(run_id, "brief.json")
        if brief is None:
            raise HTTPException(404, "This run has no brief yet")
        return brief

    @app.get("/api/runs/{run_id}/events")
    def run_events(run_id: str, after: int = 0, last_event_id: str | None = Header(default=None)) -> StreamingResponse:
        channel = channel_for(run_id)
        start = int(last_event_id) if last_event_id and last_event_id.isdigit() else after
        return StreamingResponse(
            channel.subscribe(after=start),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/runs/{run_id}/network")
    @app.get("/api/runs/{run_id}/alert")
    @app.get("/api/runs/{run_id}/overlap")
    def get_projection(run_id: str, request: Request) -> dict | list:
        channel_for(run_id)
        name = request.url.path.rsplit("/", 1)[-1]
        projection = store.read_json(run_id, "evidence-overlap.json" if name == "overlap" else f"{name}.json")
        if projection is None:
            raise HTTPException(404, "This projection is not available yet")
        return projection

    # Downloaded media and run files, e.g. /runs/<run_id>/media/instagram-123.jpg
    app.mount("/runs", StaticFiles(directory=settings.runs_dir), name="runs")
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def s1() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    return app
