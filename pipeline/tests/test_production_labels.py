import copy
import hashlib
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from czlake.production_labels import (
    VERSION,
    digest,
    freeze_classification_bundle,
    registered_output,
    reviewed_records,
    text_digest,
    validate_labels,
)


class SourceReviewTests(unittest.TestCase):
    def setUp(self):
        self.text = "🏠 Nové byty. Doprava zůstává."
        self.cards = [{"asset_id": "post:1", "text": self.text,
                       "content_sha256": text_digest(self.text), "owner_status": "independently_confirmed"}]
        self.labels = {"schema_version": VERSION, "assignment_id": "classify-1", "session_id": "session-1",
                       "items": [{"asset_id": "post:1", "content_sha256": text_digest(self.text),
                                  "topics": ["housing"], "abstain_reason": None,
                                  "coverage": {"claim_limit": 3, "basis": "supplied_caption_only",
                                               "claims_truncated": False, "omitted_claims_count": 0,
                                               "note": "Supplied caption only."},
                                  "claims": [{"text": "Nové byty.", "start": 2, "end": 12,
                                              "topics": ["housing"], "claim_type": "source_statement",
                                              "speaker_entity_id": None, "speaker_status": "unknown"}]}]}

        self.registry = {"assignments": [
            {"assignment_id": key, "session_id": session, "task_kind": kind, "pane": pane,
             "brief_sha256": "test-hash", "prompt_receipt": {"submitted": True}}
            for key, session, kind, pane in [("classify-1", "session-1", "classification", "w1:p1"),
                                              ("review-2", "session-2", "independent_review", "w1:p2")]]}
        for row in self.registry["assignments"]:
            agent = {"pane_id": row["pane"], "agent_session": {
                "source": "herdr:codex", "value": row["session_id"]}}
            row["prompt_receipt"] = {"agent": agent}
            row["session_binding"] = {"source": "herdr:codex", "pane": row["pane"],
                                      "session_id": row["session_id"], "agent_receipt": agent}

    def review(self, labels):
        return {"schema_version": VERSION, "assignment_id": "review-2", "session_id": "session-2", "submission_sha256": digest(labels),
                "items": [{"asset_id": "post:1", "decision": "accept", "critical_errors": [],
                           "topic_errors": [], "reviewed_claim_indexes": [0], "reason": "Exact source span and supported topic."}]}

    def test_unicode_span_and_independent_review_promote(self):
        self.assertTrue(validate_labels(self.cards, self.labels)["valid"])
        result = reviewed_records(self.cards, self.labels, self.review(self.labels), self.registry)
        self.assertEqual(result["counts"]["verified"], 1)

    def test_wrong_owner_and_invented_speaker_hold_entire_batch(self):
        self.cards[0]["owner_status"] = "unknown"
        self.labels["items"][0]["claims"][0]["speaker_entity_id"] = "public-person:invented"
        result = reviewed_records(self.cards, self.labels, self.review(self.labels), self.registry)
        self.assertTrue(result["batch_hold"])
        self.assertFalse(result["verified"])

    def test_stale_review_cannot_approve_changed_quote(self):
        review = self.review(self.labels)
        altered = copy.deepcopy(self.labels)
        altered["items"][0]["claims"][0]["text"] = "Falešný výrok."
        result = reviewed_records(self.cards, altered, review, self.registry)
        self.assertTrue(result["batch_hold"])
        self.assertFalse(result["verified"])

    def test_same_session_and_critical_review_fail_closed(self):
        review = self.review(self.labels)
        review["session_id"] = "session-1"
        review["items"][0]["critical_errors"] = ["wrong_identity"]
        result = reviewed_records(self.cards, self.labels, review, self.registry)
        self.assertTrue(result["batch_hold"])

    def test_unreviewed_is_not_counted_as_verified(self):
        review = self.review(self.labels)
        review["items"] = []
        result = reviewed_records(self.cards, self.labels, review, self.registry)
        self.assertFalse(result["batch_hold"])
        self.assertEqual(result["counts"]["verified"], 0)
        self.assertEqual(result["counts"]["quarantined"], 1)

    def test_missing_verdict_fields_and_forged_session_are_rejected(self):
        review = self.review(self.labels)
        review["session_id"] = "unregistered-session"
        del review["items"][0]["critical_errors"]
        del review["items"][0]["topic_errors"]
        result = reviewed_records(self.cards, self.labels, review, self.registry)
        self.assertTrue(result["batch_hold"])
        self.assertFalse(result["verified"])

    def test_same_name_unrelated_pane_receipt_cannot_promote(self):
        self.registry["assignments"][0]["session_binding"]["agent_receipt"]["pane_id"] = "w1:unowned"
        result = reviewed_records(self.cards, self.labels, self.review(self.labels), self.registry)
        self.assertTrue(result["batch_hold"])
        self.assertFalse(result["verified"])

    def test_malformed_nested_values_are_rejected_cleanly(self):
        for replacement in (None, [], {"asset_id": []}, {"asset_id": "post:1", "topics": [{}], "claims": [7]}):
            labels = copy.deepcopy(self.labels)
            labels["items"] = [replacement]
            self.assertFalse(validate_labels(self.cards, labels)["valid"])

    def test_packet_can_explicitly_allow_five_claims_and_preserves_truncation(self):
        statements = ["Nové byty.", "Lepší silnice.", "Více parků.", "Čistší ulice.", "Nová škola."]
        self.cards[0]["text"] = " ".join(statements)
        self.cards[0]["content_sha256"] = text_digest(self.cards[0]["text"])
        self.cards[0]["claim_limit"] = 5
        item = self.labels["items"][0]
        item["content_sha256"] = self.cards[0]["content_sha256"]
        item["coverage"].update(claim_limit=5, claims_truncated=True, omitted_claims_count=2)
        original = item["claims"][0]
        item["claims"] = [{**original, "text": statement, "start": self.cards[0]["text"].index(statement),
                           "end": self.cards[0]["text"].index(statement) + len(statement)} for statement in statements]
        self.assertTrue(validate_labels(self.cards, self.labels)["valid"])
        review = self.review(self.labels)
        review["items"][0]["reviewed_claim_indexes"] = list(range(5))
        result = reviewed_records(self.cards, self.labels, review, self.registry)
        self.assertEqual(result["verified"][0]["coverage"]["omitted_claims_count"], 2)

    def test_repeated_quote_cannot_inflate_claim_count(self):
        self.labels["items"][0]["claims"] *= 2
        result = validate_labels(self.cards, self.labels)
        self.assertFalse(result["valid"])
        self.assertIn("duplicate_claim_span", [error["error"] for error in result["errors"]])


class NativeSourceReviewTests(unittest.TestCase):
    def setUp(self):
        # Reuse the exact legacy packet, but exercise native admission with actual
        # coordinator files rather than mock identities or worker-supplied flags.
        SourceReviewTests.setUp(self)
        scratch = Path.cwd() / "tmp"
        scratch.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.registry.update(native_parent_session_id="coordinator-session",
                             native_parent_task_path="/root")
        self.cards_path = self.base / "cards.json"
        self.cards_path.write_text(json.dumps(self.cards, ensure_ascii=False))
        self.cards_hash = hashlib.sha256(self.cards_path.read_bytes()).hexdigest()

    def _native(self, task, kind, document):
        directory = self.base / task
        directory.mkdir()
        brief = directory / "brief.md"
        brief.write_text("Review the exact source packet independently.\n")
        output_kind = "labels" if kind == "classification" else "review"
        output = directory / (output_kind + ".json")
        cards = self.cards_path
        if kind == "classification":
            cards = directory / "cards.json"
            cards.write_bytes(self.cards_path.read_bytes())
        row = {"assignment_id": "native-" + task, "task_path": "/root/" + task,
               "session_id": "native:/root/" + task, "task_kind": kind,
               "parent_session_id": "coordinator-session", "brief": str(brief),
               "brief_sha256": hashlib.sha256(brief.read_bytes()).hexdigest(),
               "cards_path": str(cards), "cards_sha256": self.cards_hash, "output_directory": str(directory),
               "output_path": str(output), "output_kind": output_kind,
               "registered_at": datetime.now(UTC).isoformat(),
               "spawn_receipt": {"task_name": "/root/" + task},
               "session_binding": {"source": "native:collaboration", "task_path": "/root/" + task,
                                   "parent_session_id": "coordinator-session"}}
        document.update(assignment_id=row["assignment_id"], session_id=row["session_id"])
        if kind == "independent_review":
            row["submission_sha256"] = document["submission_sha256"]
        self.registry["assignments"].append(row)
        output.write_text(json.dumps(document, ensure_ascii=False))
        return row

    def _review(self, labels):
        return SourceReviewTests.review(self, labels)

    def _native_pair(self):
        classifier = self._native("classifier", "classification", self.labels)
        review = self._review(self.labels)
        reviewer = self._native("reviewer", "independent_review", review)
        return classifier, reviewer, review

    def test_legacy_classifier_native_reviewer_and_native_pair_promote(self):
        review = self._review(self.labels)
        reviewer = self._native("reviewer", "independent_review", review)
        self.assertEqual(reviewed_records(self.cards, self.labels, review, self.registry)["counts"]["verified"], 1)
        classifier = self._native("classifier", "classification", self.labels)
        review["submission_sha256"] = digest(self.labels)
        reviewer["submission_sha256"] = review["submission_sha256"]
        Path(reviewer["output_path"]).write_text(json.dumps(review))
        self.assertEqual(reviewed_records(self.cards, self.labels, review, self.registry)["counts"]["verified"], 1)
        self.assertEqual(registered_output(Path(classifier["output_path"]), self.registry,
                                           "classification"), self.labels)

    def test_native_receipt_parent_path_kind_and_hash_spoofing_hold(self):
        classifier, reviewer, review = self._native_pair()
        self.assertEqual(reviewed_records(self.cards, self.labels, review, self.registry)["counts"]["verified"], 1)
        attacks = [
            ("spawn_receipt", None), ("spawn_receipt", []),
            ("spawn_receipt", {"task_name": "/root/unregistered"}),
            ("parent_session_id", "another-parent"),
            ("session_binding", {"source": "native:collaboration", "task_path": "/root/reviewer",
                                 "parent_session_id": "another-parent"}),
            ("task_path", "/root/reviewer/descendant"),
            ("task_path", "/root/reviewer/../reviewer"),
            ("session_id", "fabricated-herdr-session"),
            ("output_kind", "labels"), ("task_kind", "classification"),
            ("brief_sha256", "0" * 64), ("brief_sha256", "not-a-hash"),
            ("cards_sha256", None), ("cards_sha256", "0" * 64),
            ("cards_path", str(self.base / "missing-cards.json")), ("submission_sha256", "0" * 64),
            ("registered_at", None), ("registered_at", "2026-10-09T00:00:00"),
            ("registered_at", (datetime.now(UTC) + timedelta(days=1)).isoformat()),
        ]
        for field, value in attacks:
            with self.subTest(field=field, value=value):
                registry = copy.deepcopy(self.registry)
                registry["assignments"][-1][field] = value
                result = reviewed_records(self.cards, self.labels, review, registry)
                self.assertTrue(result["batch_hold"])
                self.assertEqual(result["counts"]["verified"], 0)
        for field in ("assignment_id", "session_id", "task_kind", "task_path", "parent_session_id",
                      "brief", "brief_sha256", "cards_path", "cards_sha256", "output_directory",
                      "output_path", "output_kind", "registered_at", "spawn_receipt",
                      "session_binding", "submission_sha256"):
            with self.subTest(missing=field):
                registry = copy.deepcopy(self.registry)
                del registry["assignments"][-1][field]
                result = reviewed_records(self.cards, self.labels, review, registry)
                self.assertTrue(result["batch_hold"])
                self.assertEqual(result["counts"]["verified"], 0)
        for malformed in (None, {}, {"assignments": None}, {"assignments": [None]}):
            with self.subTest(registry=malformed):
                self.assertTrue(reviewed_records(self.cards, self.labels, review, malformed)["batch_hold"])

    def test_native_tasks_and_isolated_outputs_must_be_independent(self):
        classifier, reviewer, review = self._native_pair()
        for collision in ("task_path", "output_directory", "output_path", "assignment_id"):
            with self.subTest(collision=collision):
                registry = copy.deepcopy(self.registry)
                registry["assignments"][-1][collision] = classifier[collision]
                result = reviewed_records(self.cards, self.labels, review, registry)
                self.assertTrue(result["batch_hold"])
                self.assertFalse(result["verified"])
        duplicate = copy.deepcopy(self.registry)
        duplicate["assignments"].append(copy.deepcopy(reviewer))
        self.assertTrue(reviewed_records(self.cards, self.labels, review, duplicate)["batch_hold"])

    def test_native_output_alias_wrong_file_and_changed_brief_fail(self):
        classifier, reviewer, review = self._native_pair()
        output = Path(reviewer["output_path"])
        copy_path = output.parent / "copy.json"
        copy_path.write_bytes(output.read_bytes())
        alias = output.parent / "alias.json"
        alias.symlink_to(output)
        for path in (copy_path, alias, output.parent / ".." / output.parent.name / output.name):
            with self.subTest(path=str(path)):
                with self.assertRaises(ValueError):
                    registered_output(path, self.registry, "independent_review")
        with self.assertRaises(ValueError):
            registered_output(output, self.registry, "classification")
        Path(reviewer["brief"]).write_text("Changed task authority after registration.\n")
        with self.assertRaises(ValueError):
            registered_output(output, self.registry, "independent_review")

    def test_review_cannot_rebind_changed_canonical_submission(self):
        classifier, reviewer, review = self._native_pair()
        self.labels["items"][0]["topics"] = ["other"]
        Path(classifier["output_path"]).write_text(json.dumps(self.labels))
        review["submission_sha256"] = digest(self.labels)
        Path(reviewer["output_path"]).write_text(json.dumps(review))
        result = reviewed_records(self.cards, self.labels, review, self.registry)
        self.assertTrue(result["batch_hold"])
        self.assertFalse(result["verified"])

    def test_freeze_preserves_legacy_rows_receipts_and_bytes_without_mutating_inputs(self):
        # A real mixed packet is frozen into a new directory; aliases and source
        # mutation cannot silently replace its independently reviewed labels.
        legacy_row = self.registry["assignments"][0]
        directory = self.base / "legacy"
        directory.mkdir()
        brief = directory / "brief.md"
        brief.write_text("Legacy classifier task.\n")
        legacy_row.update(brief=str(brief), brief_sha256=hashlib.sha256(brief.read_bytes()).hexdigest(),
                          cards_sha256=self.cards_hash)
        cards = directory / "cards.json"
        cards.write_bytes(self.cards_path.read_bytes())
        labels = directory / "labels.json"
        labels.write_text(json.dumps(self.labels))
        review = self._review(self.labels)
        reviewer = self._native("reviewer", "independent_review", review)
        reviewer["cards_path"] = str(cards)
        legacy = self.base / "legacy-registry.json"
        native = self.base / "native-registry.json"
        legacy.write_text(json.dumps({"schema_version": "production-workers-v1",
                                      "assignments": self.registry["assignments"][:2]}))
        native.write_text(json.dumps({**{key: self.registry[key] for key in
                                       ("native_parent_session_id", "native_parent_task_path")},
                                     "assignments": [reviewer]}))
        before = {path: path.read_bytes() for path in (legacy, native, labels, Path(reviewer["output_path"]), brief)}
        output = self.base / "frozen"
        batch = {"cards": str(cards), "labels": str(labels), "review": reviewer["output_path"],
                 "packet_id": "reviewed-correction", "supersedes": {"post:1": "f" * 64}}
        result = freeze_classification_bundle(legacy, native, [batch], output)
        combined = json.loads(Path(result["registry"]).read_text())
        self.assertEqual(combined["assignments"][:2], json.loads(before[legacy])["assignments"])
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        packet = json.loads(Path(result["bundle"]).read_text())["packets"][0]
        self.assertEqual(packet["packet_id"], "reviewed-correction")
        self.assertEqual(packet["supersedes"], {"post:1": "f" * 64})
        self.assertEqual(packet["labels_sha256"], hashlib.sha256(before[labels]).hexdigest())
        self.assertEqual(Path(packet["snapshots"]["labels"]).read_bytes(), before[labels])
        self.assertEqual(result["verified"], 1)
        with self.assertRaises(ValueError):
            freeze_classification_bundle(legacy, native, [batch], output)
        invalid = {**batch, "supersedes": {"post:1": "wrong-hash"}}
        with self.assertRaises(ValueError):
            freeze_classification_bundle(legacy, native, [invalid], self.base / "invalid-metadata")
        self.assertFalse((self.base / "invalid-metadata").exists())
        reviewer["cards_sha256"] = "0" * 64
        native.write_text(json.dumps({**{key: self.registry[key] for key in
                                       ("native_parent_session_id", "native_parent_task_path")},
                                     "assignments": [reviewer]}))
        with self.assertRaises(ValueError):
            freeze_classification_bundle(legacy, native, [batch], self.base / "rejected")
        self.assertFalse((self.base / "rejected").exists())


if __name__ == "__main__":
    unittest.main()
