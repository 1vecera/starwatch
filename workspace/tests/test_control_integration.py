"""Verify CLI and HTTP share the canonical records across real processes."""

import concurrent.futures
import http.client
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from project_tracker.__main__ import DashboardServer


class ControlIntegrationTests(unittest.TestCase):
    def test_product_cli_http_exact_file_and_stale_document_conflict(self):
        _, state = self.request("GET")
        saved = self.cli(
            {
                "op": "product.save",
                "base_version": state["product"]["version"],
                "markdown": "# CLI product\n\nExact whitespace.  \n",
            },
            actor="hos-control",
            no_dispatch=True,
        )
        self.assertEqual(saved.returncode, 0, saved.stdout + saved.stderr)
        _, state = self.request("GET")
        version = state["product"]["version"]
        self.assertEqual(state["product"]["markdown"], (self.root / "docs/product-state.md").read_text())
        (self.root / "docs/product-state.md").write_text("# Concurrent agent file edit\n")
        status, result = self.request(
            "POST",
            {"op": "product.save", "base_version": version, "markdown": "Stale browser draft", "actor": "Daniel"},
        )
        self.assertEqual(status, 409)
        self.assertEqual(result["state"]["product"]["markdown"], "# Concurrent agent file edit\n")
        status, _ = self.request(
            "POST",
            {
                "op": "product.save",
                "base_version": result["state"]["product"]["version"],
                "markdown": "Browser page\n",
                "actor": "Daniel",
            },
        )
        self.assertEqual(status, 200)
        status, _ = self.request(
            "POST",
            {"op": "product.save", "markdown": "Cross-origin"},
            headers={"Origin": "https://outside.invalid", "Content-Type": "application/json"},
        )
        self.assertEqual(status, 403)
        self.assertEqual((self.root / "docs/product-state.md").read_text(), "Browser page\n")

    def setUp(self):
        scratch = Path.cwd() / "tmp"
        scratch.mkdir(exist_ok=True)
        self.fixture = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.fixture.name)
        (self.root / "docs/reports").mkdir(parents=True)
        (self.root / "docs/learnings.md").write_text("# Learnings\n\n- Original learning stays.\n")
        (self.root / "TODO.md").write_text(
            "# Project tasks\n\nOriginal opening prose.\n\n## Build\n"
            "- [ ] Preserve **original rich prose** and evidence `docs/reports/example.md`.\n"
            "\nA paragraph after the card must remain.\n\n## Delivery\n- [ ] Pending delivery.\n"
        )
        self.server = DashboardServer(self.root, 0)
        self.server.store.migrate()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.fixture.cleanup()

    def request(self, method, payload=None, headers=None, path="/api/control"):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=15)
        body = json.dumps(payload) if payload is not None else None
        connection.request(
            method,
            path,
            body=body,
            headers=headers or {"Content-Type": "application/json", "Origin": self.server.origin},
        )
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def cli(self, envelope, *, actor=None, no_dispatch=False):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "project_tracker.cli",
                "--root",
                str(self.root),
                *(["--actor", actor] if actor else []),
                "mutate",
                *(["--no-dispatch"] if no_dispatch else []),
                "--json",
                json.dumps(envelope),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )

    def test_cli_provenance_is_neutral_and_explicit_actors_and_browser_are_preserved(self):
        decision_id = "decision-subject"
        expected_actors = ["Agent CLI", "hos-control", "hos-research"]
        for flag_actor, json_actor, expected in (
            (None, None, "Agent CLI"),
            ("hos-control", None, "hos-control"),
            ("hos-chief", "hos-research", "hos-research"),
        ):
            with self.subTest(expected_actor=expected):
                operation = {
                    "op": "decision.choose",
                    "id": decision_id,
                    "custom_choice": "Fixture choice by " + expected,
                    "rationale": "Provenance check",
                }
                if json_actor:
                    operation["actor"] = json_actor
                result = self.cli(operation, actor=flag_actor, no_dispatch=True)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                _, state = self.request("GET")
                decision = next(d for d in state["decisions"] if d["id"] == decision_id)
                self.assertEqual(decision["history"][-1]["actor"], expected)
                self.assertEqual(state["messages"][-1]["actor"], expected)
                self.assertEqual(state["messages"][-1]["status"], "held")
                self.assertIn(expected + " chose Fixture choice", (self.root / "docs/learnings.md").read_text())
        _, before = self.request("GET")
        status, saved = self.request(
            "POST",
            {
                "op": "decision.choose",
                "base_revision": before["revision"],
                "actor": "Daniel",
                "id": decision_id,
                "custom_choice": "Browser choice",
                "rationale": "Actual browser author",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(saved["result"]["history"][-1]["actor"], "Daniel")
        records = json.loads((self.root / "tmp/control-room/records.json").read_text())
        decision = next(d for d in records["decisions"] if d["id"] == decision_id)
        self.assertEqual([entry["actor"] for entry in decision["history"]], expected_actors + ["Daniel"])

    def test_cli_write_is_http_state_and_both_reject_invalid_status(self):
        _, before = self.request("GET")
        operation = {
            "op": "task.create",
            "base_revision": before["revision"],
            "actor": "Fixture agent",
            "title": "CLI-created task",
            "description": "Visible in browser",
            "status": "ready",
        }
        result = self.cli(operation)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        _, state = self.request("GET")
        task = next(item for item in state["tasks"] if item["title"] == "CLI-created task")
        invalid = {"op": "task.move", "id": task["id"], "status": "invented", "base_revision": state["revision"]}
        self.assertGreaterEqual(self.request("POST", invalid)[0], 400)
        self.assertNotEqual(self.cli(invalid).returncode, 0)
        _, after = self.request("GET")
        self.assertEqual(after["revision"], state["revision"])
        self.assertEqual(next(t for t in after["tasks"] if t["id"] == task["id"])["status"], "ready")
        self.assertIn("CLI-created task", (self.root / "TODO.md").read_text())

    def test_quiet_cli_and_http_actor_spoof_cannot_use_deliberate_browser_route(self):
        result = self.cli({"op": "message.send", "actor": "Daniel", "text": "Isolated worker fixture"})
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["result"]["status"], "held")
        result = self.cli({"op": "quiet.set", "actor": "Daniel", "enabled": False})
        self.assertNotEqual(result.returncode, 0)
        _, before = self.request("GET")
        operation = {"op": "quiet.set", "actor": "Daniel", "enabled": False, "base_revision": before["revision"]}
        self.assertEqual(self.request("POST", operation)[0], 400)
        self.assertEqual(self.request("POST", operation, path="/api/browser-control")[0], 403)
        headers = {
            "Content-Type": "application/json",
            "Origin": self.server.origin,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
        }
        self.assertEqual(self.request("POST", operation, headers, path="/api/browser-control")[0], 403)
        status, intent = self.request("GET", headers=headers, path="/api/browser-intent")
        self.assertEqual(status, 200)
        headers["X-Control-Room-Intent"] = intent["token"]
        _, current = self.request("GET")
        operation.update(enabled=True, base_revision=current["revision"])
        status, result = self.request("POST", operation, headers, path="/api/browser-control")
        self.assertEqual(status, 200)
        self.assertTrue(result["state"]["communication"]["quiet"])
        _, current = self.request("GET")
        operation = {
            "op": "message.send",
            "text": "Deliberate browser fixture",
            "actor": "Worker",
            "base_revision": current["revision"],
        }
        status, result = self.request("POST", operation, headers, path="/api/browser-control")
        self.assertEqual(status, 200)
        self.assertEqual(result["result"]["actor"], "Daniel")
        self.assertEqual(result["result"]["delivery_class"], "direct")
        self.assertEqual(result["result"]["status"], "queued")

    def test_competing_processes_cannot_both_overwrite_one_revision(self):
        _, before = self.request("GET")
        identifier = before["tasks"][0]["id"]
        operations = [
            {"op": "task.update", "base_revision": before["revision"], "id": identifier, "patch": {"owner": owner}}
            for owner in ("First process", "Second process")
        ]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.cli, operations))
        self.assertEqual(
            sum(result.returncode == 0 for result in results), 1, [(r.returncode, r.stdout, r.stderr) for r in results]
        )
        _, after = self.request("GET")
        self.assertIn(
            next(t for t in after["tasks"] if t["id"] == identifier)["owner"], ("First process", "Second process")
        )
        body = (self.root / "TODO.md").read_text()
        self.assertIn("Original opening prose.", body)
        self.assertIn("A paragraph after the card must remain.", body)
        self.assertIn("**original rich prose**", body)
        self.assertIn("## Delivery", body)

    def test_external_todo_change_conflicts_and_preserves_both_card_and_other_prose(self):
        _, before = self.request("GET")
        todo = self.root / "TODO.md"
        todo.write_text(todo.read_text().replace("Original opening prose.", "Root changed the opening prose."))
        status, conflict = self.request(
            "POST",
            {
                "op": "task.move",
                "base_revision": before["revision"],
                "id": before["tasks"][0]["id"],
                "status": "review",
            },
        )
        self.assertEqual(status, 409)
        self.assertEqual(conflict["code"], "conflict")
        self.assertIn("Root changed the opening prose.", todo.read_text())
        operation = {
            "op": "task.move",
            "base_revision": conflict["state"]["revision"],
            "id": before["tasks"][0]["id"],
            "status": "review",
        }
        self.assertEqual(self.request("POST", operation)[0], 200)
        _, after = self.request("GET")
        self.assertEqual(after["tasks"][0]["id"], before["tasks"][0]["id"])
        self.assertEqual(after["tasks"][0]["status"], "review")
        self.assertIn("Root changed the opening prose.", todo.read_text())

    def test_mutations_require_same_origin_and_local_host(self):
        _, before = self.request("GET")
        operation = {"op": "task.create", "base_revision": before["revision"], "title": "Rejected"}
        for headers in (
            {"Content-Type": "application/json"},
            {"Content-Type": "application/json", "Origin": "https://foreign.example"},
            {"Content-Type": "application/json", "Origin": self.server.origin, "Host": "foreign.example"},
        ):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("POST", operation, headers)[0], 403)
        _, after = self.request("GET")
        self.assertEqual(after["revision"], before["revision"])


if __name__ == "__main__":
    unittest.main()
