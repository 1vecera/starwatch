"""Write the SAMPLE event stream the screens are designed and filmed against before real runs exist.

    uv run python starwatch/web/sample/generate.py

The stream has the exact shape of a live run (run.started, step.status, step.item, step.data,
run.finished; see starwatch/events.py) and the pacing of one: identity first, six Actors polled while
they run, items arriving in dataset batches, then transcription, extraction and writing. Everything
in it is invented placeholder content for the stand-in "Jméno Příjmení" and is labelled SAMPLE on
screen: no real person, account or post. Image slots carry only their true aspect ratio (thumb is
null), so the screens draw flat frames marked "post image" instead of pictures.

Two fields go beyond the skeleton's ItemArrival and are proposed for the collectors: `metrics`
(collected counts) and `collected_at`. Per-Actor `step.data {usage_usd}` and extraction's
`step.data {kept, dropped, claims}` are proposed in the same way. Screens work without them.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

OUT = Path(__file__).with_name("run-g1.jsonl")
RUN_ID = "20261009-034100-5a3c"
START = datetime(2026, 10, 9, 1, 41, 0, tzinfo=UTC)  # 03:41 in Prague
rng = random.Random(7)

PLAN = [
    ("identity", "Resolve identity", "identity", None, None, None, 0),
    ("collect.website", "Website", "collect", "apify/website-content-crawler", "website", 20, 1),
    ("collect.facebook", "Facebook", "collect", "apify/facebook-posts-scraper", "facebook", 30, 1),
    ("collect.instagram", "Instagram", "collect", "apify/instagram-scraper", "instagram", 30, 1),
    ("collect.tiktok", "TikTok", "collect", "clockworks/tiktok-scraper", "tiktok", 20, 1),
    ("collect.youtube", "YouTube", "collect", "streamers/youtube-scraper", "youtube", 10, 1),
    ("collect.x", "X", "collect", "apidojo/twitter-scraper-lite", "x", 30, 1),
    ("transcribe", "Transcribe", "downstream", None, None, None, 2),
    ("extract", "Extract claims", "downstream", None, None, None, 3),
    ("write", "Plan and write", "downstream", None, None, None, 4),
    ("render", "Render", "downstream", None, None, None, 5),
]

# Neutral placeholder lines in Czech, about places and public works, naming no real person.
TEXTS = [
    "Dnes jsme s kolegy projeli nový úsek cyklostezky podél Labe. Díky všem, kdo na něm pracovali.",
    "Na zastupitelstvu jsme schválili opravu mostu přes Labe v Ústí nad Labem. Začít se má v březnu.",
    "Ranní spoj z Děčína do Ústí bude od prosince jezdit každých 30 minut.",
    "Navštívili jsme základní školu v Teplicích, kde se letos opravila tělocvična.",
    "Krajská nemocnice v Mostě dostane nové oddělení urgentního příjmu.",
    "Diskuse o dopravě v Litoměřicích: díky za všechny otázky, odpovědi doplním sem.",
    "Řízení dopravy v Ústí nad Labem se od pondělí mění kvůli uzavírce Masarykovy ulice.",
    "Na Chomutovsku chybí řidiči autobusů. Co s tím chceme dělat, vysvětluji ve videu.",
    "Víkendový festival v Žatci: děkuji pořadatelům i dobrovolníkům.",
    "Oprava silnice I/13 mezi Mostem a Chomutovem: přehled termínů uzavírek.",
    "Příliš žluťoučký kůň úpěl ďábelské ódy. Ukázka textu pro typografii, ne skutečný příspěvek.",
    "Setkání se starosty obcí na Šluknovsku. Hlavní témata: vlaky, školy a lékaři.",
    "Na nádraží v Ústí bude nový přestupní terminál. Projekt jsme dnes představili.",
    "Studenti z Děčína vyhráli soutěž v robotice. Gratuluji!",
    "Kolik stojí oprava krajských silnic? Odpovídám na nejčastější otázky.",
    "Cyklostezka podél Labe měří 14 kilometrů a spojí Ústí s Děčínem.",
    "Kraj přidá od prosince 12 nových autobusových linek, hlavně na venkově.",
    "Odpoledne v Lounech: debata o budoucnosti regionálních tratí.",
    "Nový sportovní areál v Rumburku je otevřený pro veřejnost.",
    "Most přes Labe: odpovídám na otázky k objízdným trasám.",
]
PAGES = [
    ("Jméno Příjmení · O mně", "O mně: životopis, kontakty a odkazy na oficiální účty."),
    ("Program pro Ústecký kraj", "Program: doprava, školy, zdravotnictví a bydlení v kraji."),
    ("Kontakty a kancelář", "Kancelář v Ústí nad Labem, úřední hodiny a kontakty."),
]

RATIOS = {
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "9:16": (1080, 1920),
    "16:9": (1280, 720),
    "link": (1200, 628),
}

events: list[dict] = []


def emit(at: float, type_: str, **fields) -> None:
    ts = (START + timedelta(seconds=at)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    events.append({"seq": 0, "ts": ts, "type": type_, "run_id": RUN_ID, **fields})


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def metrics_for(platform: str) -> dict[str, int]:
    def lognormal(mu: float, sigma: float) -> int:
        return int(rng.lognormvariate(mu, sigma))

    if platform == "facebook":
        return {"likes": lognormal(5.6, 0.8), "comments": lognormal(3.2, 0.9), "shares": lognormal(2.6, 1.0)}
    if platform == "instagram":
        return {"likes": lognormal(6.4, 0.7), "comments": lognormal(3.0, 0.8)}
    if platform == "tiktok":
        views = lognormal(9.6, 1.0)
        return {"views": views, "likes": int(views * rng.uniform(0.04, 0.11)), "comments": lognormal(3.4, 0.9)}
    if platform == "youtube":
        views = lognormal(8.0, 0.9)
        return {"views": views, "likes": int(views * rng.uniform(0.01, 0.04)), "comments": lognormal(1.8, 0.8)}
    return {}


def items_for(platform: str, count: int, span_days: int) -> list[dict]:
    """Newest first, as the Actors return them."""
    ages = sorted(rng.uniform(0.2, span_days) for _ in range(count))
    out = []
    for n, age in enumerate(ages, start=1):
        published = START - timedelta(days=age, hours=rng.uniform(0, 10))
        item = {
            "id": f"{platform}:sample-{n:04d}",
            "platform": platform,
            "kind": "post",
            "url": f"sample:{platform}/{n:04d}",
            "published_at": iso(published),
            "thumb": None,
            "media_kind": "image",
            "text": rng.choice(TEXTS)[:140],
            "metrics": metrics_for(platform),
        }
        if platform == "facebook":
            ratio = rng.choices(["1:1", "4:5", "link", None], weights=[4, 3, 3, 2])[0]
        elif platform == "instagram":
            ratio = rng.choices(["1:1", "4:5", "9:16"], weights=[3, 4, 3])[0]
        elif platform == "tiktok":
            ratio = "9:16"
        else:
            ratio = "16:9"
        if platform in ("tiktok", "youtube") or ratio == "9:16":
            item["kind"] = "video"
        if ratio is None:
            item["media_kind"] = None  # a text-only post: the screen shows its words, not a frame
        else:
            item["width"], item["height"] = RATIOS[ratio]
        out.append(item)
    return out


def collect(step: str, items: list[dict], start: float, batches: list[int], every: float) -> float:
    """Items reach the screen in dataset-poll batches, each image downloaded before it is sent."""
    at, sent = start, 0
    for size in batches:
        t = at
        for item in items[sent:sent + size]:
            t += rng.uniform(0.18, 0.55)
            sent += 1
            arrival = {**item, "collected_at": iso(START + timedelta(seconds=t))}
            emit(t, "step.item", step=step, count=sent, item=arrival)
        at += every + rng.uniform(-1.0, 1.0)
    return at


def main() -> None:
    plan = []
    for step_id, label, group, actor, platform, max_items, stage in PLAN:
        row = {"id": step_id, "label": label, "group": group, "actor": actor, "platform": platform}
        if max_items:
            row["max_items"] = max_items
        plan.append({**row, "stage": stage, "status": "queued", "count": None, "note": ""})

    emit(0.0, "run.started", data={
        "subject": "Jméno Příjmení",
        "anchor": "jmeno-prijmeni.example",
        "goal": {"preset": "G1", "text": "doprava v Ústeckém kraji"},
        "goal_basis": "chosen",
        "mode": "sample",
        "sample": True,
        "started_at": iso(START).replace("Z", ".000Z"),
        "step_pause_s": 0,
        "credentials": {"APIFY_TOKEN": True, "ELEVENLABS_API_KEY": True, "ANTHROPIC_API_KEY": True},
        "plan": plan,
    })

    # Identity: accounts from the anchor, one namesake rejected with its reason.
    emit(0.05, "step.status", step="identity", status="running")
    emit(5.8, "step.data", step="identity", data={
        "accounts": [
            {"platform": "facebook", "url": "sample:facebook/jmeno.prijmeni", "handle": "facebook.com/jmeno.prijmeni",
             "match_basis": ["linked from the anchor site"], "status": "accepted"},
            {"platform": "instagram", "url": "sample:instagram/jmeno.prijmeni", "handle": "@jmeno.prijmeni",
             "match_basis": ["bio names the party", "linked from the site"], "status": "accepted"},
            {"platform": "tiktok", "url": "sample:tiktok/jmenoprijmeni", "handle": "@jmenoprijmeni",
             "match_basis": ["same name and photo, no link to the anchor"], "status": "unconfirmed"},
            {"platform": "youtube", "url": "sample:youtube/jmenoprijmeni", "handle": "youtube.com/@jmenoprijmeni",
             "match_basis": ["linked from the anchor site"], "status": "accepted"},
        ],
        "rejected": [
            {"platform": "facebook", "url": "sample:facebook/jmeno.prijmeni.brno", "handle": "facebook.com/jmeno.prijmeni.brno",
             "reason": "other city (Brno), no link to the anchor site"},
        ],
    })
    emit(6.0, "step.status", step="identity", status="done", count=4)

    collectors = ["website", "facebook", "instagram", "tiktok", "youtube", "x"]
    for n, platform in enumerate(collectors):
        emit(6.1 + n * 0.04, "step.status", step=f"collect.{platform}", status="running")

    # Website: three pages, no images, so they arrive as words.
    t = 8.6
    for n, (title, text) in enumerate(PAGES, start=1):
        t += rng.uniform(0.4, 0.9)
        emit(t, "step.item", step="collect.website", count=n, item={
            "id": f"website:sample-{n:04d}", "platform": "website", "kind": "page",
            "url": f"sample:website/{n}", "published_at": "", "thumb": None, "media_kind": None,
            "text": f"{title}. {text}"[:140], "metrics": {}, "collected_at": iso(START + timedelta(seconds=t)),
        })
    emit(12.0, "step.data", step="collect.website", data={"usage_usd": 0.012})
    emit(12.05, "step.status", step="collect.website", status="done", count=3)

    fb = items_for("facebook", 30, 62)
    ig = items_for("instagram", 30, 84)
    tt = items_for("tiktok", 20, 70)
    yt = items_for("youtube", 10, 88)
    end_fb = collect("collect.facebook", fb, 13.5, [4, 6, 5, 7, 8], 6.4)
    end_ig = collect("collect.instagram", ig, 16.0, [3, 5, 6, 6, 5, 5], 6.8)
    end_tt = collect("collect.tiktok", tt, 21.5, [4, 5, 6, 5], 7.6)
    end_yt = collect("collect.youtube", yt, 25.5, [3, 4, 3], 8.8)

    # X: the Actor returns nothing without sign-in. A gap, not a zero.
    emit(31.2, "step.status", step="collect.x", status="failed", count=0,
         note="login wall: no public posts without sign-in")

    for step, end, usage, count in (
        ("collect.facebook", end_fb, 0.121, 30),
        ("collect.instagram", end_ig, 0.069, 30),
        ("collect.tiktok", end_tt, 0.063, 20),
        ("collect.youtube", end_yt, 0.030, 10),
    ):
        emit(end, "step.data", step=step, data={"usage_usd": usage})
        emit(end + 0.05, "step.status", step=step, status="done", count=count)

    last = max(end_fb, end_ig, end_tt, end_yt) + 0.6
    emit(last, "step.status", step="transcribe", status="running")
    minutes = 0.0
    for n, length in enumerate([1.4, 0.9, 1.7, 1.2, 2.0], start=1):
        minutes += length
        emit(last + n * 6.2, "step.status", step="transcribe", status="running", count=n,
             note=f"{n} of 5 videos · {minutes:.1f} min")
    t = last + 31.5
    emit(t, "step.data", step="transcribe", data={"summary": f"5 videos · {minutes:.1f} min transcribed", "minutes": round(minutes, 1)})
    emit(t + 0.1, "step.status", step="transcribe", status="done", count=5, note=f"5 of 5 videos · {minutes:.1f} min")

    emit(t + 0.3, "step.status", step="extract", status="running")
    t += 19.0
    claims = [
        {"id": "F1", "kind": "fact", "confidence": "high",
         "text": "Oprava mostu přes Labe v Ústí nad Labem má začít v březnu 2027.",
         "item_ids": ["facebook:sample-0003", "youtube:sample-0002", "instagram:sample-0011"]},
        {"id": "F2", "kind": "fact", "confidence": "high",
         "text": "Cyklostezka podél Labe měří 14 kilometrů a spojí Ústí s Děčínem.",
         "item_ids": ["instagram:sample-0002", "facebook:sample-0008", "tiktok:sample-0006"]},
        {"id": "F3", "kind": "fact", "confidence": "medium",
         "text": "Kraj má od prosince přidat 12 autobusových linek.",
         "item_ids": ["tiktok:sample-0004", "facebook:sample-0012", "instagram:sample-0019"]},
        {"id": "I1", "kind": "inference", "confidence": "medium",
         "text": "Doprava je hlavním tématem podzimních příspěvků.", "based_on": ["F1", "F3"],
         "item_ids": ["youtube:sample-0002", "tiktok:sample-0004", "facebook:sample-0012", "facebook:sample-0003"]},
        {"id": "Q1", "kind": "open_question", "confidence": "low",
         "text": "Termín dokončení obchvatu Děčína žádný příspěvek neuvádí.",
         "item_ids": ["facebook:sample-0017", "youtube:sample-0006"]},
        {"id": "M1", "kind": "missing_source", "confidence": "low",
         "text": "Příspěvky na X nebyly v tomto běhu dostupné.", "item_ids": []},
    ]
    emit(t, "step.data", step="extract", data={"kept": 41, "dropped": 7, "claims": claims})
    emit(t + 0.1, "step.status", step="extract", status="done", count=41, note="41 kept · 7 dropped: quote not found verbatim")

    emit(t + 0.4, "step.status", step="write", status="running")
    t += 21.0
    emit(t, "step.data", step="write", data={"summary": "G1 brief · 4 sections · 23 sources cited"})
    emit(t + 0.1, "step.status", step="write", status="done", note="G1 brief · 4 sections · 23 sources cited")
    emit(t + 0.4, "step.status", step="render", status="running")
    emit(t + 1.6, "step.status", step="render", status="done")
    t += 1.9
    emit(t, "run.finished", status="finished", data={
        "finished_at": iso(START + timedelta(seconds=t)).replace("Z", ".000Z"),
        "coverage": [
            {"platform": "website", "status": "collected", "items": 3, "note": ""},
            {"platform": "facebook", "status": "collected", "items": 30, "note": ""},
            {"platform": "instagram", "status": "collected", "items": 30, "note": ""},
            {"platform": "tiktok", "status": "collected", "items": 20, "note": ""},
            {"platform": "youtube", "status": "collected", "items": 10, "note": ""},
            {"platform": "x", "status": "unavailable", "items": 0, "note": "login wall: no public posts without sign-in"},
        ],
        "costs": {"apify_usd": 0.295, "scribe_minutes": round(minutes, 1), "llm_tokens": 48210},
    })

    events.sort(key=lambda e: e["ts"])
    for seq, event in enumerate(events, start=1):
        event["seq"] = seq
    OUT.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    print(f"{OUT.name}: {len(events)} events over {t:.0f} s")


if __name__ == "__main__":
    main()
