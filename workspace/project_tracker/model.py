"""Read bounded local evidence; never operate workers or turn notes into tasks."""

import csv
import json
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PRAGUE = ZoneInfo("Europe/Prague")
STALE_SECONDS = 600
MAX_SOURCE_BYTES = 256_000
WORKER_DEFAULTS = {
    "hos-brief": ("Brief pipeline", "collect"),
    "hos-explore": ("Local-election research", "explore"),
    "hos-demo": ("Demo & design review", "main"),
    "hos-tracker": ("Project dashboard", "project-tracker"),
}
WORKER_NAME = re.compile(r"hos-[a-z0-9][a-z0-9_-]{0,55}\Z")
SCREEN_DIRS = ("vis-atlas", "vis-press", "collect", "skeleton", "demo-review")


def scrub(text: str, root: Path) -> str:
    """Keep readable evidence while removing paths, credentials and external links."""
    text = text.replace(str(root) + "/", "")
    text = re.sub(r"\[([^\]]+)\]\([^\n)]+\)", r"\1", text)
    text = re.sub(r"(?:https?://|file://|app://)\S+", "[link omitted]", text)
    text = re.sub(r"(?:/home/|/Users/|/etc/|/proc/|/run/|/var/|~/)[^\s`\"<>),;]+", "[local path]", text)
    text = re.sub(r"\b(?:sk-|apify_api_|ghp_|github_pat_|AKIA|eyJ)[A-Za-z0-9_.-]{12,}", "[redacted]", text)
    text = re.sub(
        r"(?im)(?:[\w-]*(?:password|secret|token|api_key|invitation|invite)[\w-]*)\s*[:=]\s*[^\n,;]+",
        "[sensitive value omitted]",
        text,
    )
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    return text


def plain(text: str, root: Path) -> str:
    """Turn report fragments into short inert prose for the overview."""
    return re.sub(r"\s+", " ", scrub(text, root).replace("**", "").replace("`", "")).strip()


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def freshness(modified: float | None, now: datetime) -> dict:
    if modified is None:
        return {"state": "missing", "at": None, "age_seconds": None}
    age = now.timestamp() - modified
    return {
        "state": "future" if age < -60 else "stale" if age > STALE_SECONDS else "fresh",
        "at": iso(datetime.fromtimestamp(modified, timezone.utc)),
        "age_seconds": max(0, int(age)),
    }


def parse_workers(body: str) -> dict[str, tuple[str, str | None]]:
    """Discover only safe named workers explicitly listed in TODO's current In flight section."""
    in_flight = False
    workers = {}
    for line in body.splitlines():
        if line.startswith("## "):
            in_flight = line[3:].strip().casefold() == "in flight"
            continue
        if not in_flight:
            continue
        entry = re.match(r"\s*- (?:\[[ xX]\] )?`([^`]+)`(?:\s|$)", line)
        if not entry or not WORKER_NAME.fullmatch(entry[1]):
            continue
        name = entry[1]
        title, branch = WORKER_DEFAULTS.get(
            name,
            (name.removeprefix("hos-").replace("-", " ").replace("_", " ").title(), None),
        )
        recorded_branch = re.search(r"\bbranch `([A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*)`", line)
        if recorded_branch:
            branch = recorded_branch[1]
        # Reports are derived from validated names, never from a path supplied in prose.
        workers[name] = (title, branch)
    return workers


def parse_tasks(body: str, root: Path, now: datetime) -> list[dict]:
    """TODO checkboxes are the only backlog; report prose cannot complete them."""
    section = "Backlog"
    tasks = []
    for number, line in enumerate(body.splitlines(), 1):
        if line.startswith("## "):
            section = line[3:].strip()
        match = re.match(r"\s*- \[([ xX])\] (.+)", line)
        if not match:
            continue
        raw = match[2]
        done = match[1].lower() == "x"
        evidence = bool(re.search(r"evidence:|tests?\b|commit\b|verified|passed|succeeded", raw, re.I))
        tasks.append(
            {
                "id": f"todo-{number}",
                "line": number,
                "section": plain(section, root),
                "text": plain(raw, root),
                "done": done,
                "status": "done_evidence" if done and evidence else "done_reported" if done else "open",
                "due": None,
                "overdue": False,
                "source": "todo",
            }
        )
    return tasks


def report_fragments(body: str, root: Path) -> dict:
    headings = list(re.finditer(r"(?m)^## .+$", body))
    last = body[headings[-1].start() :] if headings else body
    result = re.search(r"(?im)^Result:\s*(.+)", last)
    evidence = re.search(r"(?im)^Evidence:\s*(.+)", last)
    needs = re.search(r"(?im)^Needs Daniel:\s*(.+)", last)
    paragraphs = [p for p in last.split("\n\n") if p.strip() and not p.startswith(("#", "```"))]
    return {
        "heading": plain(headings[-1][0][3:], root) if headings else "Latest report",
        "progress": plain(result[1] if result else paragraphs[0] if paragraphs else "No progress text", root)[:650],
        "evidence": plain(evidence[1], root)[:600] if evidence else None,
        "needs": plain(needs[1], root)[:500] if needs and not re.match(r"none\b", needs[1], re.I) else None,
    }


def worker_state(name: str, agents: list[dict] | None, fresh: dict) -> str:
    """Live detection wins over stale prose; unavailable detection remains unknown."""
    if agents is None:
        return "unknown"
    matches = [a for a in agents if a.get("name") == name]
    if not matches:
        return "absent"
    status = matches[0].get("agent_status", "unknown")
    if status in ("working", "running", "busy"):
        return "active_stale" if fresh["state"] in ("stale", "future", "missing") else "active"
    if status in ("done", "completed"):
        return "completed"
    if status in ("idle", "waiting", "ready"):
        return "idle"
    return status if status in ("blocked", "stopped", "error") else "unknown"


class Project:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.lock = threading.Lock()
        self.live_cache: dict = {}
        self.live_at = 0.0
        self.live_names: frozenset[str] = frozenset()

    def bounded(self, relative: str, maximum: int = MAX_SOURCE_BYTES) -> Path:
        """Reject symlinks and escapes before any source or preview read."""
        path = self.root / relative
        for parent in (path, *path.parents):
            if parent == self.root:
                break
            if parent.is_symlink():
                raise ValueError("Symlink sources are not served")
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root) or not resolved.is_file():
            raise ValueError("Source unavailable")
        if resolved.stat().st_size > maximum:
            raise ValueError("Source exceeds preview limit")
        return resolved

    def sources(self) -> dict[str, str]:
        result = {
            "todo": "TODO.md",
            "learnings": "docs/learnings.md",
            "atlas-rescope": "docs/atlas-rescope.md",
            "product-state": "docs/product-state.md",
            "atlas-screens": "docs/design/atlas-screens.md",
            "identity-readiness": "docs/explore/identity-readiness.md",
            "event": "docs/event.md",
            "screens-brainstorm": "docs/screens-brainstorm.md",
            "screens-review": "docs/screens-review.md",
            "atlas-execution": "docs/tasks/hos-claude-atlas-execution.md",
        }
        directory = self.root / "docs/reports"
        if not directory.is_symlink():
            for file in sorted(directory.glob("*.md")):
                if re.fullmatch(r"[a-zA-Z0-9_-]+\.md", file.name):
                    result[f"report:{file.stem}"] = f"docs/reports/{file.name}"
        directory = self.root / "docs/research"
        if not directory.is_symlink():
            for file in sorted(directory.glob("*.md")):
                if re.fullmatch(r"[a-zA-Z0-9_-]+\.md", file.name):
                    result[f"research:{file.stem}"] = f"docs/research/{file.name}"
        directory = self.root / "docs/explore"
        if not directory.is_symlink():
            for file in sorted(directory.glob("*audit*.md")):
                if re.fullmatch(r"[a-zA-Z0-9_-]+\.md", file.name):
                    result[f"audit:{file.stem}"] = f"docs/explore/{file.name}"
        return result

    def source(self, identifier: str) -> dict:
        relative = self.sources()[identifier]
        path = self.bounded(relative)
        return {"name": relative, "text": scrub(path.read_text(errors="replace"), self.root)}

    def live(self, worker_names: frozenset[str]) -> dict[str, Any]:
        """Cache read-only CLI calls; only project worker fields leave this method."""
        with self.lock:
            if time.monotonic() - self.live_at < 4 and worker_names == self.live_names:
                return self.live_cache
            now = datetime.now(timezone.utc)
            live = {"observed_at": iso(now), "agents": None, "branches": [], "herdr_error": None}
            try:
                output = subprocess.run(
                    ["herdr", "agent", "list"],
                    capture_output=True,
                    timeout=3,
                    check=True,
                    text=True,
                )
                rows = json.loads(output.stdout)["result"]["agents"]
                live["agents"] = [
                    {"name": a.get("name"), "agent_status": a.get("agent_status"), "agent": a.get("agent")}
                    for a in rows
                    if a.get("name") in worker_names and Path(str(a.get("cwd", ""))).is_relative_to(self.root)
                ]
            except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
                live["herdr_error"] = "Herdr unavailable; worker activity is unknown"
            try:
                output = subprocess.run(
                    ["git", "--no-optional-locks", "-C", str(self.root), "worktree", "list", "--porcelain"],
                    capture_output=True,
                    timeout=3,
                    check=True,
                    text=True,
                )
                for block in output.stdout.strip().split("\n\n"):
                    fields = dict(line.split(" ", 1) for line in block.splitlines() if " " in line)
                    path = Path(fields["worktree"]).resolve()
                    branch = fields.get("branch", "detached").removeprefix("refs/heads/")
                    if path == self.root or path.parent == self.root / ".claude/worktrees":
                        status = subprocess.run(
                            [
                                "git",
                                "--no-optional-locks",
                                "-C",
                                str(path),
                                "status",
                                "--porcelain",
                                "--untracked-files=no",
                            ],
                            capture_output=True,
                            text=True,
                            timeout=2,
                            check=True,
                        )
                        live["branches"].append(
                            {
                                "name": plain(branch, self.root),
                                "commit": fields["HEAD"][:10],
                                "dirty": bool(status.stdout.strip()),
                            }
                        )
            except (OSError, subprocess.SubprocessError, ValueError, KeyError):
                live["git_error"] = "Git observation unavailable"
            self.live_cache, self.live_at, self.live_names = live, time.monotonic(), worker_names
            return live

    def screenshots(self) -> dict[str, str]:
        result = {}
        for directory in SCREEN_DIRS:
            parent = self.root / "tmp" / directory
            if parent.is_symlink():
                continue
            for path in sorted(parent.glob("*.png")):
                if re.fullmatch(r"[A-Za-z0-9_.-]+\.png", path.name):
                    result[f"{directory}:{path.name}"] = f"tmp/{directory}/{path.name}"
        return result

    def budgets(self, now: datetime, bodies: dict[str, str]) -> list[dict]:
        """Project only cost fields from local ledgers, never raw items or credentials."""
        result = []
        spent, reserved, observed, held = None, None, None, None
        try:
            path = self.bounded("data/ledger.csv")
            rows = list(csv.DictReader(path.read_text().splitlines()))
            amounts = {r["run_id"]: float(r["usage_total_usd"]) for r in rows if r["usage_total_usd"]}
            spent = sum(amounts.values())
            observed = path.stat().st_mtime
            timestamps = [datetime.fromisoformat((r["finished_at"] or r["time"]).replace("Z", "+00:00")) for r in rows]
            if timestamps:
                observed = min(observed, max(stamp.timestamp() for stamp in timestamps))
        except (OSError, ValueError, KeyError):
            pass
        try:
            path = self.bounded("data/ledger_state.json")
            entries = json.loads(path.read_text())["reservations"].values()
            reserved = sum(float(item["max"]) for item in entries)
            held = freshness(path.stat().st_mtime, now)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        result.append(
            {
                "name": "Exploration · Apify",
                "cap": 20,
                "spent": spent,
                "reserved": reserved,
                "remaining": max(0, 20 - spent - reserved) if spent is not None and reserved is not None else None,
                "freshness": freshness(observed, now),
                "reservation_freshness": held,
                "basis": "Local ledger; settlement holds are conservatively reserved. No account API queried.",
            }
        )
        collector = bodies.get("report:hos-collect", "")
        matches = list(
            re.finditer(
                r"(?:spend|spent)\s*(?:≈|about|so far|:)?\s*\$([0-9.]+)\s*(?:of|/)\s*\$3",
                collector,
                re.I,
            )
        )
        amount = float(matches[-1][1].rstrip(".")) if matches else None
        try:
            modified = self.bounded("docs/reports/hos-collect.md").stat().st_mtime
        except ValueError:
            modified = None
        result.append(
            {
                "name": "Collector · Apify",
                "cap": 3,
                "spent": amount,
                "reserved": None,
                "remaining": None,
                "freshness": freshness(modified, now),
                "basis": "Approximate cumulative collector spend; reservations and actual headroom unknown.",
                "source": "report:hos-collect",
            }
        )
        result.append(
            {
                "name": "Other services / account total",
                "cap": None,
                "spent": None,
                "reserved": None,
                "remaining": None,
                "freshness": freshness(None, now),
                "basis": "No current consolidated local account record. Scribe and model totals unknown.",
            }
        )
        return result

    def snapshot(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        bodies, sources = {}, []
        for identifier, relative in self.sources().items():
            try:
                path = self.bounded(relative)
                body = path.read_text(errors="replace")
                bodies[identifier] = body
                future = []
                for stamp in re.findall(r"(?m)^## .*?(2026-\d\d-\d\d[ T]\d\d:\d\d(?::\d\d)?(?:[+-]\d\d:\d\d)?)", body):
                    try:
                        parsed = datetime.fromisoformat(stamp)
                        parsed = parsed if parsed.tzinfo else parsed.replace(tzinfo=PRAGUE)
                        if parsed > now + timedelta(minutes=2):
                            future.append(stamp)
                    except ValueError:
                        pass
                # Historical reports often have only HH:MM headings on the hackathon date.
                if identifier.startswith("report:"):
                    old_headings = [
                        line
                        for line in body.splitlines()
                        if line.startswith("## ") and not re.search(r"\d{4}-\d\d-\d\d", line)
                    ]
                    for stamp in re.findall(r"(?m)^##[^\n]*?\b([01]\d:[0-5]\d)\b", "\n".join(old_headings)):
                        hour, minute = map(int, stamp.split(":"))
                        if now.astimezone(PRAGUE).replace(hour=hour, minute=minute, second=0) > now + timedelta(
                            minutes=2
                        ):
                            future.append(stamp)
                sources.append(
                    {
                        "id": identifier,
                        "name": relative,
                        "freshness": freshness(path.stat().st_mtime, now),
                        "future_headings": future,
                    }
                )
            except (OSError, ValueError):
                sources.append({"id": identifier, "name": relative, "freshness": freshness(None, now)})
        tasks = parse_tasks(bodies.get("todo", ""), self.root, now)
        definitions = parse_workers(bodies.get("todo", ""))
        live = self.live(frozenset(definitions))
        source_map = {s["id"]: s for s in sources}
        workers = []
        for name, (title, branch) in definitions.items():
            identifier = f"report:{name}"
            fresh = source_map.get(identifier, {}).get("freshness", freshness(None, now))
            sessions = [a for a in live["agents"] or [] if a.get("name") == name]
            workers.append(
                {
                    "name": name,
                    "title": title,
                    "branch": branch,
                    "source": identifier,
                    "state": worker_state(name, live["agents"], fresh),
                    "agent_status": sessions[0].get("agent_status") if sessions else None,
                    "session_present": None if live["agents"] is None else bool(sessions),
                    "freshness": fresh,
                    **report_fragments(bodies.get(identifier, ""), self.root),
                }
            )
        decisions = [
            t
            for t in tasks
            if not t["done"]
            and (t["section"] == "Next decision" or re.search(r"Daniel|[Pp]ick|[Dd]ecide|[Cc]hoose", t["text"]))
            and t["section"] not in ("Delivery — each step on Daniel's go", "After judging")
        ]
        blockers = [
            t
            for t in tasks
            if not t["done"]
            and re.search(
                r"unavailable|not yet|not implemented|access.*extraction|LLM access|suspended",
                t["text"],
                re.I,
            )
        ]
        changes = []
        for identifier, body in bodies.items():
            if identifier.startswith("report:"):
                changes.append(
                    {
                        "source": identifier,
                        **report_fragments(body, self.root),
                        "freshness": source_map[identifier]["freshness"],
                    }
                )
        changes.sort(key=lambda c: c["freshness"]["at"] or "", reverse=True)
        decisions_history = [
            plain(line[2:], self.root) for line in bodies.get("learnings", "").splitlines() if line.startswith("- ")
        ][-6:]
        screens = []
        for identifier, relative in self.screenshots().items():
            try:
                path = self.bounded(relative, 12_000_000)
                screens.append(
                    {
                        "id": identifier,
                        "name": path.name,
                        "group": identifier.split(":")[0],
                        "freshness": freshness(path.stat().st_mtime, now),
                    }
                )
            except (OSError, ValueError):
                pass
        screens.sort(key=lambda s: s["freshness"]["at"] or "", reverse=True)
        demos = []
        for label, port in (
            ("Atlas · cached / sample", 8101),
            ("Press · cached / sample", 8102),
            ("Collector", 8765),
        ):
            demos.append(
                {
                    "name": label,
                    "url": f"http://127.0.0.1:{port}/",
                    "state": "link from local reports; availability unverified",
                }
            )
        notes = []
        try:
            lines = self.bounded("tmp/project-tracker/inbox.jsonl", 2_000_000).read_text().splitlines()
            for line in lines[-100:]:
                try:
                    item = json.loads(line)
                    notes.append(
                        {
                            "id": item["id"],
                            "at": item["at"],
                            "text": scrub(str(item["text"]), self.root),
                            "status": "Pending acknowledgement",
                        }
                    )
                except (ValueError, KeyError, TypeError):
                    pass
        except (OSError, ValueError):
            pass
        risk = (
            decisions[0]["text"]
            if decisions
            else blockers[0]["text"]
            if blockers
            else "Inspect remaining TODO checkpoints"
        )
        summary = (
            f"Starwatch project observations at {now.astimezone(PRAGUE):%d %b %H:%M} Prague. "
            + f"{len(sources)} local sources; {len(workers)} registered workers. "
            + "Reported checkpoints are evidence references, not readiness claims."
        )
        budgets = self.budgets(now, bodies)
        rescope = bodies.get("atlas-rescope", "")
        if rescope:
            for budget in budgets:
                budget.update(cap=None, remaining=None)
            cap = re.search(r"Overall overnight ceiling is \$([0-9.]+)", rescope)
            if cap:
                budgets.insert(
                    0,
                    {
                        "name": "Current project ceiling",
                        "cap": float(cap[1]),
                        "spent": None,
                        "remaining": None,
                        "source": "atlas-rescope",
                        "basis": "Explicit current rescope; consolidated spend is not inferred.",
                        "freshness": source_map["atlas-rescope"]["freshness"],
                    },
                )
        direction = {
            "source": "atlas-rescope",
            "text": scrub(rescope, self.root),
            "observed_at": source_map.get("atlas-rescope", {}).get("freshness", {}).get("at"),
        }
        return {
            "observed_at": iso(now),
            "refresh_seconds": 5,
            "tasks": tasks,
            "workers": workers,
            "live": live,
            "sources": sources,
            "decisions": decisions,
            "blockers": blockers,
            "changes": changes[:7],
            "history": decisions_history,
            "budgets": budgets,
            "direction": direction,
            "screenshots": screens[:30],
            "demos": demos,
            "notes": notes,
            "summary": summary,
            "risk": risk,
            "completed": [
                t
                for t in tasks
                if t["done"] and (t["section"].startswith("Build") or t["section"].startswith("Exploration"))
            ],
        }
