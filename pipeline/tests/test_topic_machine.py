"""Machine topic labels: evidence checks, caching, budget and the overlay contract."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from czlake import topic_machine as tm
from czlake.production_labels import TOPICS


class FakeMessages:
    """Answers like the model: a topic for each cue word found, quoting the cue as evidence."""

    CUES = {"tramvaj": "transport", "byty": "housing", "škola": "education", "volte": "election_process"}

    def __init__(self, stop_reason="end_turn", answer=None):
        self.calls = []
        self.stop_reason = stop_reason
        self.answer = answer

    def create(self, **request):
        self.calls.append(request)
        posts = json.loads(request["messages"][0]["content"])
        items = []
        for post in posts:
            words = post["text"].split()
            topics = [{"topic": topic, "evidence": " ".join(words[i:i + 2])}
                      for i, word in enumerate(words) for cue, topic in self.CUES.items() if cue in word.lower()]
            items.append({"id": post["id"], "topics": topics})
        if self.answer is not None:
            items = self.answer(items)
        usage = SimpleNamespace(input_tokens=1000, output_tokens=100, cache_creation_input_tokens=0,
                                cache_read_input_tokens=0)
        content = [SimpleNamespace(type="text", text=json.dumps({"items": items}, ensure_ascii=False))]
        return SimpleNamespace(usage=usage, stop_reason=self.stop_reason, content=content)


def client(messages):
    return SimpleNamespace(messages=messages)


def post(asset_id, text, published_at="2026-10-01T10:00:00+00:00"):
    return {"asset_id": asset_id, "text": text, "sha": tm.text_sha(text), "published_at": published_at}


class Scratch(unittest.TestCase):
    def setUp(self):
        scratch = Path.cwd() / "tmp"
        scratch.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.work = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()


class TaxonomyTests(unittest.TestCase):
    def test_definitions_cover_the_reviewed_taxonomy(self):
        self.assertEqual(set(tm.DEFINITIONS), set(TOPICS))
        self.assertEqual(set(tm.CUES), set(TOPICS))
        self.assertEqual(tm.SCHEMA["properties"]["items"]["items"]["properties"]["topics"]["items"]
                         ["properties"]["topic"]["enum"], tm.ORDER)

    def test_prompt_examples_follow_the_rules_they_teach(self):
        for text, topics in tm.EXAMPLES:
            self.assertLessEqual(len(topics), tm.MAX_TOPICS)
            for topic, evidence in topics:
                self.assertIn(topic, TOPICS)
                self.assertEqual(tm.locate(text, evidence), evidence)
        self.assertNotIn("{", tm.system_prompt().split("Examples")[0].replace("{topics}", ""))


class EvidenceTests(unittest.TestCase):
    TEXT = "Šalina na Lesnou?\n\nBude!  #brno #Doprava 🗳️"

    def test_whitespace_and_case_are_normalised_and_the_post_wording_is_returned(self):
        self.assertEqual(tm.locate(self.TEXT, "šalina NA lesnou? bude!"), "Šalina na Lesnou?\n\nBude!")
        self.assertEqual(tm.locate(self.TEXT, "#doprava"), "#Doprava")
        self.assertEqual(tm.locate(self.TEXT, "„Šalina na Lesnou…“"), "Šalina na Lesnou")
        self.assertEqual(tm.locate(self.TEXT, "#Doprava 🗳"), "#Doprava 🗳️")

    def test_paraphrase_punctuation_only_and_non_strings_are_rejected(self):
        self.assertIsNone(tm.locate(self.TEXT, "tramvaj na Lesnou"))
        self.assertIsNone(tm.locate(self.TEXT, "?!"))
        self.assertIsNone(tm.locate(self.TEXT, None))

    def test_long_phrases_are_cut_to_twelve_words(self):
        text = " ".join(f"slovo{i}" for i in range(20))
        found = tm.locate(text, text)
        self.assertEqual(len(found.split()), tm.MAX_EVIDENCE_WORDS)
        self.assertTrue(text.startswith(found))

    def test_accept_keeps_three_supported_distinct_topics(self):
        text = "Nové byty, tramvaj, škola a park. Volte nás!"
        proposed = [{"topic": "housing", "evidence": "Nové byty"},
                    {"topic": "housing", "evidence": "byty"},
                    {"topic": "weather", "evidence": "park"},
                    {"topic": "transport", "evidence": "trolejbus"},
                    {"topic": "education", "evidence": "škola"},
                    {"topic": "election_process", "evidence": "Volte nás!"},
                    {"topic": "public_space", "evidence": "park"}]
        topics, evidence, dropped = tm.accept(text, proposed)
        self.assertEqual(topics, ["housing", "education", "election_process"])
        self.assertEqual(evidence["housing"], "Nové byty")
        self.assertEqual(dropped, {"duplicate_topic": 1, "unknown_topic": 1, "evidence_not_found": 1,
                                   "over_limit": 1})

    def test_other_is_only_kept_alone(self):
        text = "Změna začíná u nás. Tramvaj do Bystrce!"
        both = [{"topic": "other", "evidence": "Změna začíná u nás."},
                {"topic": "transport", "evidence": "Tramvaj do Bystrce!"}]
        self.assertEqual(tm.accept(text, both)[0], ["transport"])
        self.assertEqual(tm.accept(text, both[:1])[0], ["other"])
        self.assertEqual(tm.accept(text, "not a list")[0], [])


class ClassifyTests(Scratch):
    def test_identical_texts_are_asked_once_and_reruns_are_free(self):
        store = tm.Store(self.work, tm.MODELS["haiku"])
        messages = FakeMessages()
        posts = [post("a", "Nová tramvaj do Líšně"), post("b", "Nová tramvaj do Líšně"), post("c", "Krásný den")]
        stats = tm.classify(posts, store, client(messages), budget=1.0, workers=1, log=lambda _: None)
        self.assertEqual((stats["asked"], stats["answered"], len(messages.calls)), (2, 2, 1))
        self.assertEqual(json.loads(messages.calls[0]["messages"][0]["content"])[0]["text"], "Nová tramvaj do Líšně")
        self.assertEqual(messages.calls[0]["extra_body"], {"temperature": 0})

        again = tm.Store(self.work, tm.MODELS["haiku"])
        stats = tm.classify(posts, again, client(FakeMessages()), budget=1.0, workers=1, log=lambda _: None)
        self.assertEqual(stats["asked"], 0)
        labels, _ = tm.results(posts, [again])
        self.assertEqual(labels["b"].topics, ["transport"])
        self.assertEqual(labels["c"].topics, [])
        ledger = [json.loads(line) for line in again.ledger_path.read_text().splitlines()]
        self.assertEqual(len(ledger), 1)
        self.assertAlmostEqual(ledger[0]["cost_usd"], (1000 * 1.10 + 100 * 5.50) / 1e6)

    def test_budget_stops_before_a_call_that_could_pass_it(self):
        store = tm.Store(self.work, tm.MODELS["sonnet"])
        messages = FakeMessages()
        logs = []
        stats = tm.classify([post("a", "Nová tramvaj")], store, client(messages), budget=0.001, workers=1,
                            log=logs.append)
        self.assertEqual((len(messages.calls), stats["budget_stops"], stats["missing"]), (0, 1, 1))
        self.assertIn("budget", logs[0])

    def test_truncated_answers_split_the_batch_and_missing_ids_are_retried_later(self):
        store = tm.Store(self.work, tm.MODELS["haiku"])
        messages = FakeMessages(stop_reason="max_tokens")
        stats = tm.classify([post("a", "Tramvaj"), post("b", "Byty")], store, client(messages), budget=1.0,
                            workers=1, log=lambda _: None)
        self.assertEqual((len(messages.calls), stats["answered"]), (3, 0))
        dropped = FakeMessages(answer=lambda items: items[:1])
        stats = tm.classify([post("a", "Tramvaj"), post("b", "Byty")], store, client(dropped), budget=1.0,
                            workers=1, log=lambda _: None)
        self.assertEqual((stats["answered"], stats["missing"]), (1, 1))
        self.assertIsNone(store.get("b", tm.text_sha("Byty")))


class ScoreTests(unittest.TestCase):
    def test_agreement_metrics(self):
        gold = {"1": ["transport", "governance"], "2": ["housing"], "3": [], "4": ["education"]}
        machine = {"1": ["transport"], "2": ["housing", "governance"], "3": [], "4": []}
        report = tm.score(gold, machine)
        self.assertEqual(report["per_topic"]["transport"]["precision"], 1.0)
        self.assertEqual(report["per_topic"]["governance"]["recall"], 0.0)
        self.assertEqual(report["micro"], {"precision": 0.6667, "recall": 0.5, "f1": 0.5714})
        self.assertEqual(report["exact_match"], 0.25)
        self.assertEqual(report["any_overlap"], 1.0)
        self.assertEqual(report["per_topic"]["transport"]["kappa"], 1.0)


class ExportTests(Scratch):
    def snapshot(self):
        assets = [
            {"id": "reviewed", "text": "Tramvaj do Bystrce", "topics": ["production-labels-v1:transport"],
             "topic_status": "admitted", "published_at": "2026-10-01T00:00:00+00:00"},
            {"id": "new", "text": "Nová tramvaj do Bystrce", "topics": [], "topic_status": None,
             "published_at": "2026-10-02T00:00:00+00:00"},
            {"id": "old", "text": "Obecní byty pro mladé", "topics": [], "topic_status": None,
             "published_at": "2025-01-02T00:00:00+00:00"},
            {"id": "empty", "text": " ", "topics": [], "topic_status": None, "published_at": None},
        ]
        path = self.work / "real.js"
        path.write_text("window.SW_RAW = " + json.dumps({"assets": assets}, ensure_ascii=False) + ";\n")
        return path

    def seed(self, model, answers):
        store = tm.Store(self.work, tm.MODELS[model])
        store.put([{"key": f"{asset}|{tm.text_sha(text)}", "asset_id": asset, "text_sha256": tm.text_sha(text),
                    "proposed": proposed} for asset, text, proposed in answers])

    def test_overlay_never_covers_reviewed_posts_and_prefers_the_first_model(self):
        snapshot = self.snapshot()
        self.seed("sonnet", [("new", "Nová tramvaj do Bystrce", [{"topic": "transport", "evidence": "nová tramvaj"}]),
                             ("reviewed", "Tramvaj do Bystrce", [{"topic": "transport", "evidence": "Tramvaj"}])])
        self.seed("haiku", [("new", "Nová tramvaj do Bystrce", [{"topic": "housing", "evidence": "Bystrce"}]),
                            ("old", "Obecní byty pro mladé", [{"topic": "housing", "evidence": "Obecní byty"},
                                                               {"topic": "safety", "evidence": "policie"}])])
        out = self.work / "topic-labels.js"
        tm.main(["--snapshot", str(snapshot), "--work", str(self.work), "export", "--out", str(out)])
        raw = out.read_text()
        self.assertTrue(raw.startswith("/*") and "window.SW_TOPIC_LABELS = " in raw)
        document = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        self.assertEqual(set(document["labels"]), {"new", "old"})
        self.assertEqual(document["labels"]["new"], {
            "topics": ["production-labels-v1:transport"],
            "evidence": {"production-labels-v1:transport": "Nová tramvaj"}, "model": "sonnet"})
        self.assertEqual(document["labels"]["old"]["topics"], ["production-labels-v1:housing"])
        self.assertEqual(document["labels"]["old"]["model"], "haiku")
        self.assertEqual(set(document["taxonomy"]), {f"production-labels-v1:{t}" for t in TOPICS})
        self.assertEqual(document["coverage"]["eligible"], 2)
        self.assertEqual(document["coverage"]["dropped"], {"evidence_not_found": 1})
        self.assertEqual(document["models"]["haiku"]["published"], ["2025-01-02", "2025-01-02"])
        self.assertEqual(document["validation"]["sonnet"]["per_topic"]["transport"]["recall"], 1.0)
        self.assertIn("reviewed labels win", document["method"])


if __name__ == "__main__":
    unittest.main()
