"""Retained web text is useful source evidence, without fabricated identity edges."""

from __future__ import annotations

import unittest
from copy import deepcopy

import test_production_finish as finish
from test_production_graph import AS_OF, graph, save


class WebTests(unittest.TestCase):
    setUp = finish.FinishTests.setUp
    tearDown = finish.FinishTests.tearDown
    build = finish.FinishTests.build
    export = finish.FinishTests.export
    query = finish.FinishTests.query

    def supplement(self):
        text = "🏠 Same Name discusses housing. This is retained source text, with its speaker unknown."
        url = "https://public.example/programme"
        source = self.root / "retained-extraction.json"
        date = {"source": "article:published_time", "value": "2026-10-08"}
        extraction = {
            "schema_version": 2,
            "source_url": url,
            "final_url": url,
            "fetched_at": AS_OF,
            "title": "Programme source",
            "main_text": text,
            "main_text_sha256": graph.digest(text),
            "explicit_publication_dates": [date],
            "text_truncated": False,
        }
        save(source, extraction)
        asset_id = "web:" + graph.digest(url)
        name = "Same Name"
        start = text.index(name)
        document = {
            "schema_version": "production-web-supplement-v1",
            "publishers": [
                {
                    "publisher_id": "publisher:public-example",
                    "name": "Source organization",
                    "url": "https://public.example",
                    "kind": "publisher",
                }
            ],
            "assets": [
                {
                    "asset_id": asset_id,
                    "url": url,
                    "asset_type": "programme",
                    "public": True,
                    "published_at": date["value"],
                    "publication_evidence": date,
                    "observed_at": AS_OF,
                    "title": extraction["title"],
                    "text": text,
                    "content_sha256": graph.digest(text),
                    "retained_text_path": str(source),
                    "retained_text_sha256": graph.digest(source.read_bytes()),
                    "text_source_pointer": "/main_text",
                    "publisher_id": "publisher:public-example",
                }
            ],
            "relations": [
                {
                    "asset_id": asset_id,
                    "relation": "about",
                    "entity_id": "alice-candidacy",
                    "publisher_id": None,
                    "status": "unknown",
                    "reason": "Exact source name span; identity not independently reviewed.",
                    "source_sha256": graph.digest(text),
                    "evidence_quote": name,
                    "start": start,
                    "end": start + len(name),
                }
            ],
        }
        path = self.root / "web-supplement.json"
        save(path, document)
        return path, source, document

    def test_source_only_web_rows_keep_publisher_subject_and_speaker_unknown(self):
        path, _, _ = self.supplement()
        result = self.export("web", web_supplement=path)
        self.assertEqual(result["counts"]["web_asset"], 1)
        self.assertEqual(result["counts"]["web_relation"], 1)
        self.assertEqual(result["counts"]["claim"], 0)
        self.assertEqual(result["counts"]["verified_assets"], 1)
        self.assertEqual(
            self.query(
                result,
                "SELECT publisher_status,subject_status,speaker_status FROM web_asset",
            ),
            [("unknown", "unknown", "unknown")],
        )
        self.assertEqual(
            self.query(result, "SELECT status FROM web_relation"), [("unknown",)]
        )

    def test_confirmed_web_relation_cannot_bypass_independent_review(self):
        path, _, document = self.supplement()
        self.export("before", web_supplement=path)
        pointer = (self.base / "export/current.json").read_bytes()
        document["relations"][0]["status"] = "confirmed"
        save(path, document)
        with self.assertRaisesRegex(ValueError, "unknown/rejected"):
            self.export("bad-web", web_supplement=path)
        self.assertEqual((self.base / "export/current.json").read_bytes(), pointer)

    def test_original_extraction_hash_and_exact_text_binding_are_required(self):
        path, source, document = self.supplement()
        source.write_text(source.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.build(web_supplement=path)
        document["assets"][0]["retained_text_sha256"] = graph.digest(
            source.read_bytes()
        )
        document["assets"][0]["text"] = "Invented text"
        document["assets"][0]["content_sha256"] = graph.digest("Invented text")
        save(path, document)
        with self.assertRaisesRegex(ValueError, "retained extraction"):
            self.build(web_supplement=path)

    def test_url_title_time_and_date_evidence_cannot_be_rewritten(self):
        path, _, original = self.supplement()
        for change in (
            {
                "url": "https://elsewhere.example/",
                "asset_id": "web:" + graph.digest("https://elsewhere.example/"),
            },
            {"title": "Different title"},
            {"observed_at": "2026-10-08T00:00:00+00:00"},
            {
                "published_at": "2026-01-01",
                "publication_evidence": {"value": "2026-01-01"},
            },
        ):
            with self.subTest(change=change):
                document = deepcopy(original)
                document["assets"][0].update(change)
                save(path, document)
                with self.assertRaises(ValueError):
                    self.build(web_supplement=path)

    def test_unicode_span_and_exact_subject_reference_are_required(self):
        path, _, original = self.supplement()
        for change in (
            {"start": 3},
            {"entity_id": "invented-national-person"},
            {"source_sha256": "0" * 64},
        ):
            with self.subTest(change=change):
                document = deepcopy(original)
                document["relations"][0].update(change)
                save(path, document)
                with self.assertRaises(ValueError):
                    self.build(web_supplement=path)

    def test_named_speaker_or_publisher_identity_is_never_inherited(self):
        path, _, original = self.supplement()
        for change in (
            {"source_statement_speaker": "alice-candidacy"},
            {"publisher_status": "confirmed"},
            {"subject_status": "confirmed"},
        ):
            document = deepcopy(original)
            document["assets"][0].update(change)
            save(path, document)
            with self.assertRaisesRegex(ValueError, "unknowns"):
                self.build(web_supplement=path)

    def test_rejection_date_requires_retained_review_and_has_no_confirmed_edges(self):
        path, _, document = self.supplement()
        document["relations"][0].update(status="rejected", reviewed_at=AS_OF)
        save(path, document)
        with self.assertRaisesRegex(ValueError, "retained review"):
            self.build(web_supplement=path)
        review = self.root / "original-web-review.json"
        save(review, {"decision": "reject", "reason": "Namesake unresolved."})
        document["relations"][0].update(
            review_source_path=str(review),
            review_source_sha256=graph.digest(review.read_bytes()),
        )
        save(path, document)
        rows = self.build(web_supplement=path)
        self.assertEqual(rows["web_relation"][0]["status"], "rejected")
        self.assertTrue(rows["web_relation"][0]["review_source_id"])


if __name__ == "__main__":
    unittest.main()
