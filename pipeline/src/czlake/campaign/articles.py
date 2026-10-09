"""Czech news articles that name a list or a leading candidate together with its city.

Only title, outlet, date, URL and match evidence are kept. Article bodies are never requested:
matching uses the title and Exa's short highlight sentences, which stay in the local cache.
Poll, forecast and betting coverage is dropped (Czech election-silence rules and project scope).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from unidecode import unidecode

from .common import sha1
from .exa import Exa
from .names import (brand_pattern, city_pattern, distinctive_name, parties_in, party_pattern,
                    person_pattern)
from .programs import EXCLUDED_DOMAINS
from .snapshot import ElectionList, Snapshot
from .text import registered_domain
from .web import canonical

WINDOW_START = "2026-09-01"
WINDOW_END = "2026-10-09"
LEADING_POSITIONS = 5
# Polls, forecasts, betting and vote counts are dropped (election silence and project scope).
POLL_OR_BETTING = re.compile(
    r"průzkum|volební model|preferenc|sázk|sázen|kurz[yůu]? |odds|prediction|polymarket|kalshi|tipsport|fortuna|"
    r"\bSTEM\b|Median|Kantar|\bNMS\b|Ipsos|SANEP|exit poll|odhad výsledk|prognóz|predikc|sečteno",
    re.I,
)
# In titles only: forecasts and result reports (including misdated reports on earlier elections).
FORECAST_TITLE = re.compile(
    r"favorit|šanc\w* (?:vyhrát|na vítězství|zůstat)|vyhrál[aiy]?\b|vyhraje\b|zvítězil|by získal|"
    r"výsledk\w* (?:\w+ )?voleb|kdo vyhraje",
    re.I,
)
# Tag, author, profile and section pages list many articles; they are not articles themselves.
LISTING_URL = re.compile(
    r"/(?:stitky|stitek|tagy|tag|tags|autor|author|kategorie|category|tema|temata|osobnosti|osobnost|rubrika|"
    r"rubriky|hledat|search|archiv)(?:/|$)|\.K\d+$|/(?:novinky|aktuality|zpravy)/?$", re.I)
PARTY_DOMAIN = re.compile(r"^(?:ods|pirati|piratsk|spd|kdu|top09|trikolora|kscm|socdem|motoriste|starostove|"
                          r"svobodni|zeleni|prisaha|stacilo|ano20)")
POLITICAL_CONTEXT = re.compile(
    r"volb|volič|kandid|komunál|zastupitel|primátor|radnic|koalic|lídr|kampa|magistrát|náměst|starost|radní|"
    r"politi|stran[aěyu]\b|hnutí|opozic", re.I)
PARTY_DOMAINS = {
    "ods.cz", "anobudelip.cz", "anobudelepe.cz", "pirati.cz", "spd.cz", "starostove-nezavisli.cz", "kdu.cz",
    "top09.cz", "zeleni.cz", "svobodni.cz", "motoriste.cz", "motoristesobe.cz", "trikolora.cz", "stacilo.cz",
    "kscm.cz", "socdem.cz", "cssd.cz", "prisaha.cz", "spolu.cz",
}
CITY_HALL_DOMAINS = {
    "praha.eu", "brno.cz", "ostrava.cz", "plzen.eu", "usti-nad-labem.cz", "pardubice.eu", "liberec.cz",
    "hradeckralove.org", "c-budejovice.cz", "olomouc.eu", "volby.cz",
}
# Aggregators republish other outlets' stories under new URLs; the original outlet is kept instead.
AGGREGATORS = {"media24.cz", "globe24.cz", "seznam.cz", "newsbeezer.com", "novinky.sk", "zpravy.cz"}
OUTLETS = {
    "idnes.cz": "iDNES.cz", "lidovky.cz": "Lidovky.cz", "novinky.cz": "Novinky.cz",
    "seznamzpravy.cz": "Seznam Zprávy", "irozhlas.cz": "iROZHLAS", "rozhlas.cz": "Český rozhlas",
    "ceskatelevize.cz": "ČT24", "denik.cz": "Deník", "aktualne.cz": "Aktuálně.cz", "echo24.cz": "Echo24",
    "forum24.cz": "FORUM 24", "denikn.cz": "Deník N", "e15.cz": "E15", "metro.cz": "Metro.cz", "blesk.cz": "Blesk",
    "nova.cz": "TN.cz", "iprima.cz": "CNN Prima News", "info.cz": "Info.cz", "expres.cz": "Expres.cz",
    "reflex.cz": "Reflex", "respekt.cz": "Respekt", "ihned.cz": "Hospodářské noviny", "hn.cz": "Hospodářské noviny",
    "ceskenoviny.cz": "ČTK České noviny", "parlamentnilisty.cz": "Parlamentní listy", "media24.cz": "Media24",
    "brnenskadrbna.cz": "Brněnská Drbna", "ostravan.cz": "Ostravan.cz", "ustionline.cz": "Ústí Online",
    "libereckelisty.cz": "Liberecké listy", "zitusti.cz": "Žít Ústí",
}


@dataclass
class Entry:
    """Compiled matchers for one city."""

    city_id: str
    city: str
    city_re: re.Pattern
    cands: list[tuple[str, str, str, re.Pattern]] = field(default_factory=list)  # cand id, list id, name, re
    brands: list[tuple[str, str, re.Pattern]] = field(default_factory=list)  # list id, brand, re
    parties: list[tuple[str, str, re.Pattern]] = field(default_factory=list)  # list id, party, re


def build_index(snapshot: Snapshot) -> list[Entry]:
    entries: dict[str, Entry] = {}
    owners: dict[tuple[str, str], list[str]] = {}
    for lst in snapshot.lists:
        entry = entries.setdefault(lst.city_id, Entry(lst.city_id, lst.city, city_pattern(lst.city)))
        for cand in lst.leaders(LEADING_POSITIONS):
            pattern = person_pattern(cand.name)
            if pattern:
                entry.cands.append((cand.id, lst.id, cand.name, pattern))
        brand = distinctive_name(lst.name)
        if brand:
            entry.brands.append((lst.id, brand, brand_pattern(brand)))
        for party in parties_in(lst.name):
            owners.setdefault((lst.city_id, party), []).append(lst.id)
    for (city_id, party), list_ids in sorted(owners.items()):
        if len(list_ids) == 1:  # a party shared by two lists in one city is ambiguous
            entries[city_id].parties.append((list_ids[0], party, party_pattern(party)))
    return [entries[key] for key in sorted(entries, key=lambda k: entries[k].city)]


@dataclass
class Match:
    city_id: str
    lists: set[str]
    cands: set[str]
    names: set[str]
    in_title: bool
    score: int


def match_article(title: str, text: str, index: list[Entry]) -> list[Match]:
    """Per city: candidates by exact (declined) full name, lists by brand or unique party name.

    Every hit needs the city in the title or highlights. Brand hits, and candidate names found only
    in the highlights, also need political context; party-name hits must be in the title.
    """
    matches = []
    both = f"{title}\n{text}"
    political = bool(POLITICAL_CONTEXT.search(both))
    for entry in index:
        if not entry.city_re.search(both):
            continue
        lists, cands, names, in_title, score = set(), set(), set(), False, 0
        for cand_id, list_id, name, pattern in entry.cands:
            where = "title" if pattern.search(title) else "text" if political and pattern.search(text) else None
            if where:
                cands.add(cand_id)
                lists.add(list_id)
                names.add(name)
                in_title |= where == "title"
                score += 3
        if political:
            for list_id, brand, pattern in entry.brands:
                where = "title" if pattern.search(title) else "text" if pattern.search(text) else None
                if where:
                    lists.add(list_id)
                    names.add(brand)
                    in_title |= where == "title"
                    score += 2
            for list_id, party, pattern in entry.parties:
                if pattern.search(title):
                    lists.add(list_id)
                    names.add(party)
                    in_title = True
                    score += 1
        if lists:
            matches.append(Match(entry.city_id, lists, cands, names, in_title, score))
    return matches


def published_date(value: str | None, url: str) -> str | None:
    """A date written in the URL wins over the search index's date, which is occasionally wrong."""
    found = re.search(r"[./_-]A(\d{2})(\d{2})(\d{2})_", url)  # iDNES/Lidovky article ids: A261005_...
    if found:
        return f"20{found.group(1)}-{found.group(2)}-{found.group(3)}"
    found = re.search(r"/(20\d{2})[/-](\d{2})[/-](\d{2})/", url)
    if found:
        return "-".join(found.groups())
    if value and re.match(r"\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    return None


def outlet_name(url: str) -> str:
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    domain = registered_domain(url)
    return OUTLETS.get(host) or OUTLETS.get(domain) or domain


def clean_title(title: str, url: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    root = registered_domain(url).split(".")[0].lower()
    outlet = outlet_name(url).lower()
    for _ in range(3):
        parts = re.split(r"\s+[|–—-]\s+", title)
        if len(parts) < 2:
            break
        last = parts[-1].lower()
        outlet_suffix = len(last) <= 40 and (root in last or outlet in last or last.replace(" ", "") in root)
        section_suffix = " | " in title and len(last) <= 20 and title.rstrip().endswith(parts[-1])
        if not (outlet_suffix or section_suffix):
            break
        title = title[: title.rfind(parts[-1])].rstrip(" |–—-")
    return title


def allowed_outlet(url: str, extra_excluded: set[str]) -> bool:
    """Czech news pages only: no party, list, candidate, city-hall, aggregator or listing pages."""
    host = (urlsplit(url).hostname or "").lower()
    domain = registered_domain(url)
    if not host.endswith(".cz") or LISTING_URL.search(urlsplit(url).path) or PARTY_DOMAIN.match(domain):
        return False
    return not ({domain, host.removeprefix("www.")} & (EXCLUDED_DOMAINS | PARTY_DOMAINS | CITY_HALL_DOMAINS
                                                       | AGGREGATORS | extra_excluded))


def campaign_domains(snapshot: Snapshot) -> set[str]:
    """Domains spelled like a list brand or a leading candidate's name are campaign sites, not news."""
    names = set()

    def add(text: str) -> None:
        words = re.sub(r"[^a-z0-9 ]", "", unidecode(text).lower()).split()
        if len(words) >= 2 or (words and len(words[0]) >= 6):
            for variant in (words, [words[0], words[-1]]):
                names.update({"".join(variant) + ".cz", "".join(reversed(variant)) + ".cz",
                              "-".join(variant) + ".cz"})

    for lst in snapshot.lists:
        brand = distinctive_name(lst.name)
        if brand:
            add(brand)
        for cand in lst.leaders(LEADING_POSITIONS):
            add(cand.name)
    return names


def article_queries(snapshot: Snapshot, lists: list[ElectionList]) -> list[tuple[str, str, int]]:
    """(query, highlight query, result count), in a fixed order."""
    queries = []
    for city_id in sorted({lst.city_id for lst in lists}, key=lambda c: snapshot.cities[c]):
        city = snapshot.cities[city_id]
        queries.append((f"komunální volby {city} 2026", f"lídr kandidátky {city}", 25))
        queries.append((f"{city} volby 2026 kandidát na primátora lídr", "lídr kandidát primátor", 25))
    for lst in lists:
        brand = distinctive_name(lst.name) or lst.name
        brand = brand if len(brand) <= 80 else brand[:80].rsplit(" ", 1)[0]
        queries.append((f"{brand} {lst.city} komunální volby", brand, 10))
        if lst.candidates:
            leader = lst.candidates[0].name
            queries.append((f"{leader} {lst.city}", leader, 10))
    return queries


class ArticleCollector:
    def __init__(self, snapshot: Snapshot, exa: Exa, extra_excluded: set[str] | None = None, log=print):
        self.snapshot = snapshot
        self.exa = exa
        self.extra_excluded = (extra_excluded or set()) | campaign_domains(snapshot)
        self.index = build_index(snapshot)
        self.log = log

    def run(self, lists: list[ElectionList]) -> tuple[list[dict], dict]:
        stats = {"queries": 0, "results": 0, "unique_urls": 0, "outside_window_or_undated": 0,
                 "not_czech_news": 0, "poll_or_betting": 0, "no_match": 0, "duplicate_titles": 0, "kept": 0}
        merged: dict[str, dict] = {}
        for query, highlight, count in article_queries(self.snapshot, lists):
            record = self.exa.search(query, num_results=count, category="news",
                                     start=f"{WINDOW_START}T00:00:00.000Z", end=f"{WINDOW_END}T23:59:59.999Z",
                                     highlight_query=highlight, sentences=3, per_url=2)
            stats["queries"] += 1
            for result in record["results"]:
                stats["results"] += 1
                url = canonical(result["url"])
                seen = merged.setdefault(url, {"title": result.get("title") or "", "published_date": None,
                                               "highlights": [], "searched_at": record["searched_at"]})
                seen["published_date"] = seen["published_date"] or result.get("published_date")
                seen["highlights"] += [h for h in result.get("highlights") or [] if h not in seen["highlights"]]
                seen["searched_at"] = min(seen["searched_at"], record["searched_at"])
        stats["unique_urls"] = len(merged)
        items = [item for url, result in sorted(merged.items())
                 if (item := self._evaluate(url, result, result["searched_at"], stats))]
        items = self._dedupe_titles(items, stats)
        stats["kept"] = len(items)
        return sorted(items, key=lambda i: (i["published_at"], i["url"]), reverse=True), stats

    def _evaluate(self, url: str, result: dict, searched_at: str, stats: dict) -> dict | None:
        date = published_date(result.get("published_date"), url)
        if not date or not (WINDOW_START <= date <= WINDOW_END):
            stats["outside_window_or_undated"] += 1
            return None
        if not allowed_outlet(url, self.extra_excluded):
            stats["not_czech_news"] += 1
            return None
        title = clean_title(result.get("title") or "", url)
        text = " ".join(result.get("highlights") or [])
        if not title or POLL_OR_BETTING.search(title) or POLL_OR_BETTING.search(text) or FORECAST_TITLE.search(title):
            stats["poll_or_betting"] += 1
            return None
        matches = match_article(title, text, self.index)
        if not matches:
            stats["no_match"] += 1
            return None
        order = {entry.city_id: n for n, entry in enumerate(self.index)}
        best = max(matches, key=lambda m: (m.score, -order[m.city_id]))
        return {
            "id": sha1(url),
            "url": url,
            "title": title,
            "outlet": outlet_name(url),
            "published_at": date,
            "city_id": best.city_id,
            "cities": sorted({m.city_id for m in matches}),
            "lists": sorted(set().union(*(m.lists for m in matches))),
            "cands": sorted(set().union(*(m.cands for m in matches))),
            "match": "title" if any(m.in_title for m in matches) else "text",
            "matched": sorted(set().union(*(m.names for m in matches))),
            "observed_at": searched_at,
        }

    @staticmethod
    def _dedupe_titles(items: list[dict], stats: dict) -> list[dict]:
        """Syndicated copies (e.g. iDNES and Lidovky) share a title; keep the earliest, then by URL."""
        best: dict[str, dict] = {}
        for item in sorted(items, key=lambda i: (i["published_at"], i["url"])):
            key = re.sub(r"\W+", " ", item["title"].lower()).strip()
            if key in best:
                stats["duplicate_titles"] += 1
                continue
            best[key] = item
        return list(best.values())
