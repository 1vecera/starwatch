"""Offline behavioral checks: readiness, routing and a durable single dispatch."""

import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from project_tracker import data_ready_watch as watch

MAIN = "historical Message @general-purpose\n❯\n────────────────\n ● main\n ◯ general-purpose\n"
QUEUED = MAIN.replace("❯", "❯ Press up to edit queued messages")
COLLAPSED = (
    "old ● general-purpose\n❯\n────────────────\n"
    " ⏵⏵ bypass permissions on · 1 shell · esc to interrupt · ← 4 agents · ↓ to manage\n"
)


class FakeHerdr:
    def __init__(self, project):
        self.agent = {
            "agent": "claude",
            "agent_session": {"agent": "claude", "kind": "id", "value": watch.SESSION},
            "cwd": str(project),
            "foreground_cwd": str(project),
            "pane_id": "w6:pMoved",
            "agent_status": "working",
        }
        self.screen = MAIN
        self.sent = []
        self.failure = None
        self.before_send = None

    def agents(self):
        return [self.agent]

    def get(self, pane):
        return copy.deepcopy(self.agent)

    def read(self, pane, source):
        return self.screen

    def send(self, pane, prompt):
        if self.before_send:
            self.before_send()
        self.sent.append((pane, prompt))
        if self.failure:
            raise self.failure
        return json.dumps({"result": {"type": "agent_prompted", "agent": self.agent}})


class WatchTests(unittest.TestCase):
    def setUp(self):
        scratch = Path.cwd() / "tmp"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.project = Path(self.temp.name).resolve()
        self.read = self.project / "tmp/production/read"
        self.directory = self.read / "checkpoints/synthetic-v1"
        self.directory.mkdir(parents=True)
        self.state_dir = self.project / "tmp/production/data-ready-watch"
        areas = [{"area_id": city} for city in watch.CITIES]
        entities, accounts, assets, coverage = [], [], [], []
        for i, city in enumerate(watch.CITIES):
            entities.append({"entity_id": f"list{i}", "kind": "local_list", "area_id": city})
            for n in range(30):
                entities.append(
                    {
                        "entity_id": f"person{i}-{n}",
                        "kind": "current_candidacy",
                        "area_id": city,
                        "qualified": True,
                        "local_role_status": "official_registered_candidacy",
                        "list_id": f"list{i}",
                    }
                )
            accounts.append({"account_id": f"account{i}", "entity_id": f"person{i}-0", "identity_status": "confirmed"})
            for n in range(20 if i < 5 else 0):
                assets.append(
                    {
                        "asset_id": f"asset{i}-{n}",
                        "owner_account_id": f"account{i}",
                        "verification_status": "verified_publication_owner",
                        "text": "UNTRUSTED_SOURCE_TEXT",
                    }
                )
            coverage.append(
                {
                    "area_id": city,
                    "valid_candidacies": 30,
                    "meaningful_candidates": 30,
                    "owned_publications": 20 if i < 5 else 0,
                    "confirmed_person_accounts": 1,
                    "confirmed_list_accounts": 0,
                }
            )
        quality = {
            "status": "passed",
            "checks": dict.fromkeys(watch.QUALITY_CHECKS, 0),
            "claims_admitted": 0,
            "topics_admitted": 0,
        }
        self.data = dict(
            areas=areas,
            entities=entities,
            accounts=accounts,
            assets=assets,
            coverage=coverage,
            claims=[],
            topics=[],
            quality=quality,
        )
        self.publish()
        self.transport = FakeHerdr(self.project)
        self.stops = []

    def tearDown(self):
        self.temp.cleanup()

    def publish(self):
        for name, rows in self.data.items():
            (self.directory / f"{name}.json").write_text(json.dumps(rows))
        (self.directory / "graph.duckdb").write_bytes(b"synthetic database; never opened")
        manifest = {
            "checkpoint_id": "synthetic-v1",
            "schema_version": "starwatch-production-graph/1.0.0",
            "quality": self.data["quality"],
            "counts": {
                "area": 10,
                "verified_accounts": len(self.data["accounts"]),
                "verified_assets": len(self.data["assets"]),
                "claim": 0,
                "topic": 0,
            },
            "files": {},
        }
        for name in watch.EXPORTS:
            path = self.directory / name
            manifest["files"][name] = {"bytes": path.stat().st_size, "sha256": watch.digest(path)}
        (self.directory / "manifest.json").write_text(json.dumps(manifest))
        pointer = {
            "checkpoint_id": "synthetic-v1",
            "schema_version": manifest["schema_version"],
            "manifest": "checkpoints/synthetic-v1/manifest.json",
            "database": "checkpoints/synthetic-v1/graph.duckdb",
            "manifest_sha256": watch.digest(self.directory / "manifest.json"),
        }
        (self.read / "current.json").write_text(json.dumps(pointer))

    def tick(self, deliver=True):
        return watch.tick(self.project, deliver=deliver, transport=self.transport, stop=lambda: self.stops.append(True))

    def ack(self, notification=watch.NOTIFICATION):
        watch.atomic_json(
            self.state_dir / "ack.json",
            {
                "notification_id": notification,
                "session_id": watch.SESSION,
                "checkpoint_id": "synthetic-v1",
                "status": "acknowledged",
            },
        )

    def test_readiness_and_dry_run_do_not_send(self):
        state = self.tick(False)
        self.assertEqual(state["status"], "ready")
        self.assertEqual((state["snapshot"]["candidates"], state["snapshot"]["populated_cities"]), (300, 5))
        self.assertFalse(self.transport.sent)
        self.assertNotIn("UNTRUSTED_SOURCE_TEXT", state["prompt"])
        self.assertIn("sol-app-data.md", state["prompt"])
        self.assertIn("reviewed_pending_promotion", state["prompt"])

    def test_every_file_including_database_must_match(self):
        for filename in sorted(watch.EXPORTS | {"manifest.json"}):
            with self.subTest(filename=filename):
                self.publish()
                with (self.directory / filename).open("ab") as stream:
                    stream.write(b"bad")
                self.assertEqual(self.tick()["status"], "error")
        self.assertFalse(self.transport.sent)

    def test_malformed_pointer_and_building_escape_are_rejected(self):
        for value in (
            "{",
            json.dumps({"checkpoint_id": ".building-v1"}),
            json.dumps({"checkpoint_id": "../../escape"}),
        ):
            (self.read / "current.json").write_text(value)
            self.assertEqual(self.tick()["status"], "error")
        self.assertFalse(self.transport.sent)

    def test_incomplete_and_quality_failing_snapshots(self):
        mutations = [
            lambda d: d["coverage"].pop(),
            lambda d: d["quality"]["checks"].update(false_owned_asset=1),
            lambda d: d["entities"][1].update(qualified=False),
            lambda d: d["assets"][0].update(verification_status="provisional"),
            lambda d: d["accounts"][0].update(identity_status="serp_heuristic"),
        ]
        original = copy.deepcopy(self.data)
        for mutate in mutations:
            self.data = copy.deepcopy(original)
            mutate(self.data)
            self.publish()
            self.assertEqual(self.tick()["status"], "error")
        self.assertFalse(self.transport.sent)

    def test_wrong_session_kind_cwd_and_selected_child_wait_safely(self):
        original = copy.deepcopy(self.transport.agent)
        for field, value in (("agent", "codex"), ("cwd", "/elsewhere"), ("foreground_cwd", "/elsewhere")):
            self.transport.agent = copy.deepcopy(original)
            self.transport.agent[field] = value
            self.assertEqual(self.tick()["status"], "waiting-for-main")
        for field, value in (("value", "wrong-id"), ("kind", "name")):
            self.transport.agent = copy.deepcopy(original)
            self.transport.agent["agent_session"][field] = value
            self.assertEqual(self.tick()["status"], "waiting-for-main")
        self.transport.agent = original
        for screen in (
            MAIN.replace("● main", "◯ main").replace("◯ general-purpose", "● general-purpose"),
            MAIN.replace("❯", "❯ my unfinished draft"),
            MAIN.replace("❯", "❯ Message @general-purpose"),
            "● main\n❯\n────────\n",
            MAIN.replace("❯\n", "❯\nwrapped draft\n"),
        ):
            self.transport.screen = screen
            self.assertEqual(self.tick()["status"], "waiting-for-main")
        self.assertFalse(self.transport.sent)
        self.transport.screen = QUEUED
        self.assertEqual(self.tick()["status"], "submitted")  # Working, queued main does not require idle.
        self.assertEqual(self.transport.sent[0][0], "w6:pMoved")

    def test_repeat_restart_and_exact_ack_never_resend(self):
        self.assertEqual(self.tick()["status"], "submitted")
        (self.read / "current.json").write_text("invalid newer pointer")
        self.assertEqual(self.tick()["status"], "submitted")
        self.ack("wrong-notification")
        self.assertEqual(self.tick()["status"], "submitted")
        self.ack()
        self.assertEqual(self.tick()["status"], "acknowledged")
        self.tick()
        self.assertEqual(len(self.transport.sent), 1)
        self.assertTrue(self.stops)

    def test_uncertain_timeout_and_interrupted_intent_do_not_retry(self):
        self.transport.failure = TimeoutError("ambiguous write")
        self.assertEqual(self.tick()["status"], "uncertain")
        self.transport.failure = None
        self.assertEqual(self.tick()["status"], "uncertain")
        state = watch.load_json(self.state_dir / "state.json")
        state["status"] = "dispatch_intent"
        watch.atomic_json(self.state_dir / "state.json", state)
        self.assertEqual(self.tick()["status"], "uncertain")
        self.ack()
        self.assertEqual(self.tick()["status"], "acknowledged")
        self.assertEqual(len(self.transport.sent), 1)

    def test_done_idle_working_and_both_main_layouts_are_input_ready(self):
        for status in ("done", "idle", "working"):
            for screen in (MAIN, COLLAPSED, COLLAPSED.replace("↓ to manage", "↓ to man…"), QUEUED):
                self.transport.agent["agent_status"] = status
                self.transport.screen = screen
                self.assertEqual(self.tick(False)["status"], "ready")
        for status in ("blocked", "waiting", "unknown"):
            self.transport.agent["agent_status"] = status
            self.assertEqual(self.tick()["status"], "waiting-for-main")
        for screen in (
            COLLAPSED.replace("❯", "❯ Message @design"),
            COLLAPSED + "● design\n",
            COLLAPSED + "◯ general-purpose\n",
            COLLAPSED + "Select an agent\n",
            COLLAPSED.replace("❯", "❯ unfinished draft"),
        ):
            self.transport.agent["agent_status"] = "done"
            self.transport.screen = screen
            self.assertEqual(self.tick()["status"], "waiting-for-main")
        self.assertFalse(self.transport.sent)

    def test_concurrent_tick_observes_lock_and_durable_intent(self):
        entered, release = threading.Event(), threading.Event()
        result = []

        def hold():
            self.assertEqual(watch.load_json(self.state_dir / "state.json")["status"], "dispatch_intent")
            entered.set()
            self.assertTrue(release.wait(5))

        self.transport.before_send = hold
        worker = threading.Thread(target=lambda: result.append(self.tick()))
        worker.start()
        self.assertTrue(entered.wait(5))
        try:
            self.assertEqual(self.tick()["status"], "busy")
        finally:
            release.set()
            worker.join(5)
        self.assertEqual(result[0]["status"], "submitted")
        self.assertEqual(len(self.transport.sent), 1)

    def test_corrupt_dispatch_state_fails_closed(self):
        self.tick()
        (self.state_dir / "state.json").write_text("corrupted")
        self.assertEqual(self.tick()["status"], "error")
        self.assertEqual(len(self.transport.sent), 1)

    def test_prepare_never_activates(self):
        with (
            patch.dict("os.environ", {"HERDR_ENV": "1", "HERDR_SOCKET_PATH": "/tmp/test-herdr.sock"}),
            patch("subprocess.run") as runner,
        ):
            result = watch.prepare(self.project)
        self.assertEqual(result["status"], "prepared-not-active")
        runner.assert_not_called()
        activation = Path(result["activation"]).read_text()
        self.assertIn("--on-unit-active=2m", activation)
        self.assertIn("tick --deliver", activation)
        self.assertEqual((self.state_dir / "herdr.env").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
