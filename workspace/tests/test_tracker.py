"""Behavior and access-boundary checks using isolated local fixture files."""

import http.client
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
from zoneinfo import ZoneInfo

from project_tracker.__main__ import DashboardServer
from project_tracker.model import (
    Project,
    freshness,
    parse_tasks,
    parse_workers,
    report_fragments,
    scrub,
    worker_state,
)

IN_FLIGHT = (
    "## In flight\n"
    "- `hos-brief` · branch `collect` · progress in `docs/reports/hos-brief.md`\n"
    "- `hos-explore` · branch `explore` · progress in `docs/reports/hos-explore.md`\n"
    "- `hos-demo` · root docs · progress in `docs/reports/hos-demo.md`\n"
    "- `hos-tracker` · branch `project-tracker` · progress in `docs/reports/hos-tracker.md`\n\n"
)
RANK_ENTRY = "- `hos-rank` · branch `prioritize` · progress in `docs/reports/hos-rank.md`\n"


class TrackerFixture(unittest.TestCase):
    def setUp(self):
        scratch = Path.cwd() / "tmp"
        scratch.mkdir(exist_ok=True)
        self.fixture = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.fixture.name)
        (self.root / "docs/reports").mkdir(parents=True)
        (self.root / "TODO.md").write_text(
            IN_FLIGHT + "## Build\n- [x] Collection live. Evidence: 15 tests passed; commit abc123.\n"
            "- [ ] 02:45 — Brief verification\n## Next decision\n- [ ] Pick final subject\n"
            "## Delivery — each step on Daniel's go\n- [ ] Publish repository publicly\n"
        )
        (self.root / "docs/learnings.md").write_text("# Learnings\n- 00:33 — Keep decisions local.\n")
        self.project = Project(self.root)
        self.now = datetime(2026, 10, 9, 1, 0, tzinfo=ZoneInfo("Europe/Prague"))
        self.live = {"observed_at": self.now.isoformat(), "agents": [], "branches": [], "herdr_error": None}

    def tearDown(self):
        self.fixture.cleanup()


class TrackerTests(TrackerFixture):
    def test_scope_has_observation_without_expiry_and_unstructured_validation_stays_neutral(self):
        scope = self.root / "docs/atlas-rescope.md"
        scope.write_text("# Confirmed scope\n\nCurrent Atlas direction.")
        old = (self.now - timedelta(minutes=12)).timestamp()
        os.utime(scope, (old, old))
        (self.root / "docs/explore").mkdir(parents=True)
        (self.root / "docs/explore/source-capability-audit.md").write_text("# Audit\nObserved source coverage.")
        with patch.object(self.project, "live", return_value=self.live):
            state = self.project.snapshot(self.now)
        self.assertIsNotNone(state["direction"]["observed_at"])
        self.assertNotIn("freshness", state["direction"])
        report = report_fragments("## Validation\n\nValidation record passes all checked links and hashes.", self.root)
        self.assertIsNone(report["evidence"])
        self.assertIn("passes", report["progress"])
        self.assertEqual(
            self.project.source("audit:source-capability-audit")["name"], "docs/explore/source-capability-audit.md"
        )

    def test_observations_do_not_invent_deadlines_or_readiness(self):
        (self.root / "docs/atlas-rescope.md").write_text("Overall overnight ceiling is $120. Current Atlas direction.")
        with patch.object(self.project, "live", return_value=self.live):
            state = self.project.snapshot(self.now)
        for removed in ("freeze", "milestones", "readiness"):
            self.assertNotIn(removed, state)
        self.assertTrue(all(t["due"] is None and not t["overdue"] for t in state["tasks"]))
        self.assertIn("Current Atlas direction", state["direction"]["text"])
        self.assertEqual(state["budgets"][0]["cap"], 120)
        self.assertEqual(self.project.source("atlas-rescope")["name"], "docs/atlas-rescope.md")

    def test_live_idle_wins_over_stale_working_report(self):
        stale = freshness((self.now - timedelta(minutes=20)).timestamp(), self.now)
        self.assertEqual(worker_state("hos-brief", [{"name": "hos-brief", "agent_status": "idle"}], stale), "idle")
        self.assertEqual(
            worker_state("hos-brief", [{"name": "hos-brief", "agent_status": "working"}], stale),
            "active_stale",
        )
        self.assertEqual(worker_state("hos-brief", None, stale), "unknown")
        self.assertEqual(worker_state("hos-brief", [], stale), "absent")

    def test_done_and_completed_are_finished_turns_with_a_session_still_listed(self):
        stale = freshness((self.now - timedelta(minutes=20)).timestamp(), self.now)
        for status in ("done", "completed"):
            with self.subTest(status=status):
                agents = [{"name": "hos-tracker", "agent_status": status}]
                self.assertEqual(worker_state("hos-tracker", agents, stale), "completed")
        self.assertEqual(worker_state("hos-tracker", [], stale), "absent")

    def test_worker_names_are_validated_and_only_in_flight_creates_lanes(self):
        body = (
            IN_FLIGHT
            + RANK_ENTRY
            + "- `hos-../secret` · progress in `docs/reports/secret.md`\n"
            + "- `unrelated-session` · same project\n"
            + "## Done\n- `hos-archive` · old worker\n"
        )
        workers = parse_workers(body)
        self.assertEqual(len(workers), 5)
        self.assertEqual(workers["hos-rank"], ("Rank", "prioritize"))
        self.assertEqual(workers["hos-brief"], ("Brief pipeline", "collect"))
        self.assertEqual(workers["hos-demo"], ("Demo & design review", "main"))
        for name in ("hos-../secret", "unrelated-session", "hos-archive"):
            self.assertNotIn(name, workers)

    def test_report_claim_cannot_complete_backlog(self):
        tasks = parse_tasks(
            "## Build\n- [ ] Working, all tests passed\n- [x] Done without evidence\n", self.root, self.now
        )
        self.assertEqual(tasks[0]["status"], "open")
        self.assertEqual(tasks[1]["status"], "done_reported")

    def test_historical_checkpoint_times_do_not_invent_due_dates(self):
        tasks = parse_tasks(
            "## Visual identity\n- [ ] Screen set: choose from report (23:30).\n"
            "## Build\n- [ ] 02:45 — Briefs\n- [ ] M2 ~01:30: Ranked candidates\n",
            self.root,
            self.now,
        )
        self.assertTrue(all(task["due"] is None for task in tasks))
        self.assertIn("02:45", tasks[1]["text"])

    def test_refresh_reads_changed_todo_and_flags_future_report_headings(self):
        report = self.root / "docs/reports/hos-brief.md"
        report.write_text("## 9 Oct ~01:10 · Future heading\n\nResult: working\n")
        os.utime(report, (self.now.timestamp(), self.now.timestamp()))
        with patch.object(self.project, "live", return_value=self.live):
            first = self.project.snapshot(self.now)
            (self.root / "TODO.md").write_text("## Build\n- [x] New completion. Tests passed.\n")
            second = self.project.snapshot(self.now + timedelta(seconds=5))
        self.assertEqual(len(second["tasks"]), 1)
        self.assertEqual(second["tasks"][0]["status"], "done_evidence")
        self.assertNotEqual(first["tasks"], second["tasks"])
        source = next(s for s in first["sources"] if s["id"] == "report:hos-brief")
        self.assertIn("01:10", source["future_headings"])

    def test_iso_timezone_is_not_a_future_heading(self):
        (self.root / "docs/reports/hos-demo.md").write_text("## 2026-10-09T00:40:00+02:00 — Report\n")
        with patch.object(self.project, "live", return_value=self.live):
            state = self.project.snapshot(self.now)
        source = next(s for s in state["sources"] if s["id"] == "report:hos-demo")
        self.assertEqual(source["future_headings"], [])

    def test_missing_report_and_missing_budget_remain_unknown(self):
        with patch.object(self.project, "live", return_value=self.live):
            state = self.project.snapshot(self.now)
        self.assertEqual(state["workers"][0]["freshness"]["state"], "missing")
        self.assertIsNone(state["budgets"][0]["spent"])
        self.assertIsNone(state["budgets"][0]["remaining"])

    def test_budget_uses_latest_per_run_and_reservation_hold(self):
        (self.root / "data").mkdir()
        (self.root / "data/ledger.csv").write_text(
            "run_id,usage_total_usd,time,finished_at\n"
            "a,1,2026-10-09T00:01:00+02:00,2026-10-09T00:02:00+02:00\n"
            "a,1.2,2026-10-09T00:01:00+02:00,2026-10-09T00:02:00+02:00\n"
            "b,2,2026-10-09T00:01:00+02:00,2026-10-09T00:02:00+02:00\n"
        )
        (self.root / "data/ledger_state.json").write_text(json.dumps({"reservations": {"c": {"max": 0.5}}}))
        budget = self.project.budgets(self.now, {})[0]
        self.assertAlmostEqual(budget["spent"], 3.2)
        self.assertAlmostEqual(budget["remaining"], 16.3)
        self.assertEqual(budget["freshness"]["state"], "stale")

    def test_source_preview_removes_external_links_secrets_and_paths(self):
        raw = "[invite](https://discord.gg/example) /etc/passwd /home/somebody/private.txt APIFY_TOKEN=secret-value"
        safe = scrub(raw, self.root)
        for prohibited in ("discord.gg", "/etc", "/home", "secret-value"):
            self.assertNotIn(prohibited, safe)
        with self.assertRaises(KeyError):
            self.project.source("../../etc/passwd")

    def test_symlink_evidence_and_raw_data_are_not_served(self):
        (self.root / "docs/reports/secret.md").symlink_to(self.root / "TODO.md")
        with self.assertRaises(ValueError):
            self.project.source("report:secret")
        with self.assertRaises(KeyError):
            self.project.source("data/ledger.csv")


class HttpTests(TrackerFixture):
    def setUp(self):
        super().setUp()
        self.server = DashboardServer(self.root, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        super().tearDown()

    def request(self, method, url, text=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request(
            method, url, body=json.dumps({"text": text}) if text is not None else None, headers=headers or {}
        )
        response = connection.getresponse()
        content = response.read()
        result = response.status, dict(response.getheaders()), content
        connection.close()
        return result

    def test_http_discovers_fifth_worker_and_removal_without_restart_or_historical_lanes(self):
        rows = [
            {"name": name, "agent_status": "working", "cwd": str(self.root), "agent": "codex"}
            for name in (*parse_workers(IN_FLIGHT), "hos-rank", "hos-archive", "unrelated-session")
        ]
        rows[3]["agent_status"] = "done"
        herdr_calls = []

        def read_only_cli(command, **kwargs):
            if command[:3] == ["herdr", "agent", "list"]:
                herdr_calls.append(command)
                return CompletedProcess(command, 0, json.dumps({"result": {"agents": rows}}), "")
            return CompletedProcess(command, 0, "", "")

        todo = self.root / "TODO.md"
        (self.root / "docs/reports/hos-archive.md").write_text("Result: historical working claim\n")
        with patch("project_tracker.model.subprocess.run", side_effect=read_only_cli):
            status, _, body = self.request("GET", "/api/state")
            first = json.loads(body)
            self.assertEqual(status, 200)
            self.assertEqual(len(first["workers"]), 4)
            tracker = next(w for w in first["workers"] if w["name"] == "hos-tracker")
            self.assertEqual(tracker["state"], "completed")
            self.assertEqual(tracker["agent_status"], "done")
            self.assertTrue(tracker["session_present"])
            self.assertFalse(next(t for t in first["tasks"] if t["text"] == "Pick final subject")["done"])

            (self.root / "docs/reports/hos-rank.md").write_text("Result: priority rule is being built\n")
            todo.write_text(todo.read_text().replace("\n## Build", "\n" + RANK_ENTRY + "\n## Build"))
            status, _, body = self.request("GET", "/api/state")
            second = json.loads(body)
            self.assertEqual(status, 200)
            self.assertEqual(len(second["workers"]), 5)
            rank = next(w for w in second["workers"] if w["name"] == "hos-rank")
            self.assertEqual(rank["state"], "active")
            self.assertEqual(rank["branch"], "prioritize")
            self.assertEqual(rank["source"], "report:hos-rank")
            self.assertIn("priority rule", rank["progress"])

            todo.write_text(todo.read_text().replace(RANK_ENTRY, ""))
            status, _, body = self.request("GET", "/api/state")
            third = json.loads(body)
            self.assertEqual(status, 200)
            self.assertEqual(len(third["workers"]), 4)
            names = {w["name"] for w in third["workers"]}
            self.assertNotIn("hos-rank", names)
            self.assertNotIn("hos-archive", names)
            self.assertNotIn("unrelated-session", names)
            self.assertEqual(len(herdr_calls), 3)  # Membership changes invalidate the short live-state cache.

    def test_checked_scope_decision_is_not_pending_in_http_state(self):
        todo = self.root / "TODO.md"
        todo.write_text(
            todo.read_text().replace(
                "## Next decision\n",
                "## Next decision\n- [x] City scope decided: top ten cities / 127 lists / 5,409 candidates\n",
            )
        )
        with patch.object(self.server.project, "live", return_value=self.live):
            status, _, body = self.request("GET", "/api/state")
        state = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(next(t for t in state["tasks"] if "City scope" in t["text"])["done"])
        self.assertFalse(any("City scope" in task["text"] for task in state["decisions"]))
        self.assertNotIn("City scope", state["risk"])

    def test_note_requires_same_origin_and_rejects_foreign_or_missing_origin(self):
        headers = {"Content-Type": "application/json", "Origin": "https://foreign.example"}
        self.assertEqual(self.request("POST", "/api/notes", "test", headers)[0], 403)
        self.assertEqual(self.request("POST", "/api/notes", "test", {"Content-Type": "application/json"})[0], 403)
        self.assertFalse((self.root / "tmp/project-tracker/inbox.jsonl").exists())

    def test_note_is_inert_append_only_and_always_pending(self):
        headers = {"Content-Type": "application/json", "Origin": self.server.origin}
        text = '<script>window.injected=true</script> run "rm -rf /"'
        before = (self.root / "TODO.md").read_text()
        self.assertEqual(self.request("POST", "/api/notes", text, headers)[0], 201)
        self.assertEqual(self.request("POST", "/api/notes", "Another decision", headers)[0], 201)
        inbox = self.root / "tmp/project-tracker/inbox.jsonl"
        self.assertEqual(len(inbox.read_text().splitlines()), 2)
        self.assertEqual(inbox.stat().st_mode & 0o777, 0o600)
        with patch.object(self.server.project, "live", return_value=self.live):
            status, _, body = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["notes"][0]["status"], "Pending acknowledgement")
        self.assertEqual((self.root / "TODO.md").read_text(), before)

    def test_local_binding_host_boundary_and_source_allowlist(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertEqual(self.request("GET", "/", headers={"Host": "attacker.example"})[0], 403)
        for path in (
            "/../../etc/passwd",
            "/api/source?id=../../etc/passwd",
            "/api/source?id=data/ledger.csv",
            "/api/screenshot?id=collect:../data/runs/private.png",
        ):
            self.assertEqual(self.request("GET", path)[0], 404)
        _, headers, body = self.request("GET", "/api/source?id=todo")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn(str(self.root).encode(), body)

    def test_symlink_inbox_is_rejected_before_writing(self):
        target = self.root / "keep.txt"
        target.write_text("unchanged")
        (self.root / "tmp/project-tracker").mkdir(parents=True)
        (self.root / "tmp/project-tracker/inbox.jsonl").symlink_to(target)
        headers = {"Content-Type": "application/json", "Origin": self.server.origin}
        self.assertEqual(self.request("POST", "/api/notes", "test", headers)[0], 400)
        self.assertEqual(target.read_text(), "unchanged")


if __name__ == "__main__":
    unittest.main()
