import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from czlake.production_pool import (
    assign,
    bind_session,
    effective_limit,
    owned_live_panes,
    refresh,
)


class NativePoolTests(unittest.TestCase):
    def test_physical_limit_cannot_be_raised_and_counts_idle_shells(self):
        state = {"pool_limit": 100, "assignments": [{"pane": f"p{i}"} for i in range(5)]}
        self.assertEqual(effective_limit(state), 4)
        panes = [{"pane_id": f"p{i}", "agent_status": "idle"} for i in range(5)]
        self.assertEqual(len(owned_live_panes(state, panes)), 5)

    def test_wrong_pane_or_changed_session_never_rebinds_history(self):
        row = {"pane": "owned", "session_id": "original"}
        for pane, session in [("unrelated", "original"), ("owned", "replacement")]:
            bind_session(row, {"pane_id": pane, "agent_session": {"source": "herdr:codex", "value": session}})
            self.assertEqual(row["session_id"], "original")
            self.assertNotIn("session_binding", row)

    def test_reuse_only_and_overfull_pool_fail_before_prompt(self):
        Path("tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir="tmp") as folder:
            worktree = Path(folder).resolve()
            base = worktree / "tmp/production-workers"
            brief = base / "next/brief.md"
            brief.parent.mkdir(parents=True)
            brief.write_text("Isolated assignment")
            state = {"assignment_cap": 100, "pool_limit": 100,
                     "assignments": [{"assignment_id": f"old{i}", "pane": f"p{i}"} for i in range(5)],
                     "routing": {"p0": {"name": "reviewer", "state": "retained"}}}
            (base / "registry.json").write_text(json.dumps(state))
            def fake(args):
                if args == ["agent", "list"]:
                    return {"agents": [{"name": "reviewer", "pane_id": "p0", "agent_status": "idle"}]}
                if args == ["pane", "list"]:
                    return {"panes": [{"pane_id": f"p{i}"} for i in range(5)]}
                self.fail(f"Unexpected mutation: {args}")
            with patch("czlake.production_pool.herdr", side_effect=fake), self.assertRaisesRegex(RuntimeError, "Physical worker cap"):
                assign(worktree, brief, "reviewer", True, "preparation")
            state["assignments"] = state["assignments"][:4]
            (base / "registry.json").write_text(json.dumps(state))
            with patch("czlake.production_pool.herdr", side_effect=fake), self.assertRaisesRegex(RuntimeError, "New panes disabled"):
                assign(worktree, brief, "new-worker", False, "preparation")

    def test_refresh_preserves_hash_and_matches_pane_not_name(self):
        Path("tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir="tmp") as folder:
            worktree = Path(folder)
            base = worktree / "tmp/production-workers"
            base.mkdir(parents=True)
            row = {"assignment_id": "old", "name": "reviewer", "pane": "owned", "brief_sha256": "frozen"}
            (base / "registry.json").write_text(json.dumps({"assignments": [row], "assignment_cap": 100, "pool_limit": 4}))
            def fake(args):
                if args == ["agent", "list"]:
                    return {"agents": [{"name": "reviewer", "pane_id": "unrelated", "agent_status": "idle",
                                        "agent_session": {"source": "herdr:codex", "value": "forged"}}]}
                return {"panes": [{"pane_id": "owned"}]}
            with patch("czlake.production_pool.herdr", side_effect=fake):
                refresh(worktree)
            saved = json.loads((base / "registry.json").read_text())["assignments"][0]
            self.assertNotIn("session_id", saved)
            self.assertEqual(saved["brief_sha256"], "frozen")
