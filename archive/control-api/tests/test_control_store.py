"""Canonical migration, revision checks and fail-closed durable outbox boundaries."""

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
        self.original = "# TODO\n\nKeep unrelated prose.\n\n## Build\n- [ ] Original **prose** [evidence](https://example.com)\n\n## Done\n- [x] Existing completion\n"
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

    def mutate(self, op, **fields):
        return self.store.mutate({"op": op, "base_revision": self.state()["revision"], **fields})

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
        self.assertEqual(result["state"]["messages"][-1]["status"], "queued")
        self.assertIn("no selected action was executed", (self.root / "docs/learnings.md").read_text())

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
        message = self.mutate("message.send", text="A harmless fixture ping")["result"]
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
        self.mutate("message.send", text="Never deliver to a replacement")
        self.chief.update(connection="unavailable", error="Chief identity changed")
        with patch("project_tracker.records.subprocess.run") as run:
            self.store.dispatch_pending()
            run.assert_not_called()
        self.assertEqual(self.state()["messages"][-1]["status"], "failed")
        # Simulate a crash after persisting claim but before observing submission.
        self.mutate("message.send", text="An uncertain attempt")
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
