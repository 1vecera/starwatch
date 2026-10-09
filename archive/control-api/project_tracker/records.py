"""Canonical TODO cards and local control records, guarded by one cross-process lock."""

import base64
import copy
import fcntl
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from project_tracker.model import Project, scrub

STATUSES = {"backlog", "ready", "doing", "blocked", "review", "done"}
PRIORITIES = {"low", "normal", "high", "urgent"}
NODE_STATUSES = {"implemented", "cached-only", "held", "planned", "missing"}
CHIEF_PANE = "w6:p24"
CHIEF_SESSION = "01a11d9e-1dad-7221-8c92-ea48d4094a3b"
MAX_FILE = 8_000_000
MAX_RECORDS = 5000
META = re.compile(r"^\s*<!-- control-task:(.+) -->\s*$")
CHECKBOX = re.compile(r"^(\s*- \[)([ xX])(\] )(.*)$")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix):
    return prefix + "-" + uuid.uuid4().hex[:16]


class ValidationError(ValueError):
    code = "validation"


class ConflictError(ValidationError):
    code = "conflict"


class DeliveryError(ValidationError):
    code = "delivery"


def text(value, label="text", maximum=4000, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValidationError(f"{label} must contain {'0' if empty else '1'}–{maximum} characters")
    if any(ord(c) < 32 and c not in "\n\t" for c in value) or "\x7f" in value:
        raise ValidationError(f"{label} contains control characters")
    return value.strip()


def one_line(value, label, maximum=200, empty=False):
    value = text(value, label, maximum, empty)
    if "\n" in value or "\r" in value:
        raise ValidationError(f"{label} must be one line")
    return value


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValidationError("Invalid record ID")
    return value


def strings(value, label="links", maximum=100):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValidationError(f"{label} must be a list of at most {maximum} strings")
    return [text(item, label, 1000) for item in value]


def allowed_keys(value, keys):
    if not isinstance(value, dict) or set(value) - set(keys):
        raise ValidationError(
            "Unknown or invalid fields: " + ", ".join(sorted(set(value) - set(keys)))
            if isinstance(value, dict)
            else "Expected an object"
        )


def comments(record, actor, body):
    comment = {"id": uid("comment"), "at": now(), "actor": actor, "text": text(body, maximum=4000)}
    record.setdefault("comments", []).append(comment)
    return comment


def infer_status(section, done):
    if done:
        return "done"
    if section.casefold() == "in flight":
        return "doing"
    if section.casefold() == "next decision":
        return "blocked"
    return "backlog"


def parse_cards(body):
    lines = body.splitlines(keepends=True)
    section = "Backlog"
    cards = []
    for i, line in enumerate(lines):
        if line.startswith("## "):
            section = line[3:].strip()
        match = CHECKBOX.match(line.rstrip("\n"))
        if not match:
            continue
        raw = match[4]
        metadata = {}
        meta_index = None
        if i + 1 < len(lines) and (meta := META.match(lines[i + 1].rstrip("\n"))):
            try:
                metadata = json.loads(meta[1])
                if not isinstance(metadata, dict):
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValidationError("Invalid task metadata; TODO was left untouched") from None
            meta_index = i + 1
        card_id = metadata.get("id", "task-" + hashlib.sha256(f"{i}:{raw}".encode()).hexdigest()[:16])
        card = {
            "id": card_id,
            "title": re.sub(r"\s+", " ", raw.replace("**", "").replace("`", "")).strip()[:180],
            "description": raw,
            "status": infer_status(section, match[2].lower() == "x"),
            "owner": "",
            "priority": "normal",
            "section": section,
            "raw": raw,
            "evidence": [],
            "comments": [],
            "architecture_ids": [],
            "decision_ids": [],
            "archived": False,
            "updated_at": None,
        }
        card.update(metadata)
        # The current checkbox and section remain authoritative after outside Markdown edits.
        card["section"] = section
        if match[2].lower() == "x":
            card["status"] = "done"
        elif card["status"] == "done":
            card["status"] = "backlog"
        if metadata and metadata.get("display_raw", raw) != raw:
            card["title"] = re.sub(r"\s+", " ", raw.replace("**", "").replace("`", "")).strip()[:180]
            card["description"] = raw
        cards.append((card, i, meta_index))
    ids = [card["id"] for card, _, _ in cards]
    if len(ids) != len(set(ids)):
        raise ValidationError("Duplicate task IDs; TODO was left untouched")
    return lines, cards


def metadata_line(card, displayed):
    record = dict(card, display_raw=displayed)
    # Escape HTML-comment delimiters and angle brackets without changing JSON values.
    encoded = (
        json.dumps(record, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e")
    )
    return "<!-- control-task:" + encoded + " -->\n"


def apply_card(body, card, index=None, meta_index=None, title_changed=False):
    lines = body.splitlines(keepends=True)
    displayed = card["title"] if title_changed or index is None else CHECKBOX.match(lines[index].rstrip("\n"))[4]
    checkbox = "- [" + ("x" if card["status"] == "done" else " ") + "] " + displayed + "\n"
    block = [checkbox, metadata_line(card, displayed)]
    if index is not None:
        old_section = parse_cards(body)[1]
        old = next(item for item, i, _ in old_section if i == index)
        if old["section"] == card["section"]:
            lines[index : index + (2 if meta_index is not None else 1)] = block
            return "".join(lines)
        del lines[index : index + (2 if meta_index is not None else 1)]
    section = "## " + card["section"]
    heading = next((i for i, line in enumerate(lines) if line.rstrip() == section), None)
    if heading is None:
        return "".join(lines).rstrip("\n") + "\n\n" + section + "\n\n" + "".join(block)
    following = next((i for i in range(heading + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    lines[following:following] = block + ["\n"]
    return "".join(lines)


def decision(card_id, title, options, choice=None, rationale=""):
    return {
        "id": card_id,
        "title": title,
        "status": "decided" if choice else "pending",
        "options": [{"id": ident, "label": label, "detail": detail} for ident, label, detail in options],
        "choice": choice,
        "custom_choice": "",
        "rationale": rationale,
        "owner": "Daniel",
        "task_ids": [],
        "architecture_ids": [],
        "comments": [],
        "history": [],
        "updated_at": now(),
    }


def seed_records():
    decisions = [
        decision(
            "decision-atlas",
            "Product visual direction",
            [
                ("atlas", "Atlas", "Chosen direction; existing quality requires substantial Claude refinement"),
                ("press", "Press", "Saved alternate direction"),
            ],
            "atlas",
            "Daniel chose Atlas around 01:22 on 9 October; current quality is inadequate, not accepted final design.",
        ),
        decision(
            "decision-city-scope",
            "Active research scope",
            [
                ("top-ten", "Ten largest cities", "Keep broader official archive; no ten-person cap"),
                ("broader", "Revise city scope", "Requires an explicit new planning choice"),
            ],
            "top-ten",
            "Daniel selected ten cities; only the newly authorized bounded sample may proceed.",
        ),
        decision(
            "decision-subject",
            "Final demo subject and identifying anchor",
            [
                ("fiala", "Petr Fiala", "Cached test fixture only; not the final selected subject"),
                (
                    "shortlist",
                    "Choose from checked shortlist",
                    "Babiš, Okamura, Fiala, Schillerová, Havlíček; retain ballot check",
                ),
            ],
        ),
        decision(
            "decision-claude",
            "Claude availability for final Atlas design",
            [
                ("available", "Availability confirmed", "Record actual current confirmation"),
                ("unconfirmed", "Still unconfirmed", "Earlier displayed 03:00 reset is not a guarantee"),
            ],
        ),
        decision(
            "decision-prioritization",
            "Deterministic research prioritization",
            [
                (
                    "max-or",
                    "Max / OR rule",
                    "One strong observable signal qualifies a candidate; newcomer route retained",
                )
            ],
            "max-or",
            "Daniel accepted the max/OR rule in latest 9 October steering.",
        ),
        decision(
            "decision-collection",
            "Bounded necessary top-ten collection",
            [
                (
                    "bounded",
                    "Authorized bounded sample",
                    "Candidate and party/list examples; exact 18-profile expected $0.0414 / hard ceiling $0.07 within cumulative $20",
                ),
                ("held", "Hold further collection", "Broader collection requires a separately bounded authorization"),
            ],
            "bounded",
            "Daniel authorized necessary bounded top-ten candidate and party/list examples in latest steering. Saving this record does not execute collection; other gates remain.",
        ),
    ]
    specs = [
        (
            "identity",
            "Identity & anchor",
            "product",
            "implemented",
            "Accepted/rejected account resolution; namesakes and institutional links checked",
            "report:hos-collect",
        ),
        (
            "collectors",
            "Six Apify collectors",
            "product",
            "implemented",
            "Collectors implemented; cached 120-item fixture; only explicitly authorized bounded top-ten sample may run",
            "report:hos-collect",
        ),
        (
            "run-store",
            "SQLite + per-run JSON",
            "product",
            "implemented",
            "Local run persistence and downloaded media",
            "report:hos-brief",
        ),
        (
            "transcripts",
            "Scribe + TikTok ASR",
            "product",
            "cached-only",
            "Three Scribe transcripts and eighteen ASR tracks retained; no fresh paid submission",
            "report:hos-brief",
        ),
        (
            "claims",
            "Exact attributed claims",
            "product",
            "cached-only",
            "Deterministic extractive claims; source quotes and timecodes",
            "report:hos-brief",
        ),
        (
            "verifier",
            "Claim verifier",
            "product",
            "implemented",
            "Standalone exact quote/timecode/graph checks; 21 backend tests",
            "report:hos-brief",
        ),
        (
            "briefs",
            "G1 / G2 / G3 briefs",
            "product",
            "cached-only",
            "Distinct extractive briefs; richer model synthesis unavailable",
            "report:hos-brief",
        ),
        (
            "synthesis",
            "Richer model synthesis",
            "product",
            "missing",
            "No Anthropic API key or Bedrock model access; paid Claude runtime fallback suspended",
            "report:hos-brief",
        ),
        (
            "sse-render",
            "SSE & render projections",
            "product",
            "implemented",
            "Run event stream plus network/alert/render projections",
            "report:hos-brief",
        ),
        (
            "atlas",
            "Atlas product screens",
            "product",
            "planned",
            "Atlas chosen at vis-atlas 56f47d7; quality inadequate, final Claude design pending",
            "report:hos-demo",
        ),
        (
            "official-lake",
            "Official-data lake",
            "research",
            "implemented",
            "100-city archive retained; active selectors clamped to ten cities",
            "report:hos-explore",
        ),
        (
            "prioritizer",
            "Max / OR prioritizer",
            "research",
            "implemented",
            "515 broad qualifiers / 65 protected; integrated at explore daba81d",
            "report:hos-rank",
        ),
        (
            "held-sample",
            "Authorized bounded sample",
            "research",
            "planned",
            "Exact 18-profile sample: $0.0414 expected, $0.07 hard ceiling within $20 cumulative cap; nine cities, explicit identity gaps; run not verified here",
            "report:hos-explore",
        ),
        (
            "chief",
            "Head of staff",
            "orchestration",
            "implemented",
            "Fixed chief w6:p24; session identity checked before each delivery",
            "report:hos-control",
        ),
        (
            "builders",
            "Local parallel builders",
            "orchestration",
            "implemented",
            "Normal in-process API/UI subagents; reports reflect progress, no invented panes",
            "report:hos-control",
        ),
        (
            "control-room",
            "Actionable control room",
            "orchestration",
            "planned",
            "Canonical Kanban, choices, XYFlow feedback, activity and durable chief outbox",
            "report:hos-control",
        ),
    ]
    nodes = []
    counts = {}
    for node_id, label, group, status, description, evidence in specs:
        n = counts.get(group, 0)
        counts[group] = n + 1
        offset = {"product": 0, "research": 600, "orchestration": 900}[group]
        nodes.append(
            {
                "id": node_id,
                "position": {"x": (n % 4) * 285, "y": offset + (n // 4) * 170},
                "type": "default",
                "data": {
                    "label": label,
                    "group": group,
                    "status": status,
                    "description": description,
                    "evidence": [evidence],
                    "task_ids": [],
                    "decision_ids": [],
                    "comments": [],
                },
            }
        )
    connections = [
        ("identity", "collectors"),
        ("collectors", "run-store"),
        ("run-store", "transcripts"),
        ("transcripts", "claims"),
        ("claims", "verifier"),
        ("verifier", "briefs"),
        ("synthesis", "briefs"),
        ("briefs", "sse-render"),
        ("sse-render", "atlas"),
        ("official-lake", "prioritizer"),
        ("prioritizer", "held-sample"),
        ("held-sample", "collectors"),
        ("chief", "builders"),
        ("builders", "control-room"),
        ("control-room", "chief"),
    ]
    return {
        "version": 1,
        "decisions": decisions,
        "architecture": {
            "nodes": nodes,
            "edges": [{"id": f"edge-{a}-{b}", "source": a, "target": b, "label": ""} for a, b in connections],
        },
        "messages": [],
        "activity": [],
        "observations": {},
        "workers": [],
    }


class ControlStore:
    def __init__(self, root: Path, project=None):
        self.root = root.resolve()
        self.project = project or Project(self.root)
        self.thread_lock = threading.RLock()
        self.dispatch_lock = threading.Lock()
        self.chief_cache = None
        self.chief_at = 0

    def path(self, relative):
        path = self.root / relative
        if not path.is_relative_to(self.root):
            raise ValidationError("Invalid local record path")
        for parent in (path, *path.parents):
            if parent == self.root:
                break
            if parent.is_symlink():
                raise ValidationError("Symlink records are not allowed")
        return path

    def read(self, relative, default=b""):
        path = self.path(relative)
        if not path.exists():
            return default
        if not path.is_file() or path.stat().st_size > MAX_FILE:
            raise ValidationError("Record unavailable or exceeds local limit")
        return path.read_bytes()

    def atomic(self, relative, body):
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".control-", dir=path.parent)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @contextmanager
    def locked(self):
        with self.thread_lock:
            lock_path = self.path("tmp/control-room/records.lock")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                pending = self.read("tmp/control-room/pending.json")
                if pending:
                    transaction = json.loads(pending)
                    for relative, encoded in transaction["files"].items():
                        if relative not in {
                            "TODO.md",
                            "docs/learnings.md",
                            "tmp/control-room/records.json",
                            "tmp/control-room/audit.jsonl",
                        }:
                            raise ValidationError("Invalid recovery transaction")
                        self.atomic(relative, base64.b64decode(encoded, validate=True))
                    self.path("tmp/control-room/pending.json").unlink()
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    def load(self):
        todo = self.read("TODO.md").decode()
        raw = self.read("tmp/control-room/records.json")
        records = json.loads(raw) if raw else seed_records()
        return todo, records, raw

    def revision(self, todo, raw):
        return hashlib.sha256(todo.encode() + b"\x00" + raw + b"\x00" + self.read("docs/learnings.md")).hexdigest()[:32]

    def save(self, todo, records, audit, learnings=None):
        raw = json.dumps(records, ensure_ascii=False, indent=2, allow_nan=False).encode() + b"\n"
        if len(raw) > MAX_FILE or len(todo.encode()) > MAX_FILE:
            raise ValidationError("Local records exceed size limit")
        previous_audit = self.read("tmp/control-room/audit.jsonl")
        files = {
            "TODO.md": todo.encode(),
            "tmp/control-room/records.json": raw,
            "tmp/control-room/audit.jsonl": previous_audit + json.dumps(audit, ensure_ascii=False).encode() + b"\n",
        }
        if learnings is not None:
            files["docs/learnings.md"] = learnings.encode()
        journal = {"files": {key: base64.b64encode(body).decode() for key, body in files.items()}}
        self.atomic("tmp/control-room/pending.json", json.dumps(journal).encode())
        for relative, body in files.items():
            self.atomic(relative, body)
        self.path("tmp/control-room/pending.json").unlink()
        return raw

    def event(self, records, actor, kind, body, record_id=None):
        entry = {
            "id": uid("activity"),
            "at": now(),
            "actor": actor,
            "kind": kind,
            "text": body[:1500],
            "record_id": record_id,
        }
        records["activity"].append(entry)
        records["activity"] = records["activity"][-500:]
        return entry

    def migrate(self):
        with self.locked():
            todo, records, raw = self.load()
            lines, cards = parse_cards(todo)
            if raw and all(meta is not None for _, _, meta in cards):
                return {"ok": True, "tasks": len(cards), "migrated": False}
            backup = (
                "tmp/control-room/backups/"
                + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                + "-"
                + uuid.uuid4().hex[:8]
            )
            for relative in (
                "TODO.md",
                "docs/learnings.md",
                "tmp/project-tracker/inbox.jsonl",
                "tmp/control-room/records.json",
            ):
                if self.path(relative).exists():
                    self.atomic(backup + "/" + relative, self.read(relative))
            for card, index, meta_index in reversed(cards):
                if meta_index is None:
                    card["updated_at"] = now()
                    lines.insert(index + 1, metadata_line(card, CHECKBOX.match(lines[index].rstrip("\n"))[4]))
            todo = "".join(lines)
            self.event(
                records,
                "Control room",
                "migration",
                f"Imported {len(cards)} TODO cards; original prose, sections and legacy inbox retained",
            )
            self.save(todo, records, {"at": now(), "actor": "Control room", "op": "migration", "backup": backup})
            return {"ok": True, "tasks": len(cards), "migrated": True, "backup": backup}

    def chief(self, refresh=False):
        import time

        if not refresh and self.chief_cache and time.monotonic() - self.chief_at < 3:
            return dict(self.chief_cache)
        chief = {
            "pane_id": CHIEF_PANE,
            "session_id": CHIEF_SESSION,
            "status": "unknown",
            "observed_at": now(),
            "connection": "unavailable",
            "error": None,
        }
        try:
            if os.environ.get("HERDR_ENV") != "1":
                raise DeliveryError("Herdr context is unavailable")
            output = subprocess.run(
                ["herdr", "agent", "get", CHIEF_PANE], capture_output=True, timeout=3, text=True, check=True
            )
            agent = json.loads(output.stdout)["result"]["agent"]
            session = agent.get("agent_session", {})
            if (
                agent.get("pane_id") != CHIEF_PANE
                or session.get("value") != CHIEF_SESSION
                or agent.get("cwd") != str(self.root)
                or agent.get("agent") != "codex"
            ):
                raise DeliveryError("Chief identity changed; delivery disabled")
            chief.update(status=agent.get("agent_status", "unknown"), connection="verified")
            if chief["status"] not in {"working", "idle", "done", "running", "busy", "ready"}:
                chief["error"] = "Chief is blocked or its lifecycle is unknown; delivery disabled"
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            chief["error"] = "Chief identity unavailable; delivery disabled"
        self.chief_cache, self.chief_at = chief, time.monotonic()
        return dict(chief)

    def observe(self, records):
        observations = records.setdefault("observations", {})
        changed = False
        for ident, relative in self.project.sources().items():
            if not ident.startswith("report:"):
                continue
            try:
                path = self.project.bounded(relative)
                body = path.read_text(errors="replace")
                digest = hashlib.sha256(body.encode()).hexdigest()
                previous = observations.get(ident)
                if previous and previous.get("digest") == digest:
                    continue
                # Only bounded report prose, never terminal snapshots or raw source data.
                from project_tracker.model import report_fragments

                fragment = report_fragments(body, self.root)
                self.event(records, ident.removeprefix("report:"), "report", fragment["progress"], ident)
                observations[ident] = {"digest": digest, "observed_at": now()}
                changed = True
            except (OSError, ValueError):
                continue
        chief = self.chief()
        signature = f"{chief['connection']}:{chief['status']}:{chief['error']}"
        if observations.get("chief", {}).get("signature") != signature:
            self.event(
                records,
                "Chief",
                "lifecycle",
                f"Chief observation: {chief['status']} ({chief['connection']}); lifecycle is not task completion",
                "chief",
            )
            observations["chief"] = {"signature": signature, "observed_at": chief["observed_at"]}
            changed = True
        return changed

    def public(self, todo, records, raw, include_project=True):
        tasks = [card for card, _, _ in parse_cards(todo)[1]]
        state = {
            "revision": self.revision(todo, raw),
            "observed_at": now(),
            "tasks": tasks,
            "decisions": records["decisions"],
            "architecture": records["architecture"],
            "messages": records["messages"],
            "activity": list(reversed(records["activity"][-200:])),
            "chief": self.chief(),
            "project": self.project.snapshot() if include_project else None,
        }

        # Reads retain the tracker protections: credentials and external raw paths never leave the API.
        def safe(value):
            if isinstance(value, str):
                if re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}/", value):
                    return value
                return scrub(value, self.root)
            if isinstance(value, list):
                return [safe(item) for item in value]
            if isinstance(value, dict):
                return {key: safe(item) for key, item in value.items()}
            return value

        return safe(state)

    def snapshot(self, include_project=True, observe=True):
        with self.locked():
            todo, records, raw = self.load()
            if raw and observe and self.observe(records):
                raw = self.save(todo, records, {"at": now(), "actor": "Observer", "op": "activity.observe"})
            state = self.public(todo, records, raw, include_project)
        return state

    def find(self, rows, record_id):
        identifier(record_id)
        for row in rows:
            if row["id"] == record_id:
                return row
        raise ValidationError("Record not found")

    def validate_task_patch(self, patch):
        allowed_keys(
            patch,
            {
                "title",
                "description",
                "status",
                "owner",
                "priority",
                "section",
                "evidence",
                "architecture_ids",
                "decision_ids",
                "archived",
            },
        )
        validated = {}
        for key, value in patch.items():
            if key in {"title", "owner", "section"}:
                validated[key] = one_line(value, key, 200, key == "owner")
                if key == "section" and (value.startswith("#") or "<!--" in value):
                    raise ValidationError("Invalid section")
            elif key == "description":
                validated[key] = text(value, key, 8000, True)
            elif key == "status":
                if value not in STATUSES:
                    raise ValidationError("Invalid task status")
                validated[key] = value
            elif key == "priority":
                if value not in PRIORITIES:
                    raise ValidationError("Invalid priority")
                validated[key] = value
            elif key == "archived":
                if not isinstance(value, bool):
                    raise ValidationError("archived must be boolean")
                validated[key] = value
            else:
                validated[key] = strings(value, key)
        return validated

    def validate_decision_patch(self, patch):
        allowed_keys(patch, {"title", "owner", "options", "task_ids", "architecture_ids", "rationale"})
        result = {}
        for key, value in patch.items():
            if key in {"title", "owner"}:
                result[key] = one_line(value, key, 200, key == "owner")
            elif key == "rationale":
                result[key] = text(value, key, 4000, True)
            elif key == "options":
                if not isinstance(value, list) or not 1 <= len(value) <= 20:
                    raise ValidationError("Decisions need 1–20 options")
                result[key] = []
                for option in value:
                    allowed_keys(option, {"id", "label", "detail"})
                    result[key].append(
                        {
                            "id": identifier(option.get("id")),
                            "label": one_line(option.get("label"), "label", 200),
                            "detail": text(option.get("detail", ""), "detail", 2000, True),
                        }
                    )
                if len({item["id"] for item in result[key]}) != len(value):
                    raise ValidationError("Duplicate option IDs")
            else:
                result[key] = strings(value, key)
        return result

    def validate_position(self, position):
        allowed_keys(position, {"x", "y"})
        result = {}
        for key in ("x", "y"):
            value = position.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or abs(value) > 100000
            ):
                raise ValidationError("Positions require finite coordinates within ±100000")
            result[key] = value
        return result

    def validate_node_patch(self, patch):
        allowed_keys(patch, {"position", "data"})
        result = {}
        if "position" in patch:
            result["position"] = self.validate_position(patch["position"])
        if "data" in patch:
            allowed_keys(
                patch["data"], {"label", "group", "status", "description", "evidence", "task_ids", "decision_ids"}
            )
            result["data"] = {}
            for key, value in patch["data"].items():
                if key == "status":
                    if value not in NODE_STATUSES:
                        raise ValidationError("Invalid architecture status")
                    result["data"][key] = value
                elif key in {"evidence", "task_ids", "decision_ids"}:
                    result["data"][key] = strings(value, key)
                else:
                    result["data"][key] = text(value, key, 4000 if key == "description" else 200, key == "description")
        return result

    def mutate(self, envelope, require_revision=False):
        if not isinstance(envelope, dict):
            raise ValidationError("Mutation must be an object")
        # Reject unbounded CLI inputs as well as HTTP payloads.
        try:
            encoded = json.dumps(envelope, allow_nan=False)
        except (ValueError, TypeError):
            raise ValidationError("Mutation must contain finite JSON values") from None
        if len(encoded.encode()) > 64_000:
            raise ValidationError("Mutation exceeds 64000 bytes")
        op = one_line(envelope.get("op"), "operation", 80)
        actor = one_line(envelope.get("actor", "Daniel"), "actor", 100)
        base = envelope.get("base_revision")
        if require_revision and not isinstance(base, str):
            raise ValidationError("base_revision is required")
        with self.locked():
            todo, records, raw = self.load()
            if not raw:
                raise ValidationError("Run the migrate command before making changes")
            revision = self.revision(todo, raw)
            if base is not None and base != revision:
                raise ConflictError("The project changed; refresh and reapply your edit")
            if any(len(records.get(key, [])) >= MAX_RECORDS for key in ("decisions", "messages")):
                raise ValidationError("Record capacity reached")
            result = None
            learnings = None
            fields = {key: value for key, value in envelope.items() if key not in {"op", "actor", "base_revision"}}
            if op.startswith("task.") or (op == "progress.record" and fields.get("task_id")):
                lines, cards = parse_cards(todo)
                if op == "task.create":
                    patch = self.validate_task_patch(fields)
                    if not patch.get("title"):
                        raise ValidationError("Task title is required")
                    result = {
                        "id": uid("task"),
                        "title": patch["title"],
                        "description": "",
                        "status": "backlog",
                        "owner": "",
                        "priority": "normal",
                        "section": "Control room",
                        "raw": patch["title"],
                        "evidence": [],
                        "comments": [],
                        "architecture_ids": [],
                        "decision_ids": [],
                        "archived": False,
                        "updated_at": now(),
                    }
                    result.update(patch)
                    todo = apply_card(todo, result)
                else:
                    record_id = fields.get("task_id") if op == "progress.record" else fields.get("id")
                    card, index, meta = next(
                        ((card, i, m) for card, i, m in cards if card["id"] == record_id), (None, None, None)
                    )
                    if card is None:
                        raise ValidationError("Task not found")
                    if op == "task.update":
                        allowed_keys(fields, {"id", "patch"})
                        patch = self.validate_task_patch(fields.get("patch"))
                    elif op == "task.move":
                        allowed_keys(fields, {"id", "status"})
                        patch = self.validate_task_patch({"status": fields.get("status")})
                    elif op == "task.comment":
                        allowed_keys(fields, {"id", "text"})
                        comments(card, actor, fields.get("text"))
                        patch = {}
                    elif op == "progress.record":
                        allowed_keys(fields, {"text", "task_id", "status", "evidence"})
                        text(fields.get("text"), maximum=4000)
                        patch = self.validate_task_patch(
                            {k: v for k, v in fields.items() if k in {"status", "evidence"}}
                        )
                    else:
                        raise ValidationError("Unknown operation")
                    card.update(patch)
                    card["updated_at"] = now()
                    todo = apply_card(todo, card, index, meta, "title" in patch)
                    result = card
            elif op.startswith("decision."):
                if op == "decision.create":
                    patch = self.validate_decision_patch(fields)
                    if not patch.get("title") or not patch.get("options"):
                        raise ValidationError("Decision title and options are required")
                    result = decision(uid("decision"), patch["title"], [])
                    result.update(patch)
                    records["decisions"].append(result)
                else:
                    result = self.find(records["decisions"], fields.get("id"))
                    if op == "decision.update":
                        allowed_keys(fields, {"id", "patch"})
                        patch = self.validate_decision_patch(fields.get("patch"))
                        if (
                            "options" in patch
                            and result.get("choice")
                            and result["choice"] not in {item["id"] for item in patch["options"]}
                        ):
                            raise ValidationError("Cannot remove the current chosen option; revise the choice first")
                        result.update(patch)
                    elif op == "decision.comment":
                        allowed_keys(fields, {"id", "text"})
                        comments(result, actor, fields.get("text"))
                    elif op == "decision.choose":
                        allowed_keys(fields, {"id", "choice", "custom_choice", "rationale"})
                        choice = fields.get("choice")
                        custom = text(fields.get("custom_choice", ""), "custom choice", 2000, True)
                        rationale = text(fields.get("rationale", ""), "rationale", 4000, True)
                        if choice is not None and choice not in {item["id"] for item in result["options"]}:
                            raise ValidationError("Choose a listed option or enter a custom choice")
                        if bool(choice) == bool(custom):
                            raise ValidationError("Choose exactly one option or custom choice")
                        history = {
                            "id": uid("choice"),
                            "at": now(),
                            "actor": actor,
                            "source": "control-room",
                            "choice": choice,
                            "custom_choice": custom,
                            "rationale": rationale,
                            "previous_choice": result.get("choice"),
                            "previous_custom_choice": result.get("custom_choice", ""),
                        }
                        result.update(choice=choice, custom_choice=custom, rationale=rationale, status="decided")
                        result["history"].append(history)
                        chosen = custom or next(
                            option["label"] for option in result["options"] if option["id"] == choice
                        )
                        summary = f"{actor} chose {chosen} for {result['title']}. Rationale: {rationale or 'Not supplied'}. Planning record only; no selected action was executed."
                        learnings = (
                            self.read("docs/learnings.md").decode().rstrip("\n")
                            + "\n\n- "
                            + history["at"]
                            + " — "
                            + summary.replace("\n", " ")
                            + " Source: control-room; decision "
                            + result["id"]
                            + "; audit "
                            + history["id"]
                            + ".\n"
                        )
                        self.queue_message(records, actor, summary, result["id"])
                    else:
                        raise ValidationError("Unknown operation")
                    result["updated_at"] = now()
            elif op.startswith("architecture."):
                if op == "architecture.layout":
                    allowed_keys(fields, {"positions"})
                    positions = fields.get("positions")
                    if not isinstance(positions, list) or len(positions) > 1000:
                        raise ValidationError("positions must be a bounded list")
                    for position in positions:
                        allowed_keys(position, {"id", "x", "y"})
                        node = self.find(records["architecture"]["nodes"], position.get("id"))
                        node["position"] = self.validate_position({key: position.get(key) for key in ("x", "y")})
                    result = records["architecture"]
                elif op == "architecture.edge":
                    allowed_keys(fields, {"edge"})
                    edge = fields.get("edge")
                    allowed_keys(edge, {"id", "source", "target", "label"})
                    edge = {
                        "id": identifier(edge.get("id")),
                        "source": identifier(edge.get("source")),
                        "target": identifier(edge.get("target")),
                        "label": text(edge.get("label", ""), "label", 200, True),
                    }
                    self.find(records["architecture"]["nodes"], edge["source"])
                    self.find(records["architecture"]["nodes"], edge["target"])
                    existing = next(
                        (item for item in records["architecture"]["edges"] if item["id"] == edge["id"]), None
                    )
                    if existing:
                        existing.update(edge)
                    else:
                        records["architecture"]["edges"].append(edge)
                    result = edge
                else:
                    result = self.find(records["architecture"]["nodes"], fields.get("id"))
                    if op == "architecture.update":
                        allowed_keys(fields, {"id", "patch"})
                        patch = self.validate_node_patch(fields.get("patch"))
                        if "data" in patch:
                            result["data"].update(patch["data"])
                        if "position" in patch:
                            result["position"] = patch["position"]
                    elif op == "architecture.feedback":
                        allowed_keys(fields, {"id", "text"})
                        comments(result["data"], actor, fields.get("text"))
                    else:
                        raise ValidationError("Unknown operation")
            elif op.startswith("message."):
                if op == "message.send":
                    allowed_keys(fields, {"text"})
                    result = self.queue_message(records, actor, text(fields.get("text"), maximum=4000))
                else:
                    result = self.find(records["messages"], fields.get("id"))
                    if op == "message.retry":
                        allowed_keys(fields, {"id"})
                        if result["status"] != "failed":
                            raise ValidationError(
                                "Only failed messages can be retried; submitted messages may already have been read"
                            )
                        result.update(status="queued", error=None, attempt_started_at=None)
                    elif op == "message.ack":
                        allowed_keys(fields, {"id", "reply"})
                        if result["status"] not in {"submitted", "acknowledged"}:
                            raise ValidationError("A message must have been submitted before acknowledgement")
                        result.update(
                            status="acknowledged",
                            acknowledged_at=now(),
                            reply=text(fields.get("reply", ""), "reply", 4000, True),
                        )
                    else:
                        raise ValidationError("Unknown operation")
            elif op == "progress.record":
                allowed_keys(fields, {"text", "task_id", "status", "evidence"})
                if "status" in fields or "evidence" in fields:
                    raise ValidationError("Task status/evidence requires task_id")
                result = {"id": uid("progress"), "text": text(fields.get("text"), maximum=4000), "at": now()}
            elif op in {"worker.register", "worker.update"}:
                allowed_keys(
                    fields,
                    {
                        "name",
                        "branch",
                        "description",
                        "status",
                        "kind",
                        "pane_id",
                        "session_id",
                        "cwd",
                        "model",
                        "brief",
                    },
                )
                name = fields.get("name")
                if not isinstance(name, str) or not re.fullmatch(r"hos-[a-z0-9][a-z0-9_-]{0,55}", name):
                    raise ValidationError("Worker name must be a safe hos- name")
                branch = one_line(fields.get("branch", name.removeprefix("hos-")), "branch", 100)
                if not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", branch):
                    raise ValidationError("Invalid worker branch")
                description = one_line(fields.get("description", "Local subagent"), "description", 600)
                status = one_line(fields.get("status", "working"), "status", 100)
                kind = fields.get("kind", "local-subagent")
                if kind not in {"local-subagent", "herdr"}:
                    raise ValidationError("Worker kind must be local-subagent or herdr")
                extras = {}
                for key in ("pane_id", "session_id", "cwd", "model", "brief"):
                    if key in fields:
                        extras[key] = one_line(fields[key], key, 300)
                if "pane_id" in extras and not re.fullmatch(r"w[0-9]+:p[A-Za-z0-9]+", extras["pane_id"]):
                    raise ValidationError("Invalid worker pane")
                if "session_id" in extras and not re.fullmatch(r"[a-fA-F0-9-]{20,80}", extras["session_id"]):
                    raise ValidationError("Invalid worker session")
                if "cwd" in extras and not Path(extras["cwd"]).resolve().is_relative_to(self.root):
                    raise ValidationError("Worker cwd must belong to this project")
                if "brief" in extras and not re.fullmatch(r"docs/tasks/hos-[a-z0-9_-]+\.md", extras["brief"]):
                    raise ValidationError("Invalid worker brief")
                result = {
                    "id": name,
                    "name": name,
                    "branch": branch,
                    "description": description,
                    "status": status,
                    "kind": kind,
                    "updated_at": now(),
                    **extras,
                }
                workers = records.setdefault("workers", [])
                workers[:] = [item for item in workers if item["id"] != name] + [result]
                lines = todo.splitlines(keepends=True)
                start = next((i for i, line in enumerate(lines) if line.rstrip() == "## In flight"), None)
                if start is None:
                    todo = todo.rstrip() + "\n\n## In flight\n\n"
                    lines = todo.splitlines(keepends=True)
                    start = len(lines) - 2
                end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
                identity = "normal local Codex subagent" if kind == "local-subagent" else "Herdr agent"
                details = " · ".join(f"{key} `{value}`" for key, value in extras.items())
                row = f"- `{name}` · {identity} · branch `{branch}` · {details + ' · ' if details else ''}{description} · {status}; progress in `docs/reports/{name}.md`.\n"
                existing = next(
                    (
                        i
                        for i in range(start + 1, end)
                        if re.match(r"\s*- `" + re.escape(name) + r"`(?:\s|$)", lines[i])
                    ),
                    None,
                )
                if existing is None:
                    lines.insert(start + 2, row)
                else:
                    lines[existing] = row
                todo = "".join(lines)
            else:
                raise ValidationError("Unknown operation")
            kind = op
            summary = (
                text(fields["text"], maximum=4000)
                if op
                in {"progress.record", "task.comment", "decision.comment", "architecture.feedback", "message.send"}
                else op.replace(".", " ") + ": " + str(result.get("title", result.get("id", "saved")))
            )
            self.event(records, actor, kind, summary, result.get("id"))
            audit = {
                "id": uid("audit"),
                "at": now(),
                "actor": actor,
                "op": op,
                "record_id": result.get("id"),
                "base_revision": revision,
            }
            raw = self.save(todo, records, audit, learnings)
            state = self.public(todo, records, raw)
            return {"ok": True, "state": state, "result": copy.deepcopy(result)}

    def queue_message(self, records, actor, body, related_id=None):
        message = {
            "id": uid("message"),
            "text": text(body, maximum=8000),
            "actor": actor,
            "target": "chief",
            "status": "queued",
            "created_at": now(),
            "submitted_at": None,
            "acknowledged_at": None,
            "error": None,
            "reply": None,
            "attempt_started_at": None,
            "related_id": related_id,
        }
        records["messages"].append(message)
        return message

    def dispatch_pending(self, maximum=10, recover_interrupted=False):
        """Persist claim before delivery. An interrupted submission needs explicit retry."""
        if not self.dispatch_lock.acquire(blocking=False):
            return 0
        completed = 0
        try:
            for _ in range(maximum):
                with self.locked():
                    todo, records, raw = self.load()
                    if not raw:
                        return completed
                    if recover_interrupted:
                        for message in records["messages"]:
                            if message["status"] == "queued" and message.get("attempt_started_at"):
                                message.update(
                                    status="failed",
                                    error="Previous delivery was interrupted; it may have been submitted. Inspect chief before explicit retry.",
                                )
                                self.event(records, "Outbox", "message.failed", message["error"], message["id"])
                        raw = self.save(todo, records, {"at": now(), "actor": "Outbox", "op": "message.recover"})
                        recover_interrupted = False
                    message = next(
                        (
                            item
                            for item in records["messages"]
                            if item["status"] == "queued" and not item.get("attempt_started_at")
                        ),
                        None,
                    )
                    if message is None:
                        return completed
                    message["attempt_started_at"] = now()
                    self.save(
                        todo,
                        records,
                        {"at": now(), "actor": "Outbox", "op": "message.claim", "record_id": message["id"]},
                    )
                    claimed = copy.deepcopy(message)
                chief = self.chief(refresh=True)
                error = None
                if chief["connection"] != "verified" or chief.get("error"):
                    error = chief.get("error") or "Chief identity unavailable; delivery disabled"
                else:
                    prompt = f"[Control room message {claimed['id']} from {claimed['actor']}]\n{claimed['text']}\n\nAcknowledge/reply explicitly using the project_tracker CLI message.ack operation with this ID. Submitted is not acknowledgement."
                    try:
                        output = subprocess.run(
                            ["herdr", "agent", "prompt", CHIEF_PANE, prompt],
                            capture_output=True,
                            timeout=8,
                            text=True,
                            check=True,
                        )
                        response = json.loads(output.stdout)
                        if response.get("error") or "result" not in response:
                            raise DeliveryError("Herdr did not confirm submission")
                    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
                        error = "Herdr submission failed or was not confirmed; it may have been submitted. Inspect chief before retry."
                with self.locked():
                    todo, records, raw = self.load()
                    message = self.find(records["messages"], claimed["id"])
                    if error:
                        message.update(status="failed", error=error)
                    else:
                        message.update(status="submitted", submitted_at=now(), error=None)
                    self.event(
                        records,
                        "Outbox",
                        "message." + message["status"],
                        error or "Message submitted to verified chief; acknowledgement pending",
                        message["id"],
                    )
                    self.save(
                        todo,
                        records,
                        {
                            "at": now(),
                            "actor": "Outbox",
                            "op": "message." + message["status"],
                            "record_id": message["id"],
                        },
                    )
                completed += 1
            return completed
        finally:
            self.dispatch_lock.release()
