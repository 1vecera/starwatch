"""Machine topic labels for posts that have no reviewed labels.

Claude on Amazon Bedrock labels each post's own text against the 13 topics of the reviewed
``production-labels-v1`` taxonomy. Every label must carry an evidence phrase copied from the post;
a label whose phrase is not found in the text after whitespace and case normalisation is dropped.
Labels describe what a post is about, never its stance, sentiment, author or truth.

Reviewed labels are never changed. The result is a separate overlay
(``window.SW_TOPIC_LABELS`` in ``app/web/data/topic-labels.js``) that the app shows as machine
labels next to reviewed ones. Model answers are cached per asset ID and text hash, so a rerun
costs nothing, and every paid call is written to a spending ledger with a hard budget.

    uv run --with "anthropic[bedrock]>=1.11" python -m czlake.topic_machine \\
        --snapshot ../app/web/data/real.js --work tmp/topics validate --model haiku
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import threading
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .production_labels import TOPICS
from .production_labels import VERSION as TAXONOMY

METHOD_VERSION = "topic-machine-v1"
MAX_TOPICS = 3
MAX_EVIDENCE_WORDS = 12
MAX_POST_CHARS = 2000
ENV_PREFIX = "DAS_ITEM_AWS_BEDROCK__"

# One line each, in the context of Czech municipal politics. The app shows these to readers.
DEFINITIONS: dict[str, str] = {
    "housing": "Housing: flats and houses, rents, municipal and affordable housing, new residential "
               "construction and housing-development areas.",
    "transport": "Transport: public transport (trams, buses, trolleybuses, trains, stations), roads, "
                 "traffic, parking, closures and detours, cycling and walking routes.",
    "environment": "Environment: trees and greenery, climate and heat, air, noise, water and sewerage, "
                   "waste, nature and animals.",
    "public_space": "Public space: squares, streets, parks, playgrounds, pavements, lighting, cleanliness, "
                    "urban planning, architecture and the look of neighbourhoods.",
    "public_finance": "Public finance: the city budget, local taxes and fees, debt, the cost of investments, "
                      "grants and subsidies, public procurement and the use of public money.",
    "education": "Education: nurseries, kindergartens, primary and secondary schools, school capacity and "
                 "buildings, teachers, universities and science.",
    "health_social": "Health and social care: hospitals, doctors, emergency care, social services, seniors, "
                     "disability, families in need, addiction and homelessness.",
    "governance": "Governance and politics: how the city, region and state are run: councils, mayors, "
                  "government and parliament, parties, coalitions and opposition, office holders, laws, "
                  "transparency, corruption and citizen participation.",
    "safety": "Safety: police and municipal police, crime, public order, camera systems, firefighters, "
              "crisis management, road safety, and national security and defence.",
    "culture_sport": "Culture and sport: cultural venues and events, festivals, theatres, music, museums, "
                     "history, heritage and monuments, sport clubs, matches and facilities, leisure events.",
    "economy_work": "Economy and work: jobs and wages, businesses and industry, the local economy, tourism, "
                    "prices, cost of living and energy prices.",
    "election_process": "Election process: the election and campaign itself: dates and voting, calls to vote, "
                        "how to fill in the ballot, candidacies and candidate lists, campaign events, debates "
                        "and results.",
    "other": "Other: clearly political or campaign content with no issue from the twelve topics above, "
             "such as a general slogan or a campaign launch.",
}
assert set(DEFINITIONS) == set(TOPICS), "definitions must cover exactly the reviewed taxonomy"
ORDER = list(DEFINITIONS)

# Czech words that point to each topic. Prompt guidance only; the model still judges context.
CUES: dict[str, str] = {
    "housing": "bydlení, byty, nájem, obecní byty, dostupné bydlení, výstavba bytů, developer",
    "transport": "doprava, MHD, šalina, tramvaj, autobus, trolejbus, vlak, nádraží, silnice, parkování, "
                 "uzavírka, objížďka, kolona, cyklostezka, přechod",
    "environment": "životní prostředí, zeleň, stromy, klima, vedro, ovzduší, hluk, voda, kanalizace, odpady, "
                   "příroda, zvířata",
    "public_space": "veřejný prostor, náměstí, ulice, park, hřiště, chodník, osvětlení, čistota, územní plán, "
                    "architektura, revitalizace",
    "public_finance": "rozpočet, daně, poplatky, dluh, investice, dotace, zakázky, peníze města",
    "education": "škola, školka, jesle, učitelé, žáci, kapacity škol, univerzita, věda",
    "health_social": "nemocnice, lékaři, záchranka, sociální služby, senioři, péče, hendikep, závislosti, "
                     "bezdomovectví",
    "governance": "radnice, vedení města, zastupitelstvo, rada, starosta, primátor, hejtman, vláda, ministr, "
                  "Sněmovna, zákon, strana, koalice, opozice, demokracie, transparentnost, korupce, úřad",
    "safety": "bezpečnost, policie, strážníci, kriminalita, kamery, hasiči, krizové řízení, obrana",
    "culture_sport": "kultura, festival, divadlo, muzeum, památky, historie, koncert, sport, zápas, klub, "
                     "stadion, hala",
    "economy_work": "práce, mzdy, firmy, podnikání, průmysl, ekonomika, turismus, ceny, inflace, energie",
    "election_process": "volby, volte, 9. a 10. října, volební místnost, hlasovací lístek, křížek, kandidátka, "
                        "kandidát, číslo listiny, preferenční hlasy, kampaň, debata, výsledky",
    "other": "obecný kampaňový slogan bez tématu",
}

SYSTEM_PROMPT = """You label public social-media posts by Czech politicians, candidates and party lists, \
collected before the municipal elections (komunální volby) of 9 and 10 October 2026. For each post you \
decide which topics the post is about, using a fixed taxonomy. The topics apply to local, regional and \
national politics alike.

Topics (id: definition; Czech cue words)
{topics}

Rules
1. Label subject matter only. Never label stance, sentiment, tone, the author's character, credibility \
or whether a claim is true. Criticism and praise of the same tram line are both "transport".
2. Give every topic the post discusses, up to 3, the most central first. A topic counts when the post \
says something about it, even in one sentence or a hashtag (#doprava, #bydleni, #volby2026). Leave the \
list empty only when nothing in the post belongs to any topic.
3. For every topic, copy an evidence phrase of 2 to 6 consecutive words exactly as written in the post: \
same words, spelling, diacritics, punctuation and emoji. Never translate, paraphrase, abbreviate or join \
separate parts of the text. If you cannot quote such a phrase, leave the topic out.
4. "governance" covers politics and public administration: decisions and conduct of city, regional and \
national leadership, councils, government and parliament, parties, coalitions and opposition, office \
holders, laws, democracy, transparency and corruption. It does not apply merely because a politician \
wrote the post.
5. "election_process" applies when the post refers to the election or the campaign itself: voting dates, \
calls to vote, how to vote, candidacies, candidate lists and numbers, campaign events, debates, party \
leadership votes and results.
6. Personal posts are labelled by their subject: a hockey match or a concert is "culture_sport", a \
factory visit is "economy_work". Posts with no subject from the taxonomy (greetings, thanks, \
congratulations, holiday wishes, jokes, food, bare links or emoji) get no topics. Use "other" only for \
clearly campaign-generic content with no topic, such as a slogan, and never together with another topic.
7. Never infer sensitive traits of people (religion, ethnicity, health, sexuality, political views of \
private persons). Never estimate support, polls or election outcomes.

Input: a JSON array of posts with "id" and "text". Output: one item per post with the same "id", in the \
same order, and its topics (an empty list when none apply).

Examples (invented posts, not from the data)
{examples}"""

# Invented posts that show the rules at work; none is taken from the collected snapshot.
EXAMPLES: list[tuple[str, list[tuple[str, str]]]] = [
    ("Tramvaj do Bystrce musí jezdit i v noci. Volte číslo 5! #brno",
     [("transport", "Tramvaj do Bystrce musí jezdit"), ("election_process", "Volte číslo 5!")]),
    ("Vláda škrtá peníze na kulturu a ministr mlčí. Tohle si naše divadla nezaslouží.",
     [("culture_sport", "naše divadla nezaslouží"), ("public_finance", "škrtá peníze na kulturu"),
      ("governance", "ministr mlčí")]),
    ("Krásné Vánoce a hodně zdraví v novém roce! 🎄", []),
    ("Dnes jsme s týmem odstartovali kampaň na Náměstí Svobody. Přijďte za námi ke stánku!",
     [("election_process", "odstartovali kampaň")]),
    ("Změna začíná u nás. 💪 #spolecneprobudoucnost", [("other", "Změna začíná u nás.")]),
    ("Večer na hokeji, Kometa vyhrála 4:2! 🏒", [("culture_sport", "Večer na hokeji")]),
    ("Navštívil jsem strojírnu v Kuřimi, která zaměstnává 300 lidí.",
     [("economy_work", "strojírnu v Kuřimi, která zaměstnává")]),
    ("Město za posledních pět let prodalo 120 obecních bytů. Nájmy rostou a mladé rodiny odcházejí.",
     [("housing", "prodalo 120 obecních bytů"), ("governance", "Město za posledních pět let")]),
    ("Rozpočet kraje na příští rok počítá se schodkem 900 milionů. Opozice navrhuje škrtnout drahé kanceláře.",
     [("public_finance", "Rozpočet kraje"), ("governance", "Opozice navrhuje")]),
    ("Kolem hlavního nádraží se lidé večer bojí. Chceme víc strážníků a terénní sociální pracovníky.",
     [("safety", "Chceme víc strážníků"), ("health_social", "terénní sociální pracovníky"),
      ("public_space", "Kolem hlavního nádraží")]),
    ("Ve školce v Lesné chybí 60 míst. Přistavíme pavilon do roku 2028.",
     [("education", "Ve školce v Lesné chybí")]),
    ("Vysadili jsme se sousedy 40 stromů v parku Lužánky 🌳",
     [("environment", "Vysadili jsme se sousedy 40 stromů"), ("public_space", "v parku Lužánky")]),
    ("Jak volit? Máte 45 hlasů, můžete udělat křížek u strany nebo u jednotlivých kandidátů.",
     [("election_process", "Jak volit?")]),
    ("Gratuluji Petrovi ke zvolení předsedou místní organizace strany!",
     [("election_process", "ke zvolení předsedou"), ("governance", "místní organizace strany")]),
    ("https://www.facebook.com/share/abc123", []),
    ("Děkujeme všem, kdo dnes přišli! ❤️", []),
    ("Senioři v Porubě čekají na pečovatelskou službu měsíce. To musíme změnit.",
     [("health_social", "čekají na pečovatelskou službu")]),
    ("Zastupitelstvo dnes schválilo zakázku za 2 miliardy bez soutěže. Kde je transparentnost?",
     [("public_finance", "zakázku za 2 miliardy"), ("governance", "Kde je transparentnost?")]),
    ("Před 80 lety skončila válka. Čest památce obětí. 🇨🇿", [("culture_sport", "Čest památce obětí.")]),
    ("Ceny energií drtí malé živnostníky.", [("economy_work", "Ceny energií drtí malé živnostníky.")]),
    ("Koalice ANO a SPD opět odmítla vydat poslance k trestnímu stíhání.",
     [("governance", "odmítla vydat poslance")]),
    ("Hasiči z Lysé zasahovali u povodní celý víkend. Díky! 🚒", [("safety", "Hasiči z Lysé zasahovali")]),
    ("Plán pro Ostravu 🔖 #ostrava2026", [("other", "Plán pro Ostravu")]),
    ("Dobré ráno z Hostýna ☀️", []),
    ("Uzavírka Husovy ulice potrvá do listopadu, objížďka vede přes Vídeňskou.",
     [("transport", "Uzavírka Husovy ulice")]),
]


def system_prompt() -> str:
    lines = [f"- {key}: {DEFINITIONS[key].split(': ', 1)[1]} [{CUES[key]}]" for key in ORDER]
    examples = "\n".join(
        f"Post: {text}\nTopics: " + json.dumps([{"topic": t, "evidence": e} for t, e in topics], ensure_ascii=False)
        for text, topics in EXAMPLES)
    return SYSTEM_PROMPT.format(topics="\n".join(lines), examples=examples)


SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "topics": {"type": "array", "items": {
                "type": "object",
                "properties": {"topic": {"type": "string", "enum": ORDER}, "evidence": {"type": "string"}},
                "required": ["topic", "evidence"], "additionalProperties": False}},
        },
        "required": ["id", "topics"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False,
}


@dataclass(frozen=True)
class Label:
    topics: list[str]
    evidence: dict[str, str]
    model: str


@dataclass(frozen=True)
class Model:
    key: str
    model_id: str
    name: str
    usd_in: float  # per million input tokens, EU cross-region inference profile (+10 %)
    usd_out: float

    def cost(self, usage: dict) -> float:
        return (usage.get("input_tokens", 0) * self.usd_in
                + usage.get("cache_creation_input_tokens", 0) * self.usd_in * 1.25
                + usage.get("cache_read_input_tokens", 0) * self.usd_in * 0.1
                + usage.get("output_tokens", 0) * self.usd_out) / 1_000_000


MODELS = {
    "haiku": Model("haiku", "eu.anthropic.claude-haiku-4-5-20251001-v1:0", "Claude Haiku 4.5", 1.10, 5.50),
    "sonnet": Model("sonnet", "eu.anthropic.claude-sonnet-4-6", "Claude Sonnet 4.6", 3.30, 16.50),
}


def prompt_digest(model: Model) -> str:
    """Binds cached answers to the exact model, prompt, schema and input limits."""
    blob = json.dumps({"model": model.model_id, "system": system_prompt(), "schema": SCHEMA,
                       "max_chars": MAX_POST_CHARS, "temperature": 0}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# --- evidence ---------------------------------------------------------------------------------

_INVISIBLE = {"\u200b", "\u200c", "\u200d", "\u2060", "\ufe0e", "\ufe0f", "\ufeff"}
_WRAP = " \t\r\n\"'„“”‚‘’«»…"


def _fold(text: str) -> tuple[str, list[int]]:
    """Case-folded text with whitespace runs collapsed, plus each character's index in ``text``."""
    chars: list[str] = []
    index: list[int] = []
    gap = False
    for i, ch in enumerate(text):
        if ch in _INVISIBLE:
            continue
        if ch.isspace():
            gap = bool(chars)
            continue
        if gap:
            chars.append(" ")
            index.append(i)
            gap = False
        for folded in ch.casefold():
            chars.append(folded)
            index.append(i)
    return "".join(chars), index


def locate(text: str, phrase: object) -> str | None:
    """Return the post's own wording of ``phrase`` (at most 12 words), or None if it is not in the text."""
    if not isinstance(phrase, str):
        return None
    text = unicodedata.normalize("NFC", text)
    phrase = unicodedata.normalize("NFC", phrase).strip(_WRAP)
    phrase = re.sub(r"(\.\.\.|…)+$", "", phrase).strip(_WRAP)
    words = phrase.split()
    if not words:
        return None
    needle, _ = _fold(" ".join(words[:MAX_EVIDENCE_WORDS]))
    haystack, index = _fold(text)
    if not needle or not any(ch.isalnum() for ch in needle):
        return None
    position = haystack.find(needle)
    if position < 0:
        return None
    end = index[position + len(needle) - 1] + 1
    while end < len(text) and text[end] in _INVISIBLE:  # keep an emoji's variation selector
        end += 1
    return text[index[position]:end]


def accept(text: str, proposed: object) -> tuple[list[str], dict[str, str], Counter]:
    """Keep at most three known, distinct topics whose evidence is found in the post."""
    topics: list[str] = []
    evidence: dict[str, str] = {}
    dropped: Counter = Counter()
    for entry in proposed if isinstance(proposed, list) else []:
        topic = entry.get("topic") if isinstance(entry, dict) else None
        if topic not in TOPICS:
            dropped["unknown_topic"] += 1
            continue
        if topic in evidence:
            dropped["duplicate_topic"] += 1
            continue
        if len(topics) == MAX_TOPICS:
            dropped["over_limit"] += 1
            continue
        found = locate(text, entry.get("evidence"))
        if found is None:
            dropped["evidence_not_found"] += 1
            continue
        topics.append(topic)
        evidence[topic] = found
    if "other" in evidence and len(topics) > 1:
        dropped["other_with_specific_topic"] += 1
        topics.remove("other")
        del evidence["other"]
    return topics, evidence, dropped


# --- snapshot ---------------------------------------------------------------------------------

def load_snapshot(path: Path) -> dict:
    """Parse ``window.SW_RAW = {...};`` without executing JavaScript."""
    raw = path.read_text(encoding="utf-8")
    return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])


def reviewed(asset: dict) -> bool:
    return asset.get("topic_status") == "admitted"


def post_text(asset: dict) -> str:
    return (asset.get("text") or "").strip()


def gold_topics(asset: dict) -> list[str]:
    return [t.split(":", 1)[1] for t in asset.get("topics") or [] if t.startswith(TAXONOMY + ":")]


# --- cache and ledger -------------------------------------------------------------------------

class Store:
    """Append-only JSONL cache of model answers and a ledger of every paid call."""

    def __init__(self, work: Path, model: Model):
        self.work = work
        self.model = model
        self.digest = prompt_digest(model)
        self.cache_path = work / "cache" / f"{model.key}-{self.digest}.jsonl"
        self.ledger_path = work / "ledger.jsonl"
        self.lock = threading.Lock()
        self.by_key: dict[str, dict] = {}
        self.by_text: dict[str, dict] = {}
        for row in _read_jsonl(self.cache_path):
            self._index(row)
        self._spent = sum(row.get("cost_usd", 0.0) for row in _read_jsonl(self.ledger_path))
        self._reserved = 0.0

    def _index(self, row: dict) -> None:
        self.by_key[row["key"]] = row
        self.by_text.setdefault(row["text_sha256"], row)

    def get(self, asset_id: str, sha: str) -> dict | None:
        return self.by_key.get(f"{asset_id}|{sha}") or self.by_text.get(sha)

    def put(self, rows: list[dict]) -> None:
        with self.lock:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_path.open("a", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    self._index(row)

    def spent(self) -> float:
        return self._spent

    def reserve(self, worst: float, budget: float) -> None:
        """Hold the worst-case cost of a call so parallel calls cannot pass the budget together."""
        with self.lock:
            if self._spent + self._reserved + worst > budget:
                raise BudgetExceeded(f"the next call could pass the ${budget:.2f} budget "
                                     f"(${self._spent:.2f} spent)")
            self._reserved += worst

    def record(self, row: dict, reserved: float) -> None:
        with self.lock:
            self._reserved -= reserved
            self._spent += row["cost_usd"]
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a line cut short by an interrupted run is simply asked again
    return rows


# --- model calls ------------------------------------------------------------------------------

class BudgetExceeded(RuntimeError):
    pass


class Truncated(RuntimeError):
    pass


def bedrock_client():
    import anthropic  # optional dependency: uv run --with "anthropic[bedrock]>=1.11"

    return anthropic.AnthropicBedrock(
        aws_region=os.environ.get(f"{ENV_PREFIX}AWS_REGION") or "eu-central-1",
        aws_access_key=os.environ[f"{ENV_PREFIX}AWS_ACCESS_KEY_ID"],
        aws_secret_key=os.environ[f"{ENV_PREFIX}AWS_SECRET_ACCESS_KEY"],
        max_retries=6,
    )


def _max_tokens(batch: list[dict]) -> int:
    return min(8000, 400 + 160 * len(batch))


def call_batch(client, store: Store, batch: list[dict], budget: float) -> dict[str, list]:
    """Ask the model about one batch; return the raw proposed topics per batch-local ID."""
    payload = json.dumps([{"id": str(i + 1), "text": p["text"][:MAX_POST_CHARS]} for i, p in enumerate(batch)],
                         ensure_ascii=False)
    max_tokens = _max_tokens(batch)
    worst = store.model.cost({"input_tokens": (len(system_prompt()) + len(payload)) // 2,
                              "output_tokens": max_tokens})
    store.reserve(worst, budget)
    try:
        response = client.messages.create(
            model=store.model.model_id, max_tokens=max_tokens,
            system=[{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": payload}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            extra_body={"temperature": 0},  # SDK 1.x dropped the keyword; Claude 4.5/4.6 models accept it
        )
    except BaseException:
        store.record({"at": datetime.now(UTC).isoformat(), "model": store.model.model_id, "failed": True,
                      "cost_usd": 0.0}, worst)
        raise
    usage = {key: getattr(response.usage, key, 0) or 0 for key in
             ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}
    store.record({"at": datetime.now(UTC).isoformat(), "method": METHOD_VERSION, "model": store.model.model_id,
                  "prompt": store.digest, "posts": len(batch), "chars": len(payload), **usage,
                  "cost_usd": round(store.model.cost(usage), 6), "stop_reason": response.stop_reason}, worst)
    if response.stop_reason == "max_tokens":
        raise Truncated(len(batch))
    text = "".join(block.text for block in response.content if block.type == "text")
    items = json.loads(text).get("items", [])
    return {str(item.get("id")): item.get("topics", []) for item in items if isinstance(item, dict)}


def batches(posts: list[dict], size: int, char_budget: int) -> list[list[dict]]:
    out: list[list[dict]] = []
    current: list[dict] = []
    chars = 0
    for post in posts:
        length = min(len(post["text"]), MAX_POST_CHARS)
        if current and (len(current) >= size or chars + length > char_budget):
            out.append(current)
            current, chars = [], 0
        current.append(post)
        chars += length
    if current:
        out.append(current)
    return out


def classify(posts: list[dict], store: Store, client=None, *, budget: float, size: int = 25,
             char_budget: int = 14000, workers: int = 6, log=print) -> dict:
    """Label every post that has no cached answer; reruns make no calls."""
    pending: dict[str, dict] = {}
    for post in posts:
        if store.get(post["asset_id"], post["sha"]) is None:
            pending.setdefault(post["sha"], post)  # identical texts are asked once
    todo = list(pending.values())  # callers order posts by priority (newest first)
    stats = Counter(cached=len(posts) - sum(1 for p in posts if p["sha"] in pending), asked=len(todo))
    if not todo:
        return dict(stats)
    client = client or bedrock_client()

    def run(batch: list[dict]) -> list[dict]:
        try:
            answers = call_batch(client, store, batch, budget)
        except Truncated:
            if len(batch) == 1:
                return []
            half = len(batch) // 2
            return run(batch[:half]) + run(batch[half:])
        rows = []
        for i, post in enumerate(batch):
            proposed = answers.get(str(i + 1))
            if proposed is None:
                continue
            rows.append({"key": f"{post['asset_id']}|{post['sha']}", "asset_id": post["asset_id"],
                         "text_sha256": post["sha"], "proposed": proposed})
        store.put(rows)
        return rows

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run, batch) for batch in batches(todo, size, char_budget)]
        for number, future in enumerate(as_completed(futures), 1):
            try:
                done += len(future.result())
            except BudgetExceeded as error:
                stats["budget_stops"] += 1
                log(f"stopped: {error}")
            if number % 20 == 0:
                log(f"{number}/{len(futures)} batches, {done}/{len(todo)} answered, ${store.spent():.2f} spent")
    stats["answered"] = done
    stats["missing"] = len(todo) - done
    return dict(stats)


def results(posts: list[dict], stores: list[Store]) -> tuple[dict[str, Label], Counter]:
    """Validated labels per asset from the first store (in precedence order) that answered it."""
    labels: dict[str, Label] = {}
    dropped: Counter = Counter()
    for post in posts:
        for store in stores:
            row = store.get(post["asset_id"], post["sha"])
            if row is not None:
                topics, evidence, lost = accept(post["text"], row["proposed"])
                dropped.update(lost)
                labels[post["asset_id"]] = Label(topics, evidence, store.model.key)
                break
        else:
            dropped["no_answer"] += 1
    return labels, dropped


# --- validation -------------------------------------------------------------------------------

def _ratio(a: float, b: float) -> float | None:
    return round(a / b, 4) if b else None


def score(gold: dict[str, list[str]], predicted: dict[str, list[str]]) -> dict:
    """Per-topic and post-level agreement of machine labels with reviewed labels."""
    ids = sorted(set(gold) & set(predicted))
    n = len(ids)
    per_topic = {}
    totals = Counter()
    for topic in ORDER:
        tp = sum(1 for i in ids if topic in gold[i] and topic in predicted[i])
        fp = sum(1 for i in ids if topic not in gold[i] and topic in predicted[i])
        fn = sum(1 for i in ids if topic in gold[i] and topic not in predicted[i])
        tn = n - tp - fp - fn
        precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
        f1 = _ratio(2 * tp, 2 * tp + fp + fn)
        expected = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / (n * n) if n else 0
        kappa = round(((tp + tn) / n - expected) / (1 - expected), 4) if n and expected < 1 else None
        per_topic[topic] = {"reviewed": tp + fn, "machine": tp + fp, "both": tp, "precision": precision,
                            "recall": recall, "f1": f1, "kappa": kappa}
        if topic != "other":
            totals.update(tp=tp, fp=fp, fn=fn)
    all_tp = sum(t["both"] for t in per_topic.values())
    all_fp = sum(t["machine"] - t["both"] for t in per_topic.values())
    all_fn = sum(t["reviewed"] - t["both"] for t in per_topic.values())
    capped = sum(min(len(set(gold[i])), MAX_TOPICS) for i in ids)
    jaccard = [len(set(gold[i]) & set(predicted[i])) / len(set(gold[i]) | set(predicted[i]))
               if set(gold[i]) | set(predicted[i]) else 1.0 for i in ids]
    both = [i for i in ids if gold[i] and predicted[i]]
    f1s = [t["f1"] for t in per_topic.values() if t["f1"] is not None]
    return {
        "posts": n,
        "micro": {"precision": _ratio(all_tp, all_tp + all_fp), "recall": _ratio(all_tp, all_tp + all_fn),
                  "f1": _ratio(2 * all_tp, 2 * all_tp + all_fp + all_fn)},
        "micro_without_other": {"precision": _ratio(totals["tp"], totals["tp"] + totals["fp"]),
                                "recall": _ratio(totals["tp"], totals["tp"] + totals["fn"]),
                                "f1": _ratio(2 * totals["tp"], 2 * totals["tp"] + totals["fp"] + totals["fn"])},
        "macro_f1": round(sum(f1s) / len(f1s), 4) if f1s else None,
        "recall_within_three": _ratio(all_tp, capped),
        "exact_match": _ratio(sum(1 for i in ids if set(gold[i]) == set(predicted[i])), n),
        "mean_jaccard": round(sum(jaccard) / n, 4) if n else None,
        "first_topic_reviewed": _ratio(sum(1 for i in both if predicted[i][0] in gold[i]), len(both)),
        "any_overlap": _ratio(sum(1 for i in both if set(gold[i]) & set(predicted[i])), len(both)),
        "labelled": {"reviewed": sum(1 for i in ids if gold[i]), "machine": sum(1 for i in ids if predicted[i]),
                     "both": len(both)},
        "per_topic": per_topic,
    }


# --- overlay ----------------------------------------------------------------------------------

def topic_id(label: str) -> str:
    return f"{TAXONOMY}:{label}"


def overlay(labels: dict[str, Label], *, models: dict[str, dict], validation: dict, coverage: dict,
            generated_at: str) -> dict:
    used = [m for m in models.values() if m["posts"]]
    scope = "; ".join(f"{m['name']} read {m['posts']} posts published {m['published'][0]} to {m['published'][1]}"
                      for m in used)
    return {
        "generated_at": generated_at,
        "model": ", ".join(m["model"] for m in used),
        "models": models,
        "method": (f"{METHOD_VERSION}: Claude on Amazon Bedrock (temperature 0) read each post's own text "
                   f"(first {MAX_POST_CHARS} characters) and chose up to {MAX_TOPICS} topics from the reviewed "
                   f"{TAXONOMY} taxonomy, each with an evidence phrase copied from the post (at most "
                   f"{MAX_EVIDENCE_WORDS} words); labels whose phrase is not in the post were dropped. {scope}. "
                   "Topics describe what a post is about, not stance or truth. Machine labels can be wrong; "
                   "reviewed labels win."),
        "taxonomy": {topic_id(key): DEFINITIONS[key] for key in ORDER},
        "validation": validation,
        "coverage": coverage,
        "labels": {asset: {"topics": [topic_id(t) for t in label.topics],
                           "evidence": {topic_id(t): label.evidence[t] for t in label.topics},
                           "model": label.model}
                   for asset, label in sorted(labels.items()) if label.topics},
    }


def write_overlay(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("/* Machine topic labels (not reviewed). Reviewed labels in real.js win. */\n"
                         "window.SW_TOPIC_LABELS = " + json.dumps(document, ensure_ascii=False) + ";\n",
                         encoding="utf-8")
    temporary.replace(path)


# --- command line -----------------------------------------------------------------------------

def _posts(assets: list[dict]) -> list[dict]:
    """Posts with text, newest first so a budget stop leaves the oldest posts for later."""
    rows = [{"asset_id": a["id"], "text": post_text(a), "sha": text_sha(post_text(a)),
             "published_at": a.get("published_at") or ""} for a in assets if post_text(a)]
    return sorted(rows, key=lambda p: (p["published_at"], p["asset_id"]), reverse=True)


def _validation(snapshot: dict, store: Store) -> dict:
    gold_assets = [a for a in snapshot["assets"] if reviewed(a) and post_text(a)]
    labels, dropped = results(_posts(gold_assets), [store])
    gold = {a["id"]: gold_topics(a) for a in gold_assets}
    report = score(gold, {asset: label.topics for asset, label in labels.items()})
    report.update(model=store.model.model_id, prompt=store.digest, dropped=dict(dropped),
                  note=(f"Machine labels for the {len(gold_assets)} posts with reviewed {TAXONOMY} labels, "
                        "compared with those labels. Reviewers could give more than three topics and used "
                        "'other' as a catch-all for posts without a public issue; the machine leaves such "
                        "posts unlabelled unless they are campaign-generic."))
    return report


def _print_validation(report: dict) -> None:
    print(json.dumps({k: v for k, v in report.items() if k != "per_topic"}, ensure_ascii=False, indent=1))
    for topic, row in report["per_topic"].items():
        print(f"{topic:17} reviewed {row['reviewed']:4} machine {row['machine']:4} P {row['precision']} "
              f"R {row['recall']} F1 {row['f1']} kappa {row['kappa']}")


def spend_summary(store: Store) -> dict:
    rows = _read_jsonl(store.ledger_path)
    summary = {}
    for model_id in sorted({r["model"] for r in rows}):
        mine = [r for r in rows if r["model"] == model_id]
        summary[model_id] = {"calls": sum(1 for r in mine if not r.get("failed")),
                             "posts": sum(r.get("posts", 0) for r in mine),
                             **{key: sum(r.get(key, 0) for r in mine) for key in (
                                 "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
                                 "output_tokens")},
                             "cost_usd": round(sum(r["cost_usd"] for r in mine), 4)}
    return {"by_model": summary, "total_usd": round(sum(r["cost_usd"] for r in rows), 4)}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot", type=Path, required=True, help="app/web/data/real.js")
    parser.add_argument("--work", type=Path, required=True, help="ignored directory for cache and ledger")
    parser.add_argument("--model", choices=sorted(MODELS), default="sonnet")
    parser.add_argument("--budget", type=float, default=15.0, help="USD cap over the whole ledger")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--batch", type=int, default=25)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="label the reviewed posts and compare with the reviewed labels")
    label = commands.add_parser("label", help="label posts with text that have no reviewed label")
    label.add_argument("--since", help="only posts published on or after this ISO date")
    label.add_argument("--unanswered-by", choices=sorted(MODELS),
                       help="only posts that model has not answered (a cheaper pass over the rest)")
    label.add_argument("--limit", type=int)
    export = commands.add_parser("export", help="write the overlay from cached answers (no model calls)")
    export.add_argument("--out", type=Path, required=True)
    export.add_argument("--models", default="sonnet,haiku", help="answer precedence, comma-separated")
    commands.add_parser("spend", help="tokens and cost per model from the ledger")
    args = parser.parse_args(argv)

    store = Store(args.work, MODELS[args.model])
    if args.command == "spend":
        print(json.dumps(spend_summary(store), indent=1))
        return
    snapshot = load_snapshot(args.snapshot)
    if args.command == "validate":
        posts = _posts([a for a in snapshot["assets"] if reviewed(a)])
        print(classify(posts, store, budget=args.budget, size=args.batch, workers=args.workers))
        report = _validation(snapshot, store)
        path = args.work / f"validation-{store.model.key}-{store.digest}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        _print_validation(report)
        print(f"spent ${store.spent():.4f}; report {path}")
        return
    pool = _posts([a for a in snapshot["assets"] if not reviewed(a)])
    if args.command == "label":
        posts = [p for p in pool if not args.since or p["published_at"] >= args.since]
        if args.unanswered_by:
            other = Store(args.work, MODELS[args.unanswered_by])
            posts = [p for p in posts if other.get(p["asset_id"], p["sha"]) is None]
        posts = posts[:args.limit] if args.limit else posts
        print(classify(posts, store, budget=args.budget, size=args.batch, workers=args.workers))
        print(f"spent ${store.spent():.4f}")
        return
    stores = [Store(args.work, MODELS[key]) for key in args.models.split(",")]
    labels, dropped = results(pool, stores)
    published = {p["asset_id"]: p["published_at"][:10] for p in pool}
    models = {}
    for s in stores:
        mine = sorted(published[a] for a, label in labels.items() if label.model == s.model.key)
        models[s.model.key] = {"model": s.model.model_id, "name": s.model.name, "prompt": s.digest,
                               "posts": len(mine), "labelled": sum(1 for label in labels.values()
                                                                   if label.model == s.model.key and label.topics),
                               "published": [mine[0], mine[-1]] if mine else None}
    counts = Counter(t for label in labels.values() for t in label.topics)
    coverage = {"assets": len(snapshot["assets"]), "reviewed": sum(1 for a in snapshot["assets"] if reviewed(a)),
                "eligible": len(pool), "answered": len(labels),
                "labelled": sum(1 for label in labels.values() if label.topics),
                "per_topic": {topic_id(k): counts.get(k, 0) for k in ORDER}, "dropped": dict(dropped),
                "spend": spend_summary(stores[0])}
    validation = {s.model.key: _validation(snapshot, s) for s in stores}
    document = overlay(labels, models=models, validation=validation, coverage=coverage,
                       generated_at=datetime.now(UTC).replace(microsecond=0).isoformat())
    write_overlay(args.out, document)
    print(json.dumps({k: v for k, v in coverage.items() if k != "spend"}, indent=1))
    print(json.dumps(models, indent=1))
    sample = random.Random(9).sample(sorted(document["labels"]), min(5, len(document["labels"])))
    for asset in sample:
        print(asset, json.dumps(document["labels"][asset], ensure_ascii=False))


if __name__ == "__main__":
    main()
