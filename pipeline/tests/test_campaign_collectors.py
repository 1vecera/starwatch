"""Programme and article collectors end to end, with recorded responses instead of live services."""

from __future__ import annotations

import json

import pytest

from czlake.campaign.articles import ArticleCollector, clean_title, published_date
from czlake.campaign.common import BudgetExceeded, Cache, Ledger, OfflineMiss, digest, read_js, write_js
from czlake.campaign.exa import Exa
from czlake.campaign.programs import ProgramCollector, verify_promises
from czlake.campaign.snapshot import load
from czlake.campaign.text import Document
from czlake.campaign.web import Fetcher, canonical

SEARCHED = "2026-10-09T10:00:00+00:00"
PROGRAM_HTML = """<html><head><title>Program PRAHA SOBĚ 2026</title></head><body><main>
<h1>Volební program 2026</h1>
<p>Zahájíme přípravu stavby 8000 nových městských bytů a příspěvky developerů budeme vybírat ve formě hotových bytů.</p>
<p>Objednáme dalších 129 klimatizovaných tramvají, které jsme vysoutěžili.</p>
<p>Opravíme mosty, chodníky a zastávky tak, aby byly bezbariérové a bezpečné pro všechny Pražany.</p>
<a href="/program/doprava">Program: doprava</a></main></body></html>"""
TRANSPORT_HTML = """<html><head><title>Doprava</title></head><body><main><h1>Doprava</h1>
<p>Začneme pracovat na okružním Metru O, které přímo propojí okrajové části Prahy.</p>
<p>Prodloužíme tramvajové tratě na sídliště a zrychlíme autobusové linky vyhrazenými pruhy na hlavních
ulicích, aby cesta do centra trvala kratší dobu než autem.</p></main></body></html>"""


@pytest.fixture
def snapshot(tmp_path):
    raw = {
        "cities": [{"id": "554782", "name": "Praha"}, {"id": "582786", "name": "Brno"}],
        "lists": [
            {"id": "kv2026:554782:1373", "city_id": "554782", "name": "PRAHA SOBĚ", "short": "PS", "relevant": True},
            {"id": "kv2026:554782:768", "city_id": "554782", "name": "ANO 2011", "short": "ANO", "relevant": True},
            {"id": "kv2026:582786:768", "city_id": "582786", "name": "ANO 2011", "short": "ANO", "relevant": False},
        ],
        "cands": [
            {"id": "c1", "name": "Adam Scheinherr", "list_id": "kv2026:554782:1373", "city_id": "554782", "position": 1},
            {"id": "c2", "name": "Jan Hušbauer", "list_id": "kv2026:554782:768", "city_id": "554782", "position": 1},
            {"id": "c3", "name": "Václav Trojan", "list_id": "kv2026:582786:768", "city_id": "582786", "position": 1},
        ],
        "topics": [{"id": "production-labels-v1:housing"}, {"id": "production-labels-v1:transport"}],
    }
    path = tmp_path / "real.js"
    path.write_text("window.SW_RAW = " + json.dumps(raw, ensure_ascii=False) + ";\n")
    return load(path)


def seed_page(cache: Cache, url: str, html: str) -> None:
    key = digest({"get": url})
    cache.put("http", key, {"url": url, "final_url": url, "status": 200, "content_type": "text/html",
                            "fetched_at": SEARCHED, "via": "http"})
    path = cache.path("http", key, ".body")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(html.encode())


class FakeExa:
    def __init__(self, results):
        self.results = results
        self.queries = []

    def search(self, query, **kwargs):
        self.queries.append((query, kwargs))
        return {"searched_at": SEARCHED, "results": self.results(query)}


class FakeLLM:
    model = "fake-model"

    def __init__(self, answers):
        self.answers = answers
        self.prompts = []

    def json(self, *, system, prompt, schema, max_tokens, tag):
        self.prompts.append((tag, prompt))
        return self.answers(tag, prompt)


def test_ledger_caps_are_cumulative_across_runs(tmp_path):
    ledger = Ledger(tmp_path / "spend.jsonl", {"exa": 1.0})
    ledger.record("exa", 0.6, {"query": "q"})
    reopened = Ledger(tmp_path / "spend.jsonl", {"exa": 1.0})
    assert reopened.total("exa") == pytest.approx(0.6)
    reopened.check("exa", 0.3)
    with pytest.raises(BudgetExceeded):
        reopened.check("exa", 0.5)
    with pytest.raises(BudgetExceeded):
        reopened.check("unknown-service")


def test_exa_records_cost_once_and_replays_offline(tmp_path):
    cache = Cache(tmp_path / "cache")
    ledger = Ledger(tmp_path / "cache" / "spend.jsonl", {"exa": 1.0})
    calls = []

    class RecordingExa(Exa):
        def _post(self, body):
            calls.append(body)
            return {"costDollars": {"total": 0.007}, "results": [
                {"url": "https://a.cz/x", "title": "T", "publishedDate": "2026-10-01", "highlights": ["h"],
                 "text": "full article body that must not be kept"}]}

    exa = RecordingExa(cache, ledger, api_key="test")
    first = exa.search("dotaz", num_results=5)
    second = RecordingExa(Cache(tmp_path / "cache", offline=True), ledger, api_key="").search("dotaz", num_results=5)
    assert first == second and len(calls) == 1
    assert ledger.total("exa") == pytest.approx(0.007)
    assert "text" not in first["results"][0]
    with pytest.raises(OfflineMiss):
        RecordingExa(Cache(tmp_path / "cache", offline=True), ledger, api_key="").search("jiný dotaz")


def test_verify_promises_keeps_only_verbatim_quotes_with_page_anchors():
    pdf = Document("https://l.example/p.pdf", "pdf", "P", ["Úvod.", "Postavíme nový bazén na Lesné do roku 2028."],
                   SEARCHED)
    proposed = [
        {"document": 1, "text": "Build a pool", "quote": "Postavíme nový bazén na Lesné do roku 2028.",
         "topic": "housing"},
        {"document": 1, "text": "Invented", "quote": "Postavíme dva nové bazény na Lesné do roku 2028.",
         "topic": "none"},
        {"document": 1, "text": "Duplicate", "quote": "Postavíme nový bazén na Lesné do roku 2028",
         "topic": "housing"},
    ]
    kept, stats = verify_promises(proposed, [pdf], ("production-labels-v1:housing",))
    assert kept == [{"text": "Build a pool", "quote": "Postavíme nový bazén na Lesné do roku 2028.",
                     "topic": "production-labels-v1:housing", "source_url": "https://l.example/p.pdf#page=2"}]
    assert stats["dropped_not_found"] == 1 and stats["dropped_duplicate"] == 1


def test_programme_collector_end_to_end(tmp_path, snapshot):
    cache = Cache(tmp_path / "cache", offline=True)
    seed_page(cache, "https://prahasobe.cz/program", PROGRAM_HTML)
    seed_page(cache, "https://prahasobe.cz/program/doprava", TRANSPORT_HTML)
    exa = FakeExa(lambda query: [
        {"url": "https://www.facebook.com/prahasobe", "title": "FB", "highlights": []},
        {"url": "https://www.idnes.cz/praha/zpravy/program.A261001_1", "title": "News", "highlights": []},
        {"url": "https://prahasobe.cz/program", "title": "Program", "highlights": ["Volební program"]},
    ])
    triage = FakeLLM(lambda tag, prompt: {"selected": [1, 2], "reason": "own site"})

    def extract(tag, prompt):
        assert "[[page 1]]" not in prompt and "prahasobe.cz/program/doprava" in prompt
        return {"is_program": True, "reason": "ok", "program_title": "Volební program 2026",
                "summary": "The programme focuses on housing and transport.", "promises": [
                    {"document": 1, "text": "Prepare 8,000 municipal flats",
                     "quote": "Zahájíme přípravu stavby 8000 nových městských bytů", "topic": "housing"},
                    {"document": 1, "text": "Start Metro O", "quote": "Začneme pracovat na okružním Metru O",
                     "topic": "transport"},
                    {"document": 2, "text": "Free trams", "quote": "Jízdné v tramvajích bude zdarma pro všechny.",
                     "topic": "transport"}]}

    collector = ProgramCollector(snapshot, exa, Fetcher(cache), None, triage, FakeLLM(extract), workers=1,
                                 log=lambda message: None)
    [run] = collector.run(snapshot.select(ids=["kv2026:554782:1373"]))
    assert run.error is None
    entry = run.entry
    assert entry["status"] == "found"
    assert entry["program_url"] == "https://prahasobe.cz/program"
    assert [p["source_url"] for p in entry["promises"]] == ["https://prahasobe.cz/program",
                                                           "https://prahasobe.cz/program/doprava"]
    assert run.stats["dropped_not_found"] == 1
    assert {c.url for c in run.candidates} == {"https://prahasobe.cz/program", "https://prahasobe.cz/program/doprava"}


def test_programme_collector_reports_not_found(tmp_path, snapshot):
    cache = Cache(tmp_path / "cache", offline=True)
    seed_page(cache, "https://prahasobe.cz/program", PROGRAM_HTML)
    seed_page(cache, "https://prahasobe.cz/program/doprava", TRANSPORT_HTML)
    exa = FakeExa(lambda query: [{"url": "https://prahasobe.cz/program", "title": "P", "highlights": []}])
    triage = FakeLLM(lambda tag, prompt: {"selected": [], "reason": "a 2022 programme"})
    extractor = FakeLLM(lambda tag, prompt: pytest.fail("no extraction without a selected programme"))
    collector = ProgramCollector(snapshot, exa, Fetcher(cache), None, triage, extractor, workers=1,
                                 log=lambda message: None)
    [run] = collector.run(snapshot.select(ids=["kv2026:554782:1373"]))
    assert run.entry == {"status": "not_found", "checked_at": SEARCHED, "note": "a 2022 programme"}


def news(url, title, highlights=(), date="2026-10-02"):
    return {"url": url, "title": title, "published_date": date, "highlights": list(highlights)}


def test_articles_match_names_with_city_context_and_drop_polls(snapshot):
    results = [
        news("https://www.idnes.cz/praha/a1", "Lídr Jan Hušbauer chce v Praze stavět byty - iDNES.cz"),
        news("https://www.idnes.cz/sport/a2", "Jan Hušbauer vyhrál turnaj"),  # no city: possible namesake
        news("https://www.irozhlas.cz/a3", "Praha sobě představila program", ["Komunální volby v Praze."]),
        news("https://www.novinky.cz/a4", "Průzkum: v Brně vede ANO", ["Václav Trojan a volby v Brně"]),
        news("https://www.novinky.cz/a5", "Starý článek o Praze a Janu Hušbauerovi", date="2026-08-01"),
        news("https://www.facebook.com/a6", "Jan Hušbauer v Praze"),
        news("https://www.seznamzpravy.cz/a7", "Kdo povede Brno", ["Lídrem ANO v Brně je Václav Trojan."]),
    ]
    collector = ArticleCollector(snapshot, FakeExa(lambda query: results), log=lambda message: None)
    items, stats = collector.run(snapshot.select("all"))
    by_url = {item["url"]: item for item in items}
    assert set(by_url) == {"https://www.idnes.cz/praha/a1", "https://www.irozhlas.cz/a3",
                           "https://www.seznamzpravy.cz/a7"}
    assert by_url["https://www.idnes.cz/praha/a1"]["title"] == "Lídr Jan Hušbauer chce v Praze stavět byty"
    assert by_url["https://www.idnes.cz/praha/a1"]["cands"] == ["c2"]
    assert by_url["https://www.idnes.cz/praha/a1"]["match"] == "title"
    assert by_url["https://www.irozhlas.cz/a3"]["lists"] == ["kv2026:554782:1373"]
    assert by_url["https://www.seznamzpravy.cz/a7"] | {"match": "text", "city_id": "582786"} == \
        by_url["https://www.seznamzpravy.cz/a7"]
    assert stats["poll_or_betting"] == 1 and stats["outside_window_or_undated"] == 1
    assert set(items[0]) == {"id", "url", "title", "outlet", "published_at", "city_id", "cities", "lists", "cands",
                             "match", "matched", "observed_at"}


def test_article_helpers():
    assert published_date(None, "https://www.idnes.cz/volby/usti/x.A261005_10572") == "2026-10-05"
    assert published_date("2026-09-30T00:00:00.000Z", "https://x.cz/") == "2026-09-30"
    assert published_date(None, "https://x.cz/clanek") is None
    assert clean_title("Volby v Ústí: kandidáti a lídři | Česko | Lidovky.cz", "https://www.lidovky.cz/a") == \
        "Volby v Ústí: kandidáti a lídři"
    assert canonical("https://www.idnes.cz/nastaveni-souhlasu?url=https%3A%2F%2Fwww.idnes.cz%2Fa%3Futm_source%3Dx") \
        == "https://www.idnes.cz/a"


def test_js_output_is_byte_stable(tmp_path):
    write_js(tmp_path / "a.js", "SW_X", {"b": 1, "a": {"y": "ž", "x": [2, 1]}})
    write_js(tmp_path / "b.js", "SW_X", {"a": {"x": [2, 1], "y": "ž"}, "b": 1})
    assert (tmp_path / "a.js").read_bytes() == (tmp_path / "b.js").read_bytes()
    assert read_js(tmp_path / "a.js") == {"a": {"x": [2, 1], "y": "ž"}, "b": 1}
