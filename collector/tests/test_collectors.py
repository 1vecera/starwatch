"""Collectors: allowlist projection, media saved with true sizes, honest coverage, capped Actor runs.

Raw items below are invented, shaped like each Actor's output; none is collected data.
"""

import asyncio
import json
import struct
import zlib

import httpx

from starwatch.collectors import base as base_module
from starwatch.collectors.actors import ACTORS, ActorSpec
from starwatch.collectors.apify import API, ActorRunResult, ApifyRunFailed, StopRun, charged_usd, run_actor
from starwatch.collectors.facebook import FacebookCollector
from starwatch.collectors.identity import IdentityBoard, parse_anchor
from starwatch.collectors.instagram import InstagramCollector
from starwatch.collectors.media import image_size
from starwatch.collectors.tiktok import TiktokCollector
from starwatch.collectors.x import XCollector
from starwatch.collectors.youtube import YoutubeCollector
from starwatch.config import load_settings
from starwatch.events import RunChannel
from starwatch.models import Account, Goal, Media
from starwatch.steps.base import RunContext
from starwatch.store import RunStore


def png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IEND", b"")


def jpeg(width: int, height: int) -> bytes:
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 4) + b"JF" + sof + b"\xff\xd9"


def test_image_size_reads_headers():
    assert image_size(png(1080, 1920)) == (1080, 1920)
    assert image_size(jpeg(1280, 720)) == (1280, 720)
    assert image_size(b"not an image") is None


ACCOUNT = Account(platform="facebook", url="https://www.facebook.com/jan.novak", handle="jan.novak",
                  match_basis=["linked from novak.example"], status="accepted")


def test_projections_keep_only_the_allowlist():
    fb = FacebookCollector().project({
        "postId": "1", "url": "https://www.facebook.com/jan.novak/posts/1", "time": "2026-10-01T10:00:00.000Z",
        "text": "Dnes v Brně.", "likes": 10, "comments": 4, "isVideo": False,
        "topComments": [{"text": "a commenter's words", "profileName": "Someone"}],
        "media": [{"__typename": "Photo", "photo_image": {"uri": "https://cdn.example/1.jpg", "width": 9, "height": 9}}],
    }, ACCOUNT, "2026-10-09T00:00:00Z")
    stored = fb.item.model_dump_json()
    assert "commenter" not in stored and "Someone" not in stored
    assert fb.item.metrics == {"likes": 10, "comments_count": 4}
    assert fb.image_url == "https://cdn.example/1.jpg"

    ig_account = ACCOUNT.model_copy(update={"platform": "instagram", "handle": "jan.novak"})
    ig = InstagramCollector().project({
        "id": "9", "shortCode": "Ab", "type": "Video", "caption": "Video", "timestamp": "2026-10-02T00:00:00.000Z",
        "displayUrl": "https://cdn.example/9.jpg", "videoUrl": "https://cdn.example/9.mp4", "videoDuration": 41.5,
        "ownerUsername": "jan.novak", "latestComments": [{"text": "x"}], "firstComment": "x",
    }, ig_account, "now")
    assert ig.item.kind == "video" and ig.video_seconds == 41.5 and "firstComment" not in ig.item.model_dump_json()
    other = InstagramCollector().project({"id": "8", "url": "u", "ownerUsername": "someone.else"}, ig_account, "now")
    assert other is None  # another profile's post never lands in the subject's lane

    tt = TiktokCollector().project({
        "id": "7", "webVideoUrl": "https://www.tiktok.com/@jan_novak/video/7", "createTimeISO": "2026-10-03T00:00:00.000Z",
        "authorMeta": {"name": "jan_novak", "nickName": "Jan Novák"},
        "videoMeta": {"coverUrl": "https://cdn.example/7.jpg", "duration": 60},
    }, ACCOUNT.model_copy(update={"platform": "tiktok", "handle": "jan_novak"}), "now")
    assert tt.item.kind == "video" and tt.image_url.endswith("7.jpg") and tt.video_url.endswith("/7")

    yt = YoutubeCollector().project({
        "id": "abc", "url": "https://www.youtube.com/watch?v=abc", "title": "Rozhovor", "text": "Popis",
        "thumbnailUrl": "https://i.ytimg.com/vi/abc/maxresdefault.jpg", "duration": "00:01:05",
    }, ACCOUNT, "now")
    assert yt.item.text == "Rozhovor\n\nPopis" and yt.video_seconds == 65

    x = XCollector().project({
        "type": "tweet", "id": "5", "url": "https://x.com/JanNovak/status/5", "fullText": "Celý text",
        "createdAt": "Fri Oct 02 09:57:28 +0000 2026",
        "extendedEntities": {"media": [{"media_url_https": "https://pbs.twimg.com/media/A.jpg"}]},
    }, ACCOUNT, "now")
    assert x.item.published_at == "2026-10-02T09:57:28Z" and x.image_url.endswith("A.jpg?name=small")


def test_dataset_fields_exclude_comments_and_other_people():
    for spec in ACTORS.values():
        assert spec.fields, spec.actor_id
        assert not {"topComments", "latestComments", "firstComment", "taggedUsers", "coauthorProducers"} & set(spec.fields)
    assert ACTORS["tiktok"].base_input["commentsPerPost"] == 0
    assert ACTORS["tiktok"].base_input["maxFollowersPerProfile"] == 0
    assert ACTORS["tiktok"].max_charge_usd >= 0.5  # the Actor refuses a lower cap


def make_ctx(tmp_path, subject="Jan Novák"):
    settings = load_settings(data_dir=tmp_path, _credentials={"APIFY_TOKEN": "t"})
    store = RunStore(tmp_path)
    run_id = store.create(subject=subject, anchor="novak.example", goal_preset="G1", goal_text="", mode="live")
    channel = RunChannel(run_id, store.run_dir(run_id) / "events.jsonl")
    ctx = RunContext(run_id=run_id, subject=subject, anchor="novak.example", goal=Goal(preset="G1"), mode="live",
                     started_at="now", settings=settings, store=store, channel=channel)
    board = IdentityBoard(ctx, parse_anchor("novak.example"))
    ctx.__dict__["identity_board"] = board
    return ctx, board


def fake_actor(raw_items, usage=0.02):
    async def run(spec, run_input, *, token, on_items, **_):
        try:
            await on_items(raw_items)
        except StopRun as stop:
            return ActorRunResult("r1", f"ABORTED ({stop.reason})", "d1", len(raw_items), usage, "url")
        return ActorRunResult("r1", "SUCCEEDED", "d1", len(raw_items), usage, "url")
    return run


def fake_download(self, url, name, *, kind="image", client=None):
    async def save():
        relative = f"media/{name}.png"
        (self.run_dir / relative).write_bytes(png(1080, 1350))
        return Media(kind=kind, path=relative, source_url=url)
    return save()


def fb_raw(n, name="Jan Novák"):
    return {"postId": str(n), "url": f"https://www.facebook.com/jan.novak/posts/{n}", "text": f"post {n}",
            "user": {"name": name}, "media": [{"photo_image": {"uri": f"https://cdn.example/{n}.jpg"}}]}


def test_a_lane_streams_items_with_real_sizes_and_records_cost(tmp_path, monkeypatch):
    ctx, board = make_ctx(tmp_path)
    board.settle("facebook", ACCOUNT)
    monkeypatch.setattr(base_module, "run_actor", fake_actor([fb_raw(1), fb_raw(2), fb_raw(2)]))
    monkeypatch.setattr(RunContext, "download_media", fake_download)
    result = asyncio.run(FacebookCollector().run(ctx))
    assert result.status == "done" and result.count == 2  # the duplicate is dropped
    assert ctx.coverage["facebook"].status == "collected"
    assert ctx.costs.apify_usd == 0.02
    arrivals = [e for e in ctx.channel.events if e.type == "step.item"]
    assert [a.item.width for a in arrivals] == [1080, 1080] and arrivals[0].item.thumb.startswith(f"/runs/{ctx.run_id}/media/")
    runs = json.loads((ctx.run_dir / "apify_runs.json").read_text())
    assert runs[0]["lane"] == "collect.facebook" and runs[0]["usage_usd"] == 0.02


def test_an_account_named_for_someone_else_is_rejected_not_collected(tmp_path, monkeypatch):
    ctx, board = make_ctx(tmp_path)
    office = ACCOUNT.model_copy(update={"url": "https://www.facebook.com/uradprikladu", "handle": "uradprikladu"})
    board.settle("facebook", office)
    monkeypatch.setattr(base_module, "run_actor", fake_actor([fb_raw(1, "Úřad příkladů"), fb_raw(2, "Úřad příkladů")]))
    monkeypatch.setattr(RunContext, "download_media", fake_download)
    result = asyncio.run(FacebookCollector().run(ctx))
    assert result.status == "skipped" and not ctx.items
    assert ctx.coverage["facebook"].status == "not_found"
    assert "named “Úřad příkladů”, not Jan Novák" in ctx.coverage["facebook"].note
    assert board.rejected[0].url == office.url and ctx.accounts_for("facebook") == []


def test_no_account_and_a_failing_actor_become_labelled_gaps(tmp_path, monkeypatch):
    ctx, board = make_ctx(tmp_path)
    board.settle("facebook", None, "no Facebook account linked from novak.example")
    result = asyncio.run(FacebookCollector().run(ctx))
    assert result.status == "skipped"
    assert ctx.coverage["facebook"].model_dump() == {
        "platform": "facebook", "status": "not_found", "items": 0, "note": "no Facebook account linked from novak.example"}

    ctx, board = make_ctx(tmp_path / "second")
    board.settle("facebook", ACCOUNT)
    attempts = []

    async def failing(spec, run_input, *, token, on_items, **_):
        attempts.append(1)
        raise ApifyRunFailed("apify/facebook-posts-scraper ended FAILED: blocked", run_id=f"r{len(attempts)}", usage_usd=0.001)

    monkeypatch.setattr(base_module, "run_actor", failing)
    result = asyncio.run(FacebookCollector().run(ctx))
    assert len(attempts) == 2  # one retry
    assert result.status == "failed" and ctx.coverage["facebook"].status == "unavailable"
    assert "blocked" in ctx.coverage["facebook"].note and ctx.costs.apify_usd == 0.002


def test_run_actor_keeps_partial_items_when_time_runs_out_and_reads_charged_cost():
    calls = []
    run_obj = {"status": "RUNNING", "usageTotalUsd": 0.0, "chargedEventCounts": {"post": 2, "actor-start": 1},
               "pricingInfo": {"pricingPerEvent": {"actorChargeEvents": {"post": {"eventPriceUsd": 0.004},
                                                                          "actor-start": {"eventPriceUsd": 0.001}}}}}
    assert charged_usd(run_obj) == 0.009

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/runs"):
            return httpx.Response(201, json={"data": {"id": "r1", "defaultDatasetId": "d1"}})
        if request.url.path == "/v2/actor-runs/r1":
            return httpx.Response(200, json={"data": run_obj})
        if request.url.path == "/v2/datasets/d1/items":
            assert request.url.params["fields"] == "a,b"
            return httpx.Response(200, json=[{"a": 1}, {"a": 2}][int(request.url.params["offset"]):])
        if request.url.path == "/v2/actor-runs/r1/abort":
            return httpx.Response(200, json={"data": {}})
        return httpx.Response(404)

    got = []

    async def on_items(items):
        got.extend(items)

    async def go():
        async with httpx.AsyncClient(base_url=API, transport=httpx.MockTransport(handler)) as client:
            return await run_actor(ActorSpec("x", "a/b", max_items=10, max_charge_usd=0.1, timeout_s=-29, fields=("a", "b")),
                                   {}, token="t", on_items=on_items, poll_s=0, settle_s=0, client=client)

    result = asyncio.run(go())
    assert len(got) == 2 and result.item_count == 2
    assert result.status.startswith("ABORTED (stopped after")
    assert ("POST", "/v2/actor-runs/r1/abort") in calls
    assert result.usage_usd == 0.009  # charged events, while usageTotalUsd still lags at 0
