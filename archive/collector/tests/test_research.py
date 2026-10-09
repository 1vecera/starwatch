"""Research contracts use invented public-source fixtures; no provider calls or scraped data."""

import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from starwatch.app import create_app
from starwatch.config import load_settings
from starwatch.events import RunChannel, now_iso
from starwatch.models import Account, Brief, CollectedItem, Goal, Media, Transcript
from starwatch.steps.base import RunContext
from starwatch.steps.evidence import evidence_overlap, verify_items
from starwatch.steps.render import alert_data
from starwatch.steps.transcribe import Transcribe
from starwatch.store import RunStore


def context(tmp_path, *, preset="G1", origin=""):
    settings = load_settings(data_dir=tmp_path, _credentials={}, collection_paused=True)
    store = RunStore(tmp_path)
    rid = store.create(
        subject="Jan Novák",
        anchor="https://novak.example",
        goal_preset=preset,
        goal_text="",
        mode="cached",
    )
    return RunContext(
        run_id=rid,
        subject="Jan Novák",
        anchor="https://novak.example",
        goal=Goal(preset=preset),
        mode="cached",
        started_at=now_iso(),
        settings=settings,
        store=store,
        channel=RunChannel(rid, store.run_dir(rid) / "events.jsonl"),
        source_run_id=origin,
    )


def public_item(native, text, *, platform="website", kind="page", date="2026-10-08T10:00:00Z"):
    return CollectedItem(
        id=f"{platform}:{native}",
        platform=platform,
        kind=kind,
        url=f"https://novak.example/{native}",
        account_url="https://novak.example",
        text=text,
        published_at=date,
        collected_at="2026-10-09T00:00:00Z",
    )


def test_verifier_rejects_fabrication_and_bad_timestamps_then_drops_orphan_inference(
    tmp_path,
):
    ctx = context(tmp_path)
    item = public_item("clip", "Caption", platform="tiktok", kind="video")
    quote = "Soukromé školy potřebujeme."
    ctx.items = [item]
    ctx.transcripts = [
        Transcript(
            item_id=item.id,
            url=item.url,
            provider="scribe",
            text=quote,
            duration_s=6,
            words=[
                {
                    "text": quote,
                    "start": 2.5,
                    "end": 5.5,
                    "char_start": 0,
                    "char_end": len(quote),
                }
            ],
        )
    ]
    evidence = {
        "item_id": item.id,
        "url": item.url,
        "platform": "tiktok",
        "quote": quote,
        "source_kind": "scribe",
    }
    valid = {
        "id": "F-valid",
        "kind": "fact",
        "text": "Source statement: “" + quote + "”",
        "evidence": [evidence],
        "confidence": "medium",
    }
    candidates = [valid]
    for name, updates in [
        ("quote", {"quote": "Všechny školy zrušíme."}),
        ("url", {"url": "https://elsewhere.example"}),
        ("time", {"timecode": 5.0}),
        ("span", {"quote_start": 1}),
        ("empty", {"quote": ""}),
        ("nan", {"timecode": float("nan")}),
    ]:
        candidates.append({**valid, "id": name, "evidence": [{**evidence, **updates}]})
    candidates.append({**valid, "id": "uncited", "evidence": []})
    candidates.append({**valid, "id": "embellished", "text": "Jan secretly owns every school."})
    candidates.append(
        {
            "id": "orphan",
            "kind": "inference",
            "text": "A question",
            "based_on": ["quote"],
            "confidence": "low",
        }
    )
    kept, dropped = verify_items(ctx, candidates)
    assert [i.id for i in kept] == ["F-valid"]
    assert kept[0].evidence[0].timecode == 2.5 and kept[0].evidence[0].end_timecode == 5.5
    assert {i["id"] for i in dropped} == {
        "quote",
        "url",
        "time",
        "span",
        "empty",
        "nan",
        "uncited",
        "embellished",
        "orphan",
    }


def seed_retained(ctx):
    bio = public_item(
        "bio",
        "Jan Novák je politolog, univerzitní profesor a politik. Narodil se v Brně a působil jako rektor univerzity.",
    )
    school = public_item(
        "school",
        "School clip",
        platform="tiktok",
        kind="video",
        date="2026-10-01T10:00:00Z",
    )
    energy = public_item(
        "energy",
        "Energy clip",
        platform="tiktok",
        kind="video",
        date="2026-10-02T10:00:00Z",
    )
    post = public_item(
        "post",
        "Dnes jsme otevřeli novou knihovnu pro všechny obyvatele našeho města.",
        platform="facebook",
        kind="post",
    )
    ctx.store.write_json(ctx.run_id, "items.json", [bio, school, energy, post])
    ctx.store.write_json(
        ctx.run_id,
        "identity.json",
        {
            "accounts": [Account(platform="website", url=ctx.anchor, status="accepted").model_dump()],
            "rejected": [],
        },
    )
    ctx.store.write_json(
        ctx.run_id,
        "manifest.json",
        {
            "subject": ctx.subject,
            "anchor": ctx.anchor,
            "mode": "live",
            "started_at": ctx.started_at,
            "goal": ctx.goal.model_dump(),
            "coverage": [
                {
                    "platform": "youtube",
                    "status": "unavailable",
                    "items": 0,
                    "note": "Access refused",
                }
            ],
            "costs": {"apify_usd": 0.3},
        },
    )
    transcripts = []
    for item, text in [
        (
            school,
            "Soukromé školy potřebujeme pro dobré vzdělávání všech studentů. Náklady jsou 35 milionů korun.",
        ),
        (
            energy,
            "Cena energie by měla být nižší pro veřejné budovy v našem městě. Úspora činí 50 milionů korun.",
        ),
    ]:
        transcripts.append(
            Transcript(
                item_id=item.id,
                url=item.url,
                provider="tiktok_asr",
                text=text,
                duration_s=15,
                words=[
                    {
                        "text": text,
                        "start": 1.0,
                        "end": 14.0,
                        "char_start": 0,
                        "char_end": len(text),
                    }
                ],
            )
        )
    ctx.store.write_json(ctx.run_id, "asr-transcripts.json", transcripts)
    ctx.store.finish(ctx.run_id, "finished")


def test_paused_api_allows_cached_goals_and_preserves_graph_evidence_without_network(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    seed_retained(ctx)
    attempts = []

    async def forbidden(self, *args, **kwargs):
        attempts.append(args)
        raise AssertionError("cached processing must not make outbound requests")

    monkeypatch.setattr(httpx.AsyncClient, "request", forbidden)
    briefs = []
    with TestClient(create_app(ctx.settings)) as client:
        request = {"subject": ctx.subject, "anchor": ctx.anchor, "goal_preset": "G1"}
        assert client.post("/api/runs", json=request).status_code == 409
        assert len(client.get("/api/runs").json()) == 1  # denied collection leaves no paid job
        for goal in ("G1", "G2", "G3"):
            response = client.post(
                "/api/runs",
                json={**request, "goal_preset": goal, "source_run_id": ctx.run_id},
            )
            assert response.status_code == 201
            rid = response.json()["run_id"]
            # Streaming waits for the background pipeline to finish and exercises replay.
            with client.stream("GET", response.json()["events"]) as stream:
                events = [json.loads(l[6:]) for l in stream.iter_lines() if l.startswith("data: ")]
            assert events[-1]["type"] == "run.finished"
            assert not [e for e in events if e.get("status") in ("failed", "not_implemented")]
            brief = Brief.model_validate(client.get(f"/api/runs/{rid}/brief").json())
            assert brief.run.mode == "cached" and brief.run.source_run_id == ctx.run_id
            assert brief.run.costs.apify_usd == brief.run.costs.scribe_minutes == brief.run.costs.llm_tokens == 0
            assert brief.run.source_costs.apify_usd == 0.3
            assert brief.coverage[0].status == "unavailable"
            graph = client.get(f"/api/runs/{rid}/network").json()
            ids = {n["id"] for n in graph["nodes"]}
            assert all(e["source"] in ids and e["target"] in ids for e in graph["edges"])
            assert client.get(f"/api/runs/{rid}/alert").json()["is_new"] is False
            assert (
                client.get(
                    response.json()["events"],
                    headers={"Last-Event-ID": str(events[-2]["seq"])},
                ).text.count("data: ")
                == 1
            )
            briefs.append(brief)
        overlap = client.get(f"/api/runs/{rid}/overlap").json()
        assert any(o["right_goal"] == "G1" and o["passes"] for o in overlap)
    assert evidence_overlap(briefs[0], briefs[2])["passes"]
    assert len({tuple(s.title for s in b.sections) for b in briefs}) == 3
    assert not attempts


def test_scribe_submissions_are_bounded_reused_and_uncertain_results_not_retried(tmp_path, monkeypatch):
    ctx = context(tmp_path, origin="original-observation")
    ctx.settings._credentials = {"ELEVENLABS_API_KEY": "secret"}
    for n in range(6):
        item = public_item(
            str(n),
            "Video",
            platform="tiktok",
            kind="video",
            date=f"2026-10-0{n + 1}T10:00:00Z",
        )
        media = f"media/{n}.mp4"
        (ctx.run_dir / media).write_bytes(f"video {n}".encode())
        item.media = [Media(kind="video", path=media)]
        ctx.items.append(item)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["xi-api-key"] == "secret" and "secret" not in str(request.url)
        assert b"scribe_v2" in request.content and b"word" in request.content
        if len(calls) == 1:
            raise httpx.ReadTimeout("unknown provider outcome")
        return httpx.Response(
            200,
            json={
                "language_code": "cs",
                "text": "Školy potřebujeme pro studenty.",
                "words": [
                    {
                        "type": "word",
                        "text": "Školy potřebujeme pro studenty.",
                        "start": 1,
                        "end": 5,
                    }
                ],
            },
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "starwatch.steps.transcribe.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )

    async def duration(path):
        return 30.0

    monkeypatch.setattr("starwatch.steps.transcribe.video_duration", duration)
    asyncio.run(Transcribe().run(ctx))
    assert len(calls) == 5 and len(ctx.transcripts) == 4 and ctx.costs.scribe_minutes == 2.5
    ledger = json.loads((tmp_path / "scribe-ledger.json").read_text())
    assert len(ledger["original-observation"]) == 5  # failed/uncertain submission consumes a slot
    ctx.costs.scribe_minutes = 0
    asyncio.run(Transcribe().run(ctx))
    assert len(calls) == 5 and ctx.costs.scribe_minutes == 0 and ctx.costs.scribe_reused_minutes == 2
    newest = ctx.items[-1].model_copy(deep=True)
    newest.id = "tiktok:new"
    newest.published_at = "2026-10-08T10:00:00Z"
    (ctx.run_dir / "media/new.mp4").write_bytes(b"new bytes")
    newest.media = [Media(kind="video", path="media/new.mp4")]
    ctx.items.append(newest)
    asyncio.run(Transcribe().run(ctx))
    assert len(calls) == 5
    status = json.loads((ctx.run_dir / "transcription-status.json").read_text())
    assert any("authorization exhausted" in row.get("note", "") for row in status)


def test_alert_needs_a_later_published_item_and_never_fires_for_first_snapshot(
    tmp_path,
):
    ctx = context(tmp_path)
    ctx.items = [public_item("new", "New public post", kind="post", date="2026-10-08T10:00:00Z")]
    assert alert_data(ctx)["status"] == "baseline"
    old = ctx.store.create(
        subject=ctx.subject,
        anchor=ctx.anchor,
        goal_preset="G1",
        goal_text="",
        mode="live",
    )
    ctx.store.write_json(old, "items.json", [])
    ctx.store.finish(old, "finished")
    with ctx.store._lock:
        ctx.store._db.execute("UPDATE runs SET created_at=? WHERE id=?", ("2026-10-01T10:00:00Z", old))
        ctx.store._db.commit()
    alert = alert_data(ctx)
    assert alert["is_new"] and alert["trigger_url"] == ctx.items[0].url
    ctx.items[0].published_at = "2026-09-01T10:00:00Z"
    assert alert_data(ctx)["status"] == "no_change"


def test_asr_capture_keeps_czech_cues_and_does_not_follow_untrusted_urls(tmp_path):
    from starwatch.collectors.subtitles import capture_asr, project_tracks

    ctx = context(tmp_path)
    item = public_item("asr", "Caption", platform="tiktok", kind="video")
    item.subtitle_tracks = project_tracks(
        {
            "videoMeta": {
                "subtitleLinks": [
                    {
                        "source": "MT",
                        "language": "eng-US",
                        "downloadLink": "https://translation.example/track",
                    },
                    {
                        "source": "ASR",
                        "language": "ces-CZ",
                        "downloadLink": "https://v16m.tiktokcdn-us.com/track",
                    },
                ]
            }
        }
    )
    calls = []
    vtt = "WEBVTT\n\n00:00:02.000 --> 00:00:05.500\n<b>Soukromé školy</b> potřebujeme pro studenty.\n\n"

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, text=vtt)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await capture_asr(ctx, item, client)
            item.subtitle_tracks.append(
                {
                    "source": "ASR",
                    "language": "ces-CZ",
                    "url": "http://127.0.0.1/private",
                }
            )
            malicious = item.model_copy(deep=True)
            malicious.subtitle_tracks = malicious.subtitle_tracks[-1:]
            await capture_asr(ctx, malicious, client)
            assert malicious.subtitle_tracks[0]["status"] == "unavailable"

    asyncio.run(run())
    stored = ctx.store.read_json(ctx.run_id, "asr-transcripts.json")
    assert len(calls) == 1 and len(stored) == 1
    assert stored[0]["text"] == "Soukromé školy potřebujeme pro studenty."
    assert stored[0]["words"][0]["start"] == 2 and stored[0]["words"][0]["end"] == 5.5
    assert stored[0]["words"][0]["granularity"] == "cue"
    assert (ctx.run_dir / item.subtitle_tracks[0]["path"]).read_text() == vtt


def test_opening_a_store_for_cached_work_does_not_interrupt_active_runs(tmp_path):
    ctx = context(tmp_path)
    observer = RunStore(tmp_path)
    assert observer.get(ctx.run_id)["status"] == "running"
    recovering = RunStore(tmp_path, recover_running=True)
    assert recovering.get(ctx.run_id)["status"] == "interrupted"
