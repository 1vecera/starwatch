"""Canonical migration, revision checks and fail-closed durable outbox boundaries."""

import base64
import concurrent.futures
import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from project_tracker.records import CHIEF_PANE, CHIEF_SESSION, ConflictError, ControlStore, ValidationError


class StoreTests(unittest.TestCase):
    def setUp(self):
        scratch = Path.cwd() / "tmp"
        scratch.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.directory.name).resolve()
        (self.root / "docs").mkdir()
        self.original = (
            "# TODO\n\nKeep unrelated prose.\n\n## Build\n- [ ] Original **prose** "
            "[evidence](https://example.com)\n\n## Done\n- [x] Existing completion\n"
        )
        (self.root / "TODO.md").write_text(self.original)
        (self.root / "docs/learnings.md").write_text("# Learnings\nExisting history.\n")
        (self.root / "tmp/project-tracker").mkdir(parents=True)
        (self.root / "tmp/project-tracker/inbox.jsonl").write_text('{"text":"legacy"}\n')
        self.store = ControlStore(self.root)
        self.store.project.snapshot = lambda: {"workers": []}
        self.chief = {
            "pane_id": CHIEF_PANE,
            "session_id": CHIEF_SESSION,
            "status": "working",
            "observed_at": "now",
            "connection": "verified",
            "error": None,
        }
        self.store.chief = lambda refresh=False: dict(self.chief)
        self.store.migrate()

    def tearDown(self):
        self.directory.cleanup()

    def state(self):
        return self.store.snapshot(observe=False)

    def mutate(self, op, *, browser_intent=False, **fields):
        return self.store.mutate(
            {"op": op, "base_revision": self.state()["revision"], **fields}, browser_intent=browser_intent
        )

    def test_migration_preserves_history_legacy_notes_and_stable_ids(self):
        body = (self.root / "TODO.md").read_text()
        self.assertIn("Original **prose** [evidence](https://example.com)", body)
        self.assertIn("Keep unrelated prose.", body)
        self.assertEqual((self.root / "docs/learnings.md").read_text(), "# Learnings\nExisting history.\n")
        self.assertEqual((self.root / "tmp/project-tracker/inbox.jsonl").read_text(), '{"text":"legacy"}\n')
        self.assertFalse(self.store.migrate()["migrated"])
        tasks = self.state()["tasks"]
        self.mutate("task.move", id=tasks[0]["id"], status="doing")
        self.assertEqual(self.state()["tasks"][0]["id"], tasks[0]["id"])
        self.assertTrue(list((self.root / "tmp/control-room/backups").glob("*/TODO.md")))

    def test_product_save_keeps_exact_markdown_backup_and_rejects_external_file_conflict(self):
        path = self.root / "docs/product-state.md"
        original = "# Product\n\nExact trailing spaces.  \n"
        path.write_text(original)
        before = self.state()
        # Unrelated task progress must not invalidate a product-file edit.
        self.mutate("task.move", id=before["tasks"][0]["id"], status="doing")
        result = self.store.mutate(
            {
                "op": "product.save",
                "actor": "hos-control",
                "base_version": before["product"]["version"],
                "markdown": "# Daniel's saved page\n\nNew text.  \n",
            },
            require_revision=True,
        )
        self.assertEqual(path.read_text(), result["state"]["product"]["markdown"])
        self.assertEqual((self.root / result["result"]["previous_version"]).read_text(), original)
        version = result["state"]["product"]["version"]
        path.write_text("# Agent file edit\n")
        self.assertNotEqual(self.state()["revision"], result["state"]["revision"])
        with self.assertRaises(ConflictError):
            self.store.mutate({"op": "product.save", "base_version": version, "markdown": "A stale draft"})
        self.assertEqual(path.read_text(), "# Agent file edit\n")
        self.assertTrue(self.state()["communication"]["quiet"])

    def test_product_same_version_writers_have_one_winner(self):
        version = self.state()["product"]["version"]

        def write(markdown):
            try:
                self.store.mutate({"op": "product.save", "base_version": version, "markdown": markdown})
                return "saved"
            except ConflictError:
                return "conflict"

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(write, ["First draft", "Second draft"]))
        self.assertCountEqual(outcomes, ["saved", "conflict"])

    def test_product_bounds_and_symlinks_do_not_allow_other_file_writes(self):
        version = self.state()["product"]["version"]
        for extra in [{"path": "TODO.md"}, {"markdown": "é" * 24_001}, {"markdown": "Bad\x00text"}]:
            with self.assertRaises(ValidationError):
                self.store.mutate({"op": "product.save", "base_version": version, "markdown": "Valid", **extra})
        (self.root / "docs/product-state.md").symlink_to(self.root / "TODO.md")
        before = (self.root / "TODO.md").read_text()
        self.assertFalse(self.state()["product"]["editable"])
        with self.assertRaises(ValidationError):
            self.store.mutate({"op": "product.save", "base_version": version, "markdown": "Overwrite"})
        self.assertEqual((self.root / "TODO.md").read_text(), before)

    def test_product_interrupted_journal_recovers_file_and_previous_version(self):
        path = self.root / "docs/product-state.md"
        path.write_text("Previous page\n")
        version = self.state()["product"]["version"]
        atomic = self.store.atomic

        def interrupted(relative, body):
            if relative == "TODO.md":
                raise OSError("Simulated interruption after durable journal")
            atomic(relative, body)

        with patch.object(self.store, "atomic", side_effect=interrupted), self.assertRaises(OSError):
            self.store.mutate({"op": "product.save", "base_version": version, "markdown": "Saved page\n"})
        pending = json.loads((self.root / "tmp/control-room/pending.json").read_text())
        self.assertEqual(base64.b64decode(pending["files"]["docs/product-state.md"]), b"Saved page\n")
        self.assertEqual(self.state()["product"]["markdown"], "Saved page\n")
        self.assertEqual((self.root / f"tmp/control-room/product-history/{version}.md").read_text(), "Previous page\n")
        self.assertFalse((self.root / "tmp/control-room/pending.json").exists())

    def test_revision_conflict_and_external_prose_are_preserved(self):
        revision = self.state()["revision"]
        with (self.root / "TODO.md").open("a") as output:
            output.write("\nOutside actor note.\n")
        with self.assertRaises(ConflictError):
            self.store.mutate({"op": "task.create", "title": "Will conflict", "base_revision": revision})
        card = self.mutate("task.create", title="New card", description="Actual editable content")["result"]
        self.assertIn("Outside actor note.", (self.root / "TODO.md").read_text())
        reopened = ControlStore(self.root)
        self.assertEqual(
            next(item for item in reopened.snapshot(observe=False)["tasks"] if item["id"] == card["id"])["description"],
            "Actual editable content",
        )

    def test_decision_choice_logs_history_learnings_and_queues_without_execution(self):
        before = (self.root / "docs/learnings.md").read_text()
        result = self.mutate(
            "decision.choose",
            id="decision-subject",
            choice=None,
            custom_choice="Explicit local subject + anchor",
            rationale="A considered choice",
        )
        self.assertEqual(result["result"]["history"][-1]["actor"], "Daniel")
        self.assertTrue((self.root / "docs/learnings.md").read_text().startswith(before))
        self.assertEqual(result["state"]["messages"][-1]["status"], "held")
        self.assertIn("no selected action was executed", (self.root / "docs/learnings.md").read_text())

    def test_quiet_holds_workers_even_when_they_claim_daniel_and_cannot_be_reopened_by_actor(self):
        before = (self.root / "TODO.md").read_text()
        worker = self.mutate("message.send", actor="Daniel", text="Worker claiming Daniel")["result"]
        self.assertEqual(worker["status"], "held")
        self.assertEqual(worker["delivery_class"], "worker")
        with patch("project_tracker.records.subprocess.run") as run:
            self.assertEqual(self.store.dispatch_pending(), 0)
            run.assert_not_called()
        for operation in (
            {"op": "quiet.set", "enabled": False, "actor": "Daniel"},
            {"op": "message.send", "text": "Forged direct route", "actor": "Daniel", "delivery_class": "direct"},
            {"op": "message.release", "id": worker["id"], "actor": "Daniel"},
        ):
            with self.assertRaises(ValidationError):
                self.store.mutate(operation)
        records = json.loads((self.root / "tmp/control-room/records.json").read_text())
        self.assertTrue(records["communication"]["quiet"])
        self.assertEqual((self.root / "TODO.md").read_text(), before)

    def test_legacy_pending_is_held_and_reopening_does_not_release_history(self):
        self.mutate("quiet.set", enabled=False, browser_intent=True)
        worker = self.mutate("message.send", text="Legacy worker fixture")["result"]
        with self.store.locked():
            todo, records, _ = self.store.load()
            self.store.find(records["messages"], worker["id"]).pop("delivery_class")
            self.store.save(todo, records, {"op": "fixture.legacy"})
        self.mutate("quiet.set", enabled=True, browser_intent=True)
        direct = self.mutate("message.send", actor="Spoofed actor", text="Deliberate fixture", browser_intent=True)
        self.assertEqual(direct["result"]["actor"], "Daniel")
        with patch(
            "project_tracker.records.subprocess.run",
            return_value=CompletedProcess([], 0, '{"result":{"submitted":true}}', ""),
        ) as run:
            self.assertEqual(self.store.dispatch_pending(), 1)
            self.assertEqual(run.call_count, 1)
            held = next(m for m in self.state()["messages"] if m["id"] == worker["id"])
            self.assertEqual(held["status"], "held")
            self.assertIsNone(held["submitted_at"])
            with self.assertRaises(ValidationError):
                self.mutate("message.release", id=worker["id"], browser_intent=True)
            self.mutate("quiet.set", enabled=False, browser_intent=True)
            self.assertEqual(self.store.dispatch_pending(), 0)
            self.assertEqual(run.call_count, 1)
            self.mutate("message.release", id=worker["id"], browser_intent=True)
            self.assertEqual(self.store.dispatch_pending(), 1)
            self.assertEqual(run.call_count, 2)

    def test_architecture_feedback_layout_and_task_comments_persist(self):
        self.mutate("architecture.feedback", id="atlas", text="Refine this actual block")
        self.mutate("architecture.layout", positions=[{"id": "atlas", "x": 44, "y": -10}])
        node = next(item for item in self.state()["architecture"]["nodes"] if item["id"] == "atlas")
        self.assertEqual(node["position"], {"x": 44, "y": -10})
        self.assertEqual(node["data"]["comments"][-1]["text"], "Refine this actual block")
        for invalid_patch in ({"position": {"x": float("inf"), "y": 0}}, {"data": {"status": "fake"}}):
            with self.assertRaises(ValidationError):
                self.mutate("architecture.update", id="atlas", patch=invalid_patch)

    def test_delivery_is_durable_submitted_and_only_explicitly_acknowledged(self):
        message = self.mutate("message.send", text="A harmless fixture ping", browser_intent=True)["result"]
        seen = []

        def deliver(argv, **kwargs):
            saved = json.loads((self.root / "tmp/control-room/records.json").read_text())["messages"][-1]
            self.assertEqual(saved["status"], "queued")
            self.assertTrue(saved["attempt_started_at"])
            self.assertEqual(argv[:4], ["herdr", "agent", "prompt", CHIEF_PANE])
            self.assertNotIn("shell", kwargs)
            seen.append(argv)
            return CompletedProcess(argv, 0, '{"result":{"submitted":true}}', "")

        with patch("project_tracker.records.subprocess.run", side_effect=deliver):
            self.store.dispatch_pending()
        self.assertEqual(len(seen), 1)
        self.assertEqual(self.state()["messages"][-1]["status"], "submitted")
        self.assertIsNone(self.state()["messages"][-1]["acknowledged_at"])
        self.mutate("message.ack", id=message["id"], reply="Explicit fixture reply")
        self.assertEqual(self.state()["messages"][-1]["status"], "acknowledged")

    def test_identity_mismatch_and_interrupted_attempt_fail_without_prompt(self):
        self.mutate("message.send", text="Never deliver to a replacement", browser_intent=True)
        self.chief.update(connection="unavailable", error="Chief identity changed")
        with patch("project_tracker.records.subprocess.run") as run:
            self.store.dispatch_pending()
            run.assert_not_called()
        self.assertEqual(self.state()["messages"][-1]["status"], "failed")
        # Simulate a crash after persisting claim but before observing submission.
        self.mutate("message.send", text="An uncertain attempt", browser_intent=True)
        path = self.root / "tmp/control-room/records.json"
        records = json.loads(path.read_text())
        records["messages"][-1]["attempt_started_at"] = "previous-process"
        path.write_text(json.dumps(records))
        with patch("project_tracker.records.subprocess.run") as run:
            self.store.dispatch_pending(recover_interrupted=True)
            run.assert_not_called()
        self.assertEqual(self.state()["messages"][-1]["status"], "failed")

    def test_actual_identity_route_rejects_fixture_cwd(self):
        store = ControlStore(self.root)
        row = {
            "pane_id": CHIEF_PANE,
            "agent_session": {"value": CHIEF_SESSION},
            "cwd": "/different/root",
            "agent": "codex",
            "agent_status": "working",
        }
        with (
            patch.dict("os.environ", {"HERDR_ENV": "1"}),
            patch(
                "project_tracker.records.subprocess.run",
                return_value=CompletedProcess([], 0, json.dumps({"result": {"agent": row}}), ""),
            ),
        ):
            self.assertEqual(store.chief(refresh=True)["connection"], "unavailable")

    def test_progress_and_prior_edits_remain_on_the_card_after_reopen(self):
        card = self.state()["tasks"][0]
        self.mutate("task.update", id=card["id"], patch={"owner": "First owner", "description": "First description"})
        self.mutate("task.update", id=card["id"], patch={"owner": "Second owner", "description": "Revised description"})
        self.mutate("progress.record", task_id=card["id"], text="Verified source evidence", status="review")
        reopened = ControlStore(self.root)
        current = next(t for t in reopened.snapshot(observe=False)["tasks"] if t["id"] == card["id"])
        self.assertEqual(current["owner"], "Second owner")
        self.assertEqual(current["status"], "review")
        self.assertEqual(current["comments"][-1]["text"], "Verified source evidence")
        self.assertTrue(
            any(h["changes"].get("description", {}).get("before") == "First description" for h in current["history"])
        )

    def test_mutation_results_redact_the_same_sensitive_text_as_read_previews(self):
        result = self.mutate(
            "task.create", title="Sensitive preview fixture", description="APIFY_TOKEN=fixture-secret-value"
        )
        self.assertNotIn("fixture-secret-value", json.dumps(result))
        self.assertIn("fixture-secret-value", (self.root / "TODO.md").read_text())

    def test_symlink_records_reject_and_seed_tracks_latest_authorization(self):
        self.assertEqual(
            next(item for item in self.state()["decisions"] if item["id"] == "decision-collection")["choice"], "bounded"
        )
        target = self.root / "outside.txt"
        target.write_text("unchanged")
        path = self.root / "tmp/control-room/records.json"
        path.unlink()
        path.symlink_to(target)
        with self.assertRaises(ValidationError):
            self.store.snapshot()
        self.assertEqual(target.read_text(), "unchanged")


if __name__ == "__main__":
    unittest.main()
