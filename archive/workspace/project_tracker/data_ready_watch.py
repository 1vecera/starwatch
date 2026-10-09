"""One local, durable data-readiness notification. Delivery is opt-in; no collector calls."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path("/home/vecera/code/agents007-hackathon")
SESSION = "5ed21d54-fbbd-4b74-80c3-3f78ee96b425"
PANE = "w6:p2K"
UNIT = "starwatch-data-ready-watch"
NOTIFICATION = (
    "starwatch-data-ready-" + hashlib.sha256((SESSION + ":first-meaningful-dataset:v1").encode()).hexdigest()[:20]
)
CITIES = {
    "554782": "Praha",
    "582786": "Brno",
    "554821": "Ostrava",
    "554791": "Plzeň",
    "563889": "Liberec",
    "500496": "Olomouc",
    "544256": "České Budějovice",
    "569810": "Hradec Králové",
    "555134": "Pardubice",
    "554804": "Ústí nad Labem",
}
EXPORTS = {
    f"{name}.json" for name in ("areas", "entities", "accounts", "assets", "coverage", "claims", "topics", "quality")
}
EXPORTS.add("graph.duckdb")
QUALITY_CHECKS = {
    "false_owned_asset",
    "invalid_current_candidacy",
    "missing_list",
    "multiple_account_owners",
    "negative_metric",
    "null_without_reason",
    "undated_measured_metric",
    "unreviewed_relation_promotion",
}
TERMINAL_STATES = {"dispatch_intent", "uncertain", "submitted", "acknowledged"}


class GateError(ValueError):
    """A safe preflight failure; no dispatch has begun."""


def now():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise GateError("Duplicate JSON key")
            result[key] = value
        return result

    return json.loads(path.read_bytes(), object_pairs_hook=unique_pairs)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition, reason):
    if not condition:
        raise GateError(reason)


def safe_path(root, relative):
    require(isinstance(relative, str), "Path must be a relative string")
    parts = Path(relative).parts
    require(parts and not Path(relative).is_absolute(), "Absolute/empty checkpoint path")
    require(not any(p in {"..", "."} or p.startswith(".building-") for p in parts), "Unsafe/building path")
    path = root.joinpath(*parts)
    require(all(not root.joinpath(*parts[:i]).is_symlink() for i in range(1, len(parts) + 1)), "Checkpoint symlink")
    require(path.resolve().is_relative_to(root.resolve()), "Checkpoint escapes read root")
    return path


def indexed(rows, key):
    require(isinstance(rows, list), "Export must be a JSON array")
    require(all(isinstance(row, dict) and isinstance(row.get(key), str) for row in rows), "Malformed export row")
    result = {row[key]: row for row in rows}
    require(len(result) == len(rows), "Duplicate export identity")
    return result


def checkpoint(project):
    read_root = project / "tmp/production/read"
    pointer = load_json(read_root / "current.json")  # Exactly one pointer read; all subsequent reads are pinned.
    require(isinstance(pointer, dict), "Malformed pointer")
    cid = pointer.get("checkpoint_id")
    require(isinstance(cid, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", cid), "Invalid checkpoint ID")
    schema = pointer.get("schema_version", "")
    require(re.fullmatch(r"starwatch-production-graph/1\.\d+\.\d+", schema), "Unsupported graph schema")
    require(pointer.get("manifest") == f"checkpoints/{cid}/manifest.json", "Manifest does not pin checkpoint")
    require(pointer.get("database") == f"checkpoints/{cid}/graph.duckdb", "Database does not pin checkpoint")
    manifest_path = safe_path(read_root, pointer["manifest"])
    manifest_sha = digest(manifest_path)
    require(manifest_sha == pointer.get("manifest_sha256"), "Manifest SHA mismatch")
    manifest = load_json(manifest_path)
    require(isinstance(manifest, dict), "Malformed manifest")
    require(
        manifest.get("checkpoint_id") == cid and manifest.get("schema_version") == schema, "Pointer/manifest mismatch"
    )
    files = manifest.get("files")
    require(isinstance(files, dict) and EXPORTS <= files.keys(), "Missing exported hash")
    directory = manifest_path.parent
    require({p.name for p in directory.iterdir()} == set(files) | {"manifest.json"}, "Unlisted checkpoint file")
    for name, info in files.items():
        require(isinstance(name, str) and Path(name).name == name, "Unsafe export filename")
        path = safe_path(read_root, f"checkpoints/{cid}/{name}")
        require(isinstance(info, dict) and type(info.get("bytes")) is int, "Missing export size")
        require(path.is_file() and path.stat().st_size == info["bytes"], "Export size mismatch")
        require(digest(path) == info.get("sha256"), "Export SHA mismatch")
    data = {
        name: load_json(directory / f"{name}.json")
        for name in ("areas", "entities", "accounts", "assets", "coverage", "claims", "topics", "quality")
    }
    quality = data["quality"]
    require(isinstance(quality, dict), "Malformed quality report")
    require(quality == manifest.get("quality") and quality.get("status") == "passed", "Quality did not pass")
    checks = quality.get("checks")
    require(isinstance(checks, dict) and QUALITY_CHECKS <= checks.keys(), "Missing documented quality checks")
    require(all(type(v) is int and v == 0 for v in checks.values()), "Nonzero/unknown quality check")
    areas, coverage = indexed(data["areas"], "area_id"), indexed(data["coverage"], "area_id")
    require(set(areas) == set(CITIES) == set(coverage), "Ten city rosters required")
    require(
        all(type(r.get("valid_candidacies")) is int and r["valid_candidacies"] > 0 for r in coverage.values()),
        "Empty city roster",
    )
    entities, accounts, assets = (
        indexed(data[name], key)
        for name, key in (("entities", "entity_id"), ("accounts", "account_id"), ("assets", "asset_id"))
    )
    candidates = Counter()
    for row in entities.values():
        require(row.get("area_id") in areas, "Entity city missing")
        if row.get("kind") == "current_candidacy" and row.get("qualified") is True:
            require(row.get("local_role_status") == "official_registered_candidacy", "Unadmitted candidate role")
            require(
                row.get("list_id") in entities and entities[row["list_id"]].get("kind") == "local_list",
                "Candidate list missing",
            )
            candidates[row["area_id"]] += 1
    account_cities = Counter()
    for row in accounts.values():
        require(
            row.get("entity_id") in entities and row.get("identity_status") == "confirmed", "Unverified account owner"
        )
        require(row.get("public") is not False, "Private account")
        account_cities[entities[row["entity_id"]]["area_id"]] += 1
    asset_cities = Counter()
    for row in assets.values():
        require(row.get("owner_account_id") in accounts, "Asset owner missing")
        require(row.get("verification_status") == "verified_publication_owner", "Unverified publication owner")
        owner = accounts[row["owner_account_id"]]
        asset_cities[entities[owner["entity_id"]]["area_id"]] += 1
    for area, row in coverage.items():
        require(row.get("meaningful_candidates") == candidates[area], "Candidate coverage mismatch")
        require(row.get("owned_publications") == asset_cities[area], "Publication coverage mismatch")
        require(
            row.get("confirmed_list_accounts", 0) + row.get("confirmed_person_accounts", 0) == account_cities[area],
            "Account coverage mismatch",
        )
    owners = len({row["entity_id"] for row in accounts.values()})
    require(
        sum(candidates.values()) >= 300 and owners >= 10 and len(assets) >= 100 and len(asset_cities) >= 5,
        "Dataset below meaningful readiness threshold",
    )
    require(isinstance(data["claims"], list) and isinstance(data["topics"], list), "Malformed claims/topics")
    counts = manifest.get("counts", {})
    require(
        counts.get("area") == 10
        and counts.get("verified_accounts") == len(accounts)
        and counts.get("verified_assets") == len(assets)
        and counts.get("claim") == len(data["claims"])
        and counts.get("topic") == len(data["topics"]),
        "Manifest/export count mismatch",
    )
    require(
        quality.get("claims_admitted") == len(data["claims"]) and quality.get("topics_admitted") == len(data["topics"]),
        "Admission count mismatch",
    )
    # Detect changes to pinned exports during verification without rereading the mutable pointer.
    require(digest(manifest_path) == manifest_sha, "Manifest changed while checking")
    return {
        "checkpoint_id": cid,
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "candidates": sum(candidates.values()),
        "accounts": len(accounts),
        "account_owners": owners,
        "assets": len(assets),
        "populated_cities": len(asset_cities),
        "claims": len(data["claims"]),
        "topics": len(data["topics"]),
        "city_assets": {k: asset_cities[k] for k in CITIES},
        "hashed_files": len(files),
    }


def identity(agent, project):
    session = agent.get("agent_session") or {}
    return (
        agent.get("agent") == "claude"
        and session.get("agent") == "claude"
        and session.get("kind") == "id"
        and session.get("value") == SESSION
        and agent.get("cwd") == str(project)
        and agent.get("foreground_cwd") == str(project)
        and bool(re.fullmatch(r"w\d+:p[A-Za-z0-9]+", agent.get("pane_id", "")))
    )


def main_input(text):
    """Use only the active prompt/footer of the CURRENT screen, never old scrollback."""
    lines = text.splitlines()
    prompts = [i for i, line in enumerate(lines) if re.match(r"^\s*❯", line)]
    require(bool(prompts), "No current Claude input")
    footer = lines[prompts[-1] :]
    prompt = re.sub(r"^\s*❯\s*", "", footer[0]).strip()
    require(prompt in {"", "Press up to edit queued messages"}, "Typed draft or child input")
    require(not any("Message @" in line for line in footer), "Child input selected")
    selected = [line.strip() for line in footer if re.match(r"^\s*●\s+", line)]
    if selected:
        require(selected == ["● main"], "Selected child/menu")
    else:
        require(not any(re.match(r"^\s*◯\s+", line) for line in footer), "Unresolved agent selection menu")
        normal_footer = " ".join(footer[1:])
        require(
            "⏵⏵ bypass permissions on" in normal_footer
            and re.search(r"←\s*\d+\s+agents?\b", normal_footer)
            and re.search(r"↓ to (?:manage|man…)(?:\s|$)", normal_footer),
            "Collapsed main footer not positively visible",
        )
    require(
        not any(re.search(r"select (an? )?agent|selection menu|approve|allow once", line, re.I) for line in footer),
        "Selection/approval menu visible",
    )
    # A wrapped draft sits between the input row and its separator; reject every nonempty line there.
    for line in footer[1:]:
        if re.fullmatch(r"\s*[─━-]{3,}\s*", line):
            break
        require(not line.strip() or line.strip() == "Press up to edit queued messages", "Wrapped input draft")
    else:
        raise GateError("Input boundary not visible")


class Herdr:
    def __init__(self, binary=None):
        self.binary = binary or shutil.which("herdr") or "/home/vecera/.local/bin/herdr"

    def run(self, *args):
        return subprocess.run([self.binary, "agent", *args], capture_output=True, text=True, timeout=15, check=True)

    def agents(self):
        return json.loads(self.run("list").stdout)["result"]["agents"]

    def get(self, pane):
        return json.loads(self.run("get", pane).stdout)["result"]["agent"]

    def read(self, pane, source):
        return self.run("read", pane, "--source", source, "--lines", "120").stdout

    def send(self, pane, prompt):
        return self.run("prompt", pane, prompt).stdout  # Native queue; no idle wait, focus or keys.


def preflight(transport, project):
    matches = [agent for agent in transport.agents() if identity(agent, project)]
    require(len(matches) == 1, "Exact Claude session/cwd not uniquely found")
    pane = matches[0]["pane_id"]
    for _ in range(2):  # Recheck live identity and BOTH current screens immediately before dispatch.
        agent = transport.get(pane)
        require(identity(agent, project), "Destination identity changed")
        require(agent.get("agent_status") in {"working", "idle", "done"}, "Claude input lifecycle blocked/unknown")
        for source in ("visible", "detection"):
            main_input(transport.read(pane, source))
    return {
        "pane_id": pane,
        "session_id": SESSION,
        "status": agent["agent_status"],
        "routing": "current visible+detection selected main; empty input; native queue",
        "observed_at": now(),
    }


def prompt_text(project, snapshot, ack):
    populated = ", ".join(CITIES[k] for k, v in snapshot["city_assets"].items() if v)
    gaps = ", ".join(CITIES[k] for k, v in snapshot["city_assets"].items() if not v) or "none"
    return (
        f"Daniel authorized continuing/refreshing the existing local Starwatch screen integration once verified data "
        f"exists. Notification ID: {NOTIFICATION}. Verified checkpoint: {snapshot['checkpoint_id']}; 10 city rosters, "
        f"{snapshot['candidates']} qualifying candidates, {snapshot['accounts']} verified accounts of "
        f"{snapshot['account_owners']} owners, {snapshot['assets']} independently attributable publications across "
        f"{snapshot['populated_cities']} cities ({populated}). No verified publications yet: {gaps}. "
        f"Promoted production claims/topics: {snapshot['claims']}/{snapshot['topics']}. All documented quality "
        f"checks pass; manifest and all {snapshot['hashed_files']} exported file hashes were verified. "
        f"Stable pointer: {project / 'tmp/production/read/current.json'}. Contract: "
        f"{project / 'docs/explore/production-data-contract.md'}. Pin read-only immutable manifest "
        f"{snapshot['manifest']} (SHA256 {snapshot['manifest_sha256']}); use verified ownership/admission views, "
        f"preserve unknowns/source dates and show city gaps and incomplete sampled history honestly. "
        f"The production checkpoint does not establish complete history or retained full video/media bytes. "
        f"Existing importer: {project / '.claude/worktrees/app/tools/export_real.py'}. "
        f"Existing importer report: {project / 'docs/reports/sol-app-data.md'}. Its first export already retained "
        f"135 publication previews; 52 reviewed captions/69 claims were separately reviewed_pending_promotion, "
        f"not promoted production claims. Coordinate with existing sol-app-data if still active and continue "
        f"screen integration using that exporter; do not launch a competing importer. Keep work local; existing "
        f"spend/publication gates remain. Acknowledge receipt by atomically writing JSON to {ack} with "
        f'{{"notification_id":"{NOTIFICATION}","checkpoint_id":"{snapshot["checkpoint_id"]}",'
        f'"session_id":"{SESSION}","status":"acknowledged"}}. Then continue app implementation without '
        f"waiting on chief."
    )


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".new")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def record(state_dir, state):
    state["updated_at"] = now()
    atomic_json(state_dir / "state.json", state)
    atomic_json(state_dir / "status.json", {k: v for k, v in state.items() if k not in {"prompt", "receipt"}})
    with (state_dir / "events.jsonl").open("a") as stream:
        stream.write(json.dumps({"at": now(), "status": state["status"], "reason": state.get("reason")}) + "\n")


def acknowledgement(state_dir, state):
    path = state_dir / "ack.json"
    if not path.exists():
        return False
    ack = load_json(path)
    require(
        isinstance(ack, dict)
        and ack.get("notification_id") == NOTIFICATION
        and ack.get("session_id") == SESSION
        and ack.get("checkpoint_id") == state["snapshot"]["checkpoint_id"]
        and ack.get("status") == "acknowledged",
        "Acknowledgement identity mismatch",
    )
    state.update(status="acknowledged", ack=ack, acknowledged_at=now(), reason="Exact local acknowledgement received")
    return True


def stop_timer():
    subprocess.run(["systemctl", "--user", "stop", f"{UNIT}.timer"], capture_output=True, timeout=10, check=True)


def tick(project=PROJECT, *, deliver=False, transport=None, stop=stop_timer):
    project = project.resolve()
    state_dir = project / "tmp/production/data-ready-watch"
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / "watch.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "busy", "reason": "Another tick owns the dispatch lock"}
        state_path = state_dir / "state.json"
        try:
            state = (
                load_json(state_path) if state_path.exists() else {"notification_id": NOTIFICATION, "status": "ready"}
            )
            require(
                isinstance(state, dict) and state.get("status") in TERMINAL_STATES | {"ready", "waiting-for-main"},
                "Unknown durable state; automatic dispatch suppressed",
            )
            require(state.get("notification_id") == NOTIFICATION, "Unknown existing notification state")
            if state.get("status") in TERMINAL_STATES:
                if state["status"] == "dispatch_intent":
                    state.update(status="uncertain", reason="Interrupted dispatch intent; never automatically resend")
                if state["status"] != "acknowledged":
                    try:
                        acknowledgement(state_dir, state)
                    except (ValueError, OSError, TypeError, KeyError):
                        state["reason"] = "Invalid acknowledgement; dispatch remains suppressed"
                if state["status"] == "acknowledged" and deliver:
                    try:
                        stop()
                        state["timer_stopped"] = True
                    except (OSError, subprocess.SubprocessError):
                        state["timer_stopped"] = False  # Acknowledged ticks are inert even if stop fails.
                record(state_dir, state)
                return state
            snapshot = checkpoint(project)
            state.update(
                status="ready", snapshot=snapshot, dry_run=not deliver, reason="Dataset readiness gates passed"
            )
            prompt = prompt_text(project, snapshot, state_dir / "ack.json")
            state["prompt"] = prompt
            try:
                route = preflight(transport or Herdr(), project)
            except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError):
                state.update(status="waiting-for-main", reason="Live identity/selected-main/empty-input gate deferred")
                record(state_dir, state)
                return state
            state["route"] = route
            if not deliver:
                record(state_dir, state)
                return state
            state.update(status="dispatch_intent", dispatch_started_at=now(), reason="Durable intent before submission")
            record(state_dir, state)  # fsync state + directory BEFORE crossing the transport boundary.
            try:
                receipt = (transport or Herdr()).send(route["pane_id"], prompt)
                state["receipt"] = receipt  # Preserve actual return even if its validation fails.
                result = json.loads(receipt)["result"]
                require(
                    result.get("type") == "agent_prompted"
                    and identity(result.get("agent", {}), project)
                    and result["agent"].get("pane_id") == route["pane_id"],
                    "Unconfirmed submission receipt",
                )
                state.update(
                    status="submitted", submitted_at=now(), reason="Native prompt written; awaiting acknowledgement"
                )
            except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError) as error:
                state.update(
                    status="uncertain",
                    reason="Ambiguous transport result; never automatically resend",
                    transport_error_type=type(error).__name__,
                )
            record(state_dir, state)
            return state
        except (ValueError, OSError, KeyError, TypeError) as error:
            # Never overwrite possibly-dispatched state when its durable record is unreadable.
            failure = {
                "status": "error",
                "reason": "Readiness/state verification failed",
                "error_type": type(error).__name__,
            }
            atomic_json(state_dir / "status.json", failure)
            return failure


def prepare(project=PROJECT):
    """Write reviewable transient-unit artifacts only; do not start/install a timer."""
    project = project.resolve()
    directory = project / "tmp/production/data-ready-watch"
    directory.mkdir(parents=True, exist_ok=True)
    checkout = Path(__file__).resolve().parents[1]
    require(os.environ.get("HERDR_ENV") == "1" and os.environ.get("HERDR_SOCKET_PATH"), "Run preparation inside Herdr")
    socket = os.environ["HERDR_SOCKET_PATH"]
    require(Path(socket).is_absolute() and not any(c in socket for c in '\n\r"\\%'), "Unsafe Herdr socket path")
    env_path = directory / "herdr.env"
    env_path.write_text(f'HERDR_ENV=1\nHERDR_SOCKET_PATH="{socket}"\n')
    env_path.chmod(0o600)
    command = [
        shutil.which("uv") or "/usr/bin/uv",
        "--directory",
        str(checkout),
        "run",
        "--offline",
        "--no-sync",
        "python",
        "-m",
        "project_tracker.data_ready_watch",
        "--project",
        str(project),
        "tick",
        "--deliver",
    ]
    service = (
        f"[Unit]\nDescription=One local Starwatch readiness notification\n[Service]\nType=oneshot\n"
        f"WorkingDirectory={checkout}\nEnvironmentFile={env_path}\nTimeoutStartSec=120\n"
        f"ExecStart={shlex.join(command)}\n"
    )
    timer = (
        f"[Unit]\nDescription=Check Starwatch data every two minutes\n[Timer]\nOnActiveSec=5s\n"
        f"OnUnitActiveSec=2min\nAccuracySec=1s\nUnit={UNIT}.service\n"
    )
    (directory / f"{UNIT}.service").write_text(service)
    (directory / f"{UNIT}.timer").write_text(timer)
    activation = [
        "systemd-run",
        "--user",
        f"--unit={UNIT}",
        "--service-type=oneshot",
        "--on-active=5s",
        "--on-unit-active=2m",
        "--timer-property=AccuracySec=1s",
        "--property=TimeoutStartSec=120",
        f"--property=EnvironmentFile={env_path}",
        f"--working-directory={checkout}",
        "--",
        *command,
    ]
    path = directory / "activate.sh"
    path.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n# Root review required before executing.\nexec "
        + shlex.join(activation)
        + "\n"
    )
    path.chmod(0o700)
    return {"status": "prepared-not-active", "activation": str(path), "unit_directory": str(directory)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PROJECT)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("tick", help="Dry run by default; --deliver is reserved for root activation")
    run.add_argument("--deliver", action="store_true")
    commands.add_parser("prepare", help="Prepare unit files and activation command without activating")
    commands.add_parser("status")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.project)
    elif args.command == "status":
        result = load_json(args.project / "tmp/production/data-ready-watch/status.json")
    else:
        result = tick(args.project, deliver=args.deliver)
    print(json.dumps({k: v for k, v in result.items() if k not in {"prompt", "receipt"}}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
