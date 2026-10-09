"""CLI over the same canonical store and validation as the local dashboard."""

import argparse
import json
import sys
import time
from pathlib import Path

from project_tracker.records import ConflictError, ControlStore, ValidationError


def main():
    parser = argparse.ArgumentParser(description="Starwatch local control room")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--actor", default="Daniel")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="Back up and add stable metadata to existing TODO cards")
    for command in ("state", "tasks", "decisions", "architecture", "messages"):
        commands.add_parser(command)
    mutation = commands.add_parser("mutate", help="JSON mutation from stdin or --json")
    mutation.add_argument("--json")
    mutation.add_argument(
        "--no-dispatch", action="store_true", help="Save a message/choice queued for the running server"
    )
    tail = commands.add_parser("tail", help="Stream safe report, lifecycle and saved action events as JSONL")
    tail.add_argument("--follow", action="store_true")
    tail.add_argument("--limit", type=int, default=20)
    commands.add_parser("dispatch", help="Submit queued chief messages; never retries failed/uncertain messages")
    args = parser.parse_args()
    store = ControlStore(args.root)
    try:
        if not (args.root / "TODO.md").is_file():
            raise ValidationError("--root must contain TODO.md")
        if args.command == "migrate":
            result = store.migrate()
        elif args.command == "mutate":
            raw = args.json if args.json is not None else sys.stdin.read(64_001)
            if len(raw.encode()) > 64_000:
                raise ValidationError("Mutation exceeds 64000 bytes")
            envelope = json.loads(raw)
            if isinstance(envelope, dict):
                envelope.setdefault("actor", args.actor)
            result = store.mutate(envelope)
            if not args.no_dispatch and envelope.get("op") in {"message.send", "message.retry", "decision.choose"}:
                store.dispatch_pending()
                result["state"] = store.snapshot()
                if envelope["op"].startswith("message."):
                    result["result"] = next(
                        item for item in result["state"]["messages"] if item["id"] == result["result"]["id"]
                    )
        elif args.command == "dispatch":
            result = {"processed": store.dispatch_pending(), "state": store.snapshot()}
        elif args.command == "tail":
            if not 1 <= args.limit <= 200:
                raise ValidationError("tail --limit must be 1–200")
            seen = set()
            while True:
                rows = list(reversed(store.snapshot(include_project=False)["activity"][: args.limit]))
                for row in rows:
                    if row["id"] not in seen:
                        print(json.dumps(row, ensure_ascii=False), flush=True)
                        seen.add(row["id"])
                if not args.follow:
                    return
                time.sleep(2)
        else:
            state = store.snapshot()
            result = state if args.command == "state" else state[args.command]
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except ConflictError as error:
        print(json.dumps({"error": str(error), "code": error.code, "state": store.snapshot()}))
        raise SystemExit(2) from None
    except (ValidationError, ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error), "code": getattr(error, "code", "validation")}))
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
