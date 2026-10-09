"""Persist bounded native Herdr assignments without touching unrelated panes."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .production_labels import atomic_json

HARD_WORKER_SLOTS = 4


def effective_limit(state: dict) -> int:
    """Configuration can tighten, never raise, Daniel's physical worker ceiling."""
    return min(HARD_WORKER_SLOTS, max(0, int(state.get("pool_limit", HARD_WORKER_SLOTS))))


def owned_live_panes(state: dict, panes: list[dict]) -> set[str]:
    owned = {row.get("pane") for row in state["assignments"]}
    owned.update(state.get("routing", {}))
    return {pane["pane_id"] for pane in panes if pane["pane_id"] in owned}


def bind_session(row: dict, agent: dict) -> None:
    """Freeze native identity only when both the owned pane and session agree."""
    session = agent.get("agent_session", {})
    if (agent.get("pane_id") != row.get("pane") or session.get("source") != "herdr:codex"
            or not session.get("value") or (row.get("session_id") and row["session_id"] != session["value"])):
        row["binding_error"] = "owned_pane_or_session_mismatch"
        return
    row.setdefault("session_id", session["value"])
    row.setdefault("session_binding", {"source": "herdr:codex", "pane": row["pane"],
        "session_id": session["value"], "observed_at": datetime.now(UTC).isoformat(),
        "agent_receipt": agent})

def herdr(arguments: list[str]) -> dict:
    """Use the inherited local session and preserve CLI failure receipts."""
    if os.environ.get("HERDR_ENV") != "1":
        raise RuntimeError("Native worker control requires HERDR_ENV=1")
    result = subprocess.run(["herdr", *arguments], capture_output=True, text=True, timeout=55, check=False)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return json.loads(result.stdout)["result"]


@contextmanager
def locked_registry(worktree: Path):
    directory = worktree / "tmp/production-workers"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".pool.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / "registry.json"
        state = json.loads(path.read_text())
        try:
            yield path, state
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def refresh(worktree: Path) -> dict:
    """Record observed lifecycle states; an idle pane is not proof of valid output."""
    agents = {a["pane_id"]: a for a in herdr(["agent", "list"])["agents"]}
    panes = herdr(["pane", "list"])["panes"]
    with locked_registry(worktree) as (path, state):
        for row in state["assignments"]:
            agent = agents.get(row.get("pane"))
            row["observed_agent_state"] = agent["agent_status"] if agent else "absent"
            if agent:
                bind_session(row, agent)
        physical = owned_live_panes(state, panes)
        state["physical_worker_count"] = len(physical)
        state["hard_worker_slot_cap"] = HARD_WORKER_SLOTS
        state["effective_worker_slot_cap"] = effective_limit(state)
        state["observed_at"] = datetime.now(UTC).isoformat()
        atomic_json(path, state)
        return {"assignments": len(state["assignments"]), "cap": state["assignment_cap"],
                "pool_limit": effective_limit(state), "physical_worker_count": len(physical),
                "within_physical_cap": len(physical) <= effective_limit(state), "routing": state.get("routing", {}), "workers": [
                    {k: row.get(k) for k in ("assignment_id", "name", "pane", "state", "observed_agent_state")}
                    for row in state["assignments"]]}


def assign(worktree: Path, brief: Path, name: str, reuse: bool, task_kind: str) -> dict:
    """Reserve an assignment before native startup and never replay ambiguous prompts."""
    worktree, brief = worktree.resolve(), brief.resolve()
    base = worktree / "tmp/production-workers"
    if not brief.is_relative_to(base) or not brief.is_file():
        raise ValueError("Assignment brief must be a file in the isolated worker directory")
    assignment = brief.parent.name
    with locked_registry(worktree) as (path, state):
        if len(state["assignments"]) >= min(100, state["assignment_cap"]):
            raise RuntimeError("Worker assignment budget exhausted")
        if any(row["assignment_id"] == assignment for row in state["assignments"]):
            raise RuntimeError("Assignment already reserved; inspect and recover, never resubmit blindly")
        agents = {a.get("name"): a for a in herdr(["agent", "list"])["agents"]}
        panes = herdr(["pane", "list"])["panes"]
        physical = owned_live_panes(state, panes)
        if len(physical) > effective_limit(state):
            raise RuntimeError("Physical worker cap exceeded; consolidate before another assignment")
        owned = {route["name"]: pane for pane, route in state.get("routing", {}).items()
                 if route.get("state") == "retained"}
        if reuse:
            if name not in owned or name not in agents or agents[name]["pane_id"] != owned[name]:
                raise ValueError("Reuse is restricted to a current owned worker")
            if agents[name]["agent_status"] not in {"idle", "done"}:
                raise RuntimeError("Worker is not settled")
            pane = owned[name]
        else:
            raise RuntimeError("New panes disabled for this production run; reuse a retained worker")
        row = {"assignment_id": assignment, "name": name, "pane": pane, "brief": str(brief),
               "brief_sha256": hashlib.sha256(brief.read_bytes()).hexdigest(),
               "task_kind": task_kind, "state": "reserved", "created_at": datetime.now(UTC).isoformat(),
               "model": "gpt-6.1-sol", "reasoning_effort": "xhigh", "service_tier": "fast"}
        if (brief.parent / "cards.json").exists():
            row["cards_sha256"] = hashlib.sha256((brief.parent / "cards.json").read_bytes()).hexdigest()
        state["assignments"].append(row)
        bind_session(row, agents[name])
        if row.get("binding_error"):
            raise RuntimeError("Cannot bind assignment to the owned native session")
        atomic_json(path, state)
        try:
            row["state"] = "prompt_submission_pending"
            atomic_json(path, state)
            row["prompt_receipt"] = herdr(["agent", "prompt", name,
                (f"Read and execute {brief}. Work only in assigned files. No messages to chief/root. "
                 "Complete the bounded assignment now; hos-production reads your report.")])
            row["state"] = "submitted"
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            row["state"] = "ambiguous_control_requires_inspection"
            row["control_error"] = str(error)
            raise
        finally:
            atomic_json(path, state)
        return {"assignment_id": assignment, "pane": pane, "name": name, "state": row["state"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "assign"])
    parser.add_argument("--worktree", type=Path, default=Path.cwd())
    parser.add_argument("--brief", type=Path)
    parser.add_argument("--name")
    parser.add_argument("--reuse", action="store_true")
    parser.add_argument("--kind", choices=["preparation", "classification", "independent_review"], default="preparation")
    args = parser.parse_args()
    result = refresh(args.worktree) if args.command == "status" else assign(
        args.worktree, args.brief, args.name, args.reuse, args.kind)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
