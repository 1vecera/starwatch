"""Find each list's own 2026 programme and keep promises whose quote is found verbatim.

Phases (each cached, so an interrupted run resumes where it stopped):

1. discover: two Exa searches per list; drop social, news and registry hosts.
2. fetch: plain HTTP GET of every candidate, plus "programme" links found on those pages.
3. render: candidates that look like a programme but yield almost no text over HTTP go to one
   batched Apify Website Content Crawler run.
4. triage: a small model picks which candidates are this list's programme for this city.
5. extract: a strong model writes a neutral summary and proposes promises with Czech quotes;
   a promise survives only if its quote is found in the fetched text (see ``text.find_quote``).
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .common import BudgetExceeded, OfflineMiss, digest
from .exa import Exa
from .llm import LLM, LLMError
from .names import city_pattern, distinctive_name, parties_in, person_pattern
from .snapshot import ElectionList, Snapshot
from .text import Document, find_quote, registered_domain
from .web import Fetcher, Renderer, canonical

EXCLUDED_DOMAINS = {
    "facebook.com", "fb.com", "instagram.com", "x.com", "twitter.com", "tiktok.com", "youtube.com", "youtu.be",
    "linkedin.com", "threads.net", "wikipedia.org", "wikidata.org", "volby.cz", "gov.cz", "google.com",
    "mapy.cz", "lines.com", "polymarket.com", "kalshi.com", "spotify.com", "apple.com", "flickr.com",
}
# City halls publish registrations and candidate lists, not programmes; third-party guides are not the list's own.
CITY_HALL_DOMAINS = {
    "praha.eu", "brno.cz", "ostrava.cz", "plzen.eu", "usti-nad-labem.cz", "usti.cz", "pardubice.eu", "liberec.cz",
    "hradeckralove.org", "mmhk.cz", "c-budejovice.cz", "olomouc.eu", "volby.cz",
}
THIRD_PARTY_GUIDES = {"programydovoleb.cz", "volimprahu.cz", "volebnikalkulacka.cz", "kohovolit.eu", "demagog.cz"}
NEWS_DOMAINS = {
    "idnes.cz", "lidovky.cz", "novinky.cz", "seznamzpravy.cz", "irozhlas.cz", "rozhlas.cz", "ceskatelevize.cz",
    "denik.cz", "aktualne.cz", "echo24.cz", "forum24.cz", "denikn.cz", "e15.cz", "metro.cz", "blesk.cz",
    "nova.cz", "iprima.cz", "info.cz", "expres.cz", "reflex.cz", "respekt.cz", "ihned.cz", "media24.cz",
    "ceskenoviny.cz", "parlamentnilisty.cz", "novinky.sk", "seznam.cz", "zpravy.aktualne.cz", "tn.cz",
    "brnenskadrbna.cz", "ostravskadrbna.cz", "plzenskadrbna.cz", "libereckadrbna.cz", "olomouckadrbna.cz",
    "budejckadrbna.cz", "hradeckadrbna.cz", "pardubickadrbna.cz", "ustecky.denik.cz", "ostravan.cz",
    "ustionline.cz", "libereckelisty.cz", "kurzy.cz", "euro.cz", "eurozpravy.cz", "super.cz", "ahaonline.cz",
    "cnn.iprima.cz", "zitusti.cz", "mfdnes.cz", "frekvence1.cz", "radiozurnal.cz", "hlidacipes.org",
    # Further outlets seen in the October 2026 news search.
    "drbna.cz", "okraj.cz", "polar.cz", "rej.cz", "salonkyhk.cz", "dvtv.cz", "domacipolitika.cz", "newstream.cz",
    "report.cz", "tvmorava.cz", "telegraph.cz", "nasepraha.cz", "naseplzen.cz", "nasliberec.cz", "plzen.cz",
    "iplzensko.cz", "regionplzen.cz", "regionpraha.cz", "praha4online.cz", "praha5online.cz", "prazskypatriot.cz",
    "pardubiceonline.cz", "hanackenovinky.cz", "hkcity.cz", "denikreferendum.cz", "e-news.cz", "extra.cz",
    "iportal24.cz", "mujrozhlas.cz", "neovlivni.cz", "odkryto.cz", "voxpot.cz", "moderniobec.cz", "medialive.cz",
    "cerstvezpravy.cz", "focuson.cz", "patriotmagazin.cz", "nasepravda.cz", "zdravotnickydenik.cz",
}
PROGRAM_HINT = re.compile(
    r"program|priorit|krok[ůu]|vize|vizi|plán|chceme|slib|řešení|reseni|tem[ay]|pro-[a-z]+|\.pdf", re.I)
PROGRAMME_WORD = re.compile(r"program|priorit|100.krok|vize", re.I)
TOPIC_LABELS = {
    "culture_sport": "culture, sport, leisure, events, heritage",
    "economy_work": "local economy, jobs, business, tourism",
    "education": "schools, kindergartens, education",
    "election_process": "elections, campaigning, voting",
    "environment": "greenery, climate, waste, water, air, energy savings",
    "governance": "city administration, transparency, participation, digital services, anti-corruption",
    "health_social": "health care, social services, seniors, families, disability",
    "housing": "housing, flats, rents",
    "other": "anything else",
    "public_finance": "budget, taxes, fees, debt, financing",
    "public_space": "squares, parks, streets, urban planning, cleanliness",
    "safety": "police, crime, safety",
    "transport": "public transport, roads, parking, cycling",
}
MAX_CANDIDATES = 16
MODEL_CHARS = 90_000
MAX_PROMISES = 8
QUOTE_LIMIT = 300

TRIAGE_SYSTEM = (
    "You check web search results for a public, non-partisan election information site about the Czech "
    "municipal elections of 9-10 October 2026. Decide which documents are the official election programme "
    "of one specific candidate list for one specific city council. Be strict and factual."
)
EXTRACT_SYSTEM = (
    "You prepare neutral, factual summaries of Czech municipal election programmes for a public, "
    "non-partisan information site. You never evaluate, praise or criticise a programme, never infer "
    "anything about voters or candidates, and never invent text: every quote you give must be copied "
    "character for character from the supplied document."
)


@dataclass
class Candidate:
    url: str
    title: str = ""
    snippet: str = ""
    rank: int = 99
    origin: str = "search"  # "search" | "link"
    document: Document | None = None
    error: str | None = None


@dataclass
class ListRun:
    lst: ElectionList
    searched_at: str = ""
    candidates: list[Candidate] = field(default_factory=list)
    selected: list[Candidate] = field(default_factory=list)
    triage_reason: str = ""
    entry: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    error: str | None = None


def _query_name(lst: ElectionList) -> str:
    name = distinctive_name(lst.name) or lst.name
    return name if len(name) <= 80 else name[:80].rsplit(" ", 1)[0]


def search_queries(lst: ElectionList) -> list[str]:
    name = _query_name(lst)
    leader = lst.leaders(1)[0].name if lst.candidates else ""
    return [
        f"volební program {name} {lst.city} komunální volby 2026",
        f"{name} {leader} {lst.city} program pro komunální volby 2026".replace("  ", " "),
    ]


def deep_queries(lst: ElectionList) -> list[str]:
    """Second-pass searches for lists whose first pass found no programme: homepage and priorities."""
    parties = parties_in(lst.name)
    label = distinctive_name(lst.name) or (" ".join(parties) if parties else _query_name(lst))
    return [
        f"{label} {lst.city} 2026",
        f"{label} {lst.city} co chceme pro {lst.city} priority komunální volby",
    ]


def allowed_candidate(url: str) -> bool:
    domain = registered_domain(url)
    host = url.split("/")[2].lower() if "://" in url else ""
    blocked = EXCLUDED_DOMAINS | NEWS_DOMAINS | CITY_HALL_DOMAINS | THIRD_PARTY_GUIDES
    if domain in blocked or host.removeprefix("www.") in blocked:
        return False
    return not re.search(r"\.(?:jpe?g|png|gif|webp|svg|mp4|mp3|zip|docx?|xlsx?)(?:$|\?)", url, re.I)


class ProgramCollector:
    def __init__(self, snapshot: Snapshot, exa: Exa, fetcher: Fetcher, renderer: Renderer | None,
                 triage: LLM, extractor: LLM, workers: int = 4, log=print):
        self.snapshot = snapshot
        self.exa = exa
        self.fetcher = fetcher
        self.renderer = renderer
        self.triage_llm = triage
        self.extract_llm = extractor
        self.workers = workers
        self.log = log

    # Phase 1 ---------------------------------------------------------------------------------
    def discover(self, run: ListRun, deep: bool = False) -> None:
        seen: dict[str, Candidate] = {}
        times = []
        for query in search_queries(run.lst) + (deep_queries(run.lst) if deep else []):
            record = self.exa.search(query, num_results=10)
            times.append(record["searched_at"])
            for rank, item in enumerate(record["results"]):
                url = canonical(item["url"])
                if not allowed_candidate(url):
                    continue
                snippet = (item.get("highlights") or [""])[0]
                if url not in seen:
                    seen[url] = Candidate(url, item.get("title") or "", snippet, rank)
                else:
                    seen[url].rank = min(seen[url].rank, rank)
        run.searched_at = max(times)
        run.candidates = sorted(seen.values(), key=lambda c: (c.rank, c.url))[:12 if deep else 8]

    # Phase 2 ---------------------------------------------------------------------------------
    def fetch(self, runs: list[ListRun]) -> None:
        self.fetcher.fetch_many([c.url for run in runs for c in run.candidates])
        for run in runs:
            for candidate in run.candidates:
                self._load(candidate)
        hops: dict[str, list[Candidate]] = {}
        for run in runs:
            known = {c.url for c in run.candidates}
            added: list[Candidate] = []
            for candidate in run.candidates[:5]:
                if not candidate.document:
                    continue
                base = registered_domain(candidate.url)
                picked = 0
                for href, text in candidate.document.links:
                    url = canonical(href)
                    if url in known or not url.startswith("http") or not allowed_candidate(url):
                        continue
                    same_site = registered_domain(url) == base
                    if not (PROGRAM_HINT.search(text) or (same_site and PROGRAM_HINT.search(url.split("/", 3)[-1]))):
                        continue
                    if not same_site and not url.lower().endswith(".pdf"):
                        continue
                    known.add(url)
                    added.append(Candidate(url, text, "", 50 + len(added), "link"))
                    picked += 1
                    if picked >= 6:
                        break
            hops[run.lst.id] = added[: MAX_CANDIDATES - len(run.candidates)]
        self.fetcher.fetch_many([c.url for added in hops.values() for c in added])
        for run in runs:
            for candidate in hops[run.lst.id]:
                self._load(candidate)
            run.candidates = _distinct(run.candidates + hops[run.lst.id])

    def _load(self, candidate: Candidate) -> None:
        meta = self.fetcher.meta(candidate.url)
        candidate.error = meta.get("error")
        candidate.document = self.fetcher.document(candidate.url)

    # Phase 3 ---------------------------------------------------------------------------------
    def render(self, runs: list[ListRun]) -> None:
        need = []
        for run in runs:
            for candidate in run.candidates:
                thin = candidate.document is None or candidate.document.chars < 600
                hinted = PROGRAM_HINT.search(candidate.url.split("/", 3)[-1]) or PROGRAM_HINT.search(candidate.title)
                if thin and hinted and not candidate.url.lower().endswith(".pdf"):
                    need.append(candidate)
        if not need or self.renderer is None:
            return
        try:
            self.renderer.render([c.url for c in need])
        except (BudgetExceeded, OfflineMiss) as error:
            self.log(f"render skipped: {error}")
        for candidate in need:
            candidate.document = self.fetcher.document(candidate.url)

    # Phase 4 ---------------------------------------------------------------------------------
    def triage(self, run: ListRun) -> None:
        usable = [c for c in run.candidates if c.document and c.document.chars >= 200]
        if not usable:
            run.triage_reason = "no readable candidate"
            return
        lines = []
        for index, candidate in enumerate(usable, 1):
            text, _ = candidate.document.for_model(1200)
            lines.append(
                f"<candidate id=\"{index}\">\nurl: {candidate.url}\nformat: {candidate.document.format}\n"
                f"title: {candidate.document.title or candidate.title}\nlength: {candidate.document.chars} chars\n"
                f"beginning:\n{text}\n</candidate>"
            )
        leaders = ", ".join(c.name for c in run.lst.leaders(3))
        prompt = (
            f"City: {run.lst.city}\nCandidate list (official ballot name): {run.lst.name}\n"
            f"Leading candidates: {leaders}\n\n"
            "Which candidates are the official 2026 municipal election programme of THIS list for THIS city, "
            "published by the list itself or its party/movement (its own website, PDF or programme page)? "
            "Reject: news or media articles, other cities, other lists, earlier elections (2022 or before), "
            "national or regional programmes that are not specific to this city, regional (krajské) "
            "elections, programmes for a single city district (městský obvod / městská část) rather than the "
            "whole city council, pages that only list candidates, third-party programme aggregators, and "
            "city-hall pages. A page that contains a substantial "
            "part of the programme (for example one chapter, or a homepage with the programme points) counts.\n"
            "Return the ids of matching candidates, most complete first, at most 3, all from the same publisher. "
            "Return an empty list when none matches.\n\n" + "\n\n".join(lines)
        )
        schema = {
            "type": "object",
            "properties": {
                "selected": {"type": "array", "items": {"type": "integer"}},
                "reason": {"type": "string"},
            },
            "required": ["selected", "reason"],
            "additionalProperties": False,
        }
        answer = self.triage_llm.json(system=TRIAGE_SYSTEM, prompt=prompt, schema=schema, max_tokens=600,
                                      tag=f"triage {run.lst.id}")
        run.triage_reason = answer.get("reason", "")
        picked = []
        for index in answer.get("selected", []):
            if isinstance(index, int) and 1 <= index <= len(usable) and usable[index - 1] not in picked:
                picked.append(usable[index - 1])
        run.selected = picked[:3]

    # Phase 5 ---------------------------------------------------------------------------------
    def extract(self, run: ListRun) -> None:
        lst = run.lst
        if not run.selected:
            run.entry = self._missing(run)
            return
        documents = [c.document for c in run.selected]
        if not any(names_city_or_leader(lst, document) for document in documents):
            run.triage_reason = "rejected: the selected pages name neither the city nor a leading candidate"
            run.entry = self._missing(run)
            return
        per_doc = MODEL_CHARS // len(documents)
        blocks, truncated = [], False
        for index, document in enumerate(documents, 1):
            text, cut = document.for_model(per_doc)
            truncated |= cut
            blocks.append(f"<document id=\"{index}\" url=\"{document.url}\" format=\"{document.format}\">\n"
                          f"{text}\n</document>")
        topics = "\n".join(f"- {label}: {hint}" for label, hint in TOPIC_LABELS.items())
        prompt = (
            f"City: {lst.city}\nCandidate list (official ballot name): {lst.name}\n\n"
            + "\n\n".join(blocks)
            + "\n\nTasks:\n"
            "1. is_program: true only if the documents contain the 2026 municipal election programme of THIS "
            "list for THIS city council, published by the list or its party. False for news articles, other "
            "cities or lists, earlier elections, regional elections, or programmes not specific to this city.\n"
            "2. program_title: the programme's own title as written in Czech (at most 80 characters), or a "
            "short descriptive Czech title.\n"
            "3. summary: ONE neutral English sentence (at most 35 words) naming the programme's main focus "
            "areas, for the whole city (not a district). No evaluation, no claims about feasibility or "
            "popularity.\n"
            "4. promises: up to 10 concrete commitments (a specific action, project, number or measurable "
            "target) for the whole city, most specific first, covering different topics. Skip values, slogans, "
            "vague aims, and commitments that only concern one city district.\n"
            "   - quote: a contiguous Czech excerpt copied character for character from the document that "
            "states this commitment, at most 280 characters. Do not fix typos, do not shorten with "
            "ellipses, do not join separate passages, do not include [[page N]] markers, and start at the "
            "beginning of a sentence rather than with a heading.\n"
            "   - text: a neutral English paraphrase of the quote only, at most 160 characters, starting with "
            "a verb (e.g. \"Build 500 municipal rental flats by 2030\"). State nothing that the quote itself "
            "does not say (no numbers, names or details from elsewhere in the document). Write in English; "
            "keep proper names of places, projects and institutions as written.\n"
            "   - document: the id of the document the quote comes from.\n"
            f"   - topic: one of these labels, or \"none\" when unclear:\n{topics}\n"
        )
        schema = {
            "type": "object",
            "properties": {
                "is_program": {"type": "boolean"},
                "reason": {"type": "string"},
                "program_title": {"type": "string"},
                "summary": {"type": "string"},
                "promises": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "document": {"type": "integer"},
                            "quote": {"type": "string"},
                            "text": {"type": "string"},
                            "topic": {"type": "string", "enum": [*TOPIC_LABELS, "none"]},
                        },
                        "required": ["document", "quote", "text", "topic"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["is_program", "reason", "program_title", "summary", "promises"],
            "additionalProperties": False,
        }
        try:
            answer = self.extract_llm.json(system=EXTRACT_SYSTEM, prompt=prompt, schema=schema, max_tokens=6000,
                                           tag=f"extract {lst.id}")
        except LLMError as error:
            run.entry = self._missing(run, note=f"extraction failed: {error}")
            return
        if not answer.get("is_program"):
            run.triage_reason = f"rejected at extraction: {answer.get('reason', '')}"
            run.entry = self._missing(run)
            return
        promises, stats = verify_promises(answer.get("promises", []), documents, self.snapshot.topics)
        stats["model_input_truncated"] = truncated
        first = documents[0]
        run.stats = stats
        run.entry = {
            "status": "found",
            "program_url": first.url,
            "program_title": answer.get("program_title", "").strip() or first.title,
            "format": first.format,
            "fetched_at": first.fetched_at,
            "summary": answer.get("summary", "").strip(),
            "summary_model": self.extract_llm.model,
            "promises": promises,
            "sources": [{"url": d.url, "format": d.format, "fetched_at": d.fetched_at, "via": d.via}
                        for d in documents],
            "checked_at": run.searched_at,
        }

    def _missing(self, run: ListRun, note: str | None = None) -> dict:
        """``unreachable`` when a programme-looking page could not be read, else ``not_found``."""
        for candidate in run.candidates:
            named = PROGRAMME_WORD.search(candidate.url.split("/", 3)[-1]) or PROGRAMME_WORD.search(candidate.title)
            if named and candidate.document is None and candidate.error and candidate.origin == "search":
                meta = self.fetcher.meta(candidate.url)
                return {"status": "unreachable", "program_url": candidate.url, "error": candidate.error,
                        "fetched_at": meta.get("fetched_at"), "checked_at": run.searched_at,
                        "note": note or run.triage_reason}
        return {"status": "not_found", "checked_at": run.searched_at, "note": note or run.triage_reason}

    # Orchestration ----------------------------------------------------------------------------
    def _safe(self, step):
        """Run one phase for one list; a failure drops that list from this run instead of all lists."""
        def wrapped(run: ListRun) -> None:
            if run.error:
                return
            try:
                step(run)
            except (BudgetExceeded, OfflineMiss):
                raise
            except Exception as error:  # noqa: BLE001 - reported, and the list is left out of the output
                run.error = f"{step.__name__}: {type(error).__name__}: {str(error)[:200]}"
                self.log(f"{run.lst.id}: {run.error}")
        return wrapped

    def run(self, lists: list[ElectionList]) -> list[ListRun]:
        """All phases for these lists, then a deeper search for lists still without a programme.

        A list that hits an unexpected error is returned without an entry (and left out of the output).
        """
        runs = [ListRun(lst) for lst in lists]
        self._pass(runs, deep=False)
        retry = [run for run in runs if not run.error and run.entry.get("status") != "found"]
        if retry:
            self._pass(retry, deep=True)
        return runs

    def _pass(self, runs: list[ListRun], deep: bool) -> None:
        previous = {id(run): (run.entry, run.stats, run.triage_reason) for run in runs}
        for run in runs:
            run.selected, run.entry, run.stats = [], {}, {}

        def discover(run: ListRun) -> None:
            self.discover(run, deep=deep)

        with ThreadPoolExecutor(self.workers) as pool:
            list(pool.map(self._safe(discover), runs))
        active = [run for run in runs if not run.error]
        self.log(f"pass {2 if deep else 1}: {sum(len(r.candidates) for r in active)} search candidates "
                 f"for {len(active)} lists")
        self.fetch(active)
        self.render(active)
        with ThreadPoolExecutor(self.workers) as pool:
            list(pool.map(self._safe(self.triage), active))
        with ThreadPoolExecutor(self.workers) as pool:
            list(pool.map(self._safe(self.extract), active))
        for run in runs:
            if run.error and previous[id(run)][0]:  # keep the earlier pass's result
                run.entry, run.stats, run.triage_reason = previous[id(run)]
                self.log(f"{run.lst.id}: keeping first-pass result after {run.error}")
                run.error = None
        self.log(f"pass {2 if deep else 1}: {sum(1 for r in runs if r.entry.get('status') == 'found')} "
                 f"of {len(runs)} lists found")


def names_city_or_leader(lst: ElectionList, document: Document) -> bool:
    """A city programme names its city or its candidates; a generic party text does not."""
    text = "\n".join([document.title, *document.pages])
    if city_pattern(lst.city).search(text):
        return True
    return any((pattern := person_pattern(cand.name)) and pattern.search(text) for cand in lst.leaders(5))


def _distinct(candidates: list[Candidate]) -> list[Candidate]:
    """Drop candidates whose extracted text repeats an earlier one (cache-busting URLs, mirrors)."""
    seen, kept = set(), []
    for candidate in candidates:
        if candidate.document and candidate.document.chars:
            key = digest("\n".join(candidate.document.pages))
            if key in seen:
                continue
            seen.add(key)
        kept.append(candidate)
    return kept


def verify_promises(proposed: list[dict], documents: list[Document], topic_ids: tuple[str, ...]):
    """Keep promises whose quote is found verbatim; return (promises, counts)."""
    by_label = {topic.split(":", 1)[-1]: topic for topic in topic_ids}
    kept, seen = [], set()
    stats = {"proposed": len(proposed), "kept": 0, "dropped_not_found": 0, "dropped_too_long": 0,
             "dropped_duplicate": 0, "dropped_over_limit": 0}
    for item in proposed:
        index = item.get("document", 1)
        order = [index - 1] + [i for i in range(len(documents)) if i != index - 1] \
            if 1 <= index <= len(documents) else list(range(len(documents)))
        match, document = None, None
        for position in order:
            match = find_quote(item.get("quote", ""), documents[position])
            if match:
                document = documents[position]
                break
        if not match:
            stats["dropped_not_found"] += 1
            continue
        if len(match.quote) > QUOTE_LIMIT:
            stats["dropped_too_long"] += 1
            continue
        key = match.quote.rstrip(".!?")
        if key in seen:
            stats["dropped_duplicate"] += 1
            continue
        if len(kept) >= MAX_PROMISES:
            stats["dropped_over_limit"] += 1
            continue
        seen.add(key)
        text = re.sub(r"\s+", " ", item.get("text", "")).strip()
        if len(text) > 160:
            text = text[:159].rsplit(" ", 1)[0].rstrip(",;:") + "…"
        kept.append({
            "text": text,
            "quote": match.quote,
            "topic": by_label.get(item.get("topic", "none")),
            "source_url": document.source_url(match.page),
        })
    stats["kept"] = len(kept)
    return kept, stats
