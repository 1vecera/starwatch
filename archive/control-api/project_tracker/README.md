# Local project desk

Run from this checkout with `uv run python -m project_tracker --root /path/to/project --port 8110`, then open `http://127.0.0.1:8110/`. Python 3.13+ is the only runtime dependency. The root must contain `TODO.md`; keep this private coordination tool separate from the hackathon app's public repository.

The browser polls every five seconds. Worker lanes come only from validated `hos-*` names in TODO's current `In flight` section; each uses its corresponding `docs/reports/<name>.md`. Adding or removing an entry takes effect on the next refresh without restarting the server. Historical reports remain evidence and never create worker lanes. Existing friendly titles are fallback labels, and a recorded branch overrides the fallback branch.

The server reads the existing TODO checkboxes, Markdown worker reports and learnings, read-only `herdr agent list`, and Git worktree state. A live idle worker takes precedence over an old report saying it is working. Herdr `done` and `completed` mean a finished turn, not a completed backlog task or an exited process. The HTTP state separately records the raw agent status and whether the session was listed; process liveness is not independently verified. Missing Herdr state remains unknown; stale progress does not imply a stopped worker. Report freshness comes from file modification time and suspicious future headings are flagged. Checkbox completion is reported evidence, not independent functional verification. Checked decision questions are excluded from pending decisions.

Budget observations use the existing root `data/ledger.csv`, `data/ledger_state.json` and collector report. Repeated ledger run IDs use their latest amount. Settlement holds remain conservatively reserved, even when a terminal run is also present. Collector headroom and consolidated account totals remain unknown without current records. No paid API is called.

The Europe/Prague deadline is fixed at 9 October 2026 07:14; after it passes the UI shows “Freeze passed.” Readiness counts summarize TODO checkpoints, not a product completion percentage. Local demo URLs are taken from the preserved handoff ports and their availability is explicitly unverified. Screenshots are restricted to top-level PNGs in the five known preview directories; raw scraped data is never served.

Notes append inert text to root `tmp/project-tracker/inbox.jsonl` with restrictive permissions. Every note remains pending acknowledgement. This tool never prompts workers, executes a note, changes TODO or sends messages. The coordinator can read that inbox separately.

The server binds only to `127.0.0.1`. Host and Origin validation reject foreign access and DNS rebinding; notes require a same-origin JSON request. Evidence IDs select from fixed source and screenshot allowlists, with traversal and symlinks rejected. Source text is escaped by DOM text rendering and sensitive values, external links and absolute paths are stripped from previews. There is no general file-serving or command endpoint. No publication, upload or deployment is performed.

Run focused checks with `uv run python -m unittest -v tests.test_tracker`, `uv run --with playwright python -m tests.browser_smoke`, and `uv run --with ruff ruff check project_tracker tests`. Browser verification uses an isolated headless context and disposable fixture files under ignored `tmp/`.

To keep the server alive independently of a terminal, launch the run command with a detached process session and redirect logs. For this handoff the root scratch directory holds `server.pid` (the detached uv launcher/process-group ID), `server.log`, desktop and narrow captures. Stop only that recorded process group after checking its identity. No automatic restart is configured.

The actionable control room uses `GET/POST /api/control` and `GET /api/events`; the read-side routes and legacy notes remain available. Tasks and their stable metadata live in TODO, with decisions, diagrams, activity and the durable chief outbox in `tmp/control-room/records.json`. Every writer takes `tmp/control-room/records.lock`, checks the freshest revision, and commits atomic files through a recoverable journal. The first migration backs up TODO, learnings, records and the legacy inbox.

Run the server only after checking the selected root and port:

```bash
uv run python -m project_tracker --root /path/to/project --port 8111
uv run python -m project_tracker.cli --root /path/to/project state
uv run python -m project_tracker.cli --root /path/to/project tasks
uv run python -m project_tracker.cli --root /path/to/project mutate --json '{"op":"task.create","title":"Review the final subject","owner":"Daniel","priority":"high"}'
uv run python -m project_tracker.cli --root /path/to/project mutate --json '{"op":"task.move","id":"task-ID","status":"review"}'
uv run python -m project_tracker.cli --root /path/to/project mutate --json '{"op":"progress.record","text":"Validated cached evidence","task_id":"task-ID","evidence":["report:hos-brief"]}'
uv run python -m project_tracker.cli --root /path/to/project mutate --json '{"op":"architecture.feedback","id":"atlas","text":"Refine the brief and goal switch"}'
uv run python -m project_tracker.cli --root /path/to/project tail --follow
```

`mutate` also accepts JSON stdin. Supply `base_revision` for explicit optimistic concurrency; HTTP requires it, while CLI can select the freshest revision under the lock. Task update uses `id` and `patch`; decision create/update/choose/comment, architecture update/layout/edge/feedback, message send/retry/ack, progress record and worker register/update all share this validation. HTTP conflicts return 409 with current state; CLI conflicts exit 2. Archive cards through `task.update` with `{"archived":true}`.

```bash
uv run python -m project_tracker.cli --root /path/to/project mutate --json '{"op":"decision.choose","id":"decision-subject","custom_choice":"Subject and anchor","rationale":"Reviewed ballot and source evidence"}'
uv run python -m project_tracker.cli --root /path/to/project mutate --json '{"op":"message.send","text":"Please review the recorded choice"}'
uv run python -m project_tracker.cli --root /path/to/project mutate --json '{"op":"message.ack","id":"message-ID","reply":"Reviewed; explicit reply"}'
```

Messages are stored queued before delivery to the fixed chief w6:p24/session 01a11d9e-1dad-7221-8c92-ea48d4094a3b/root cwd. Each delivery rechecks identity and blocks on unknown/blocked/replaced sessions. Herdr runs with structured argv; no terminal snapshots or arbitrary target/command route exists. Submission is distinct from acknowledgement. A process interrupted during submission records an uncertain failure on restart and requires explicit retry after inspecting the chief. Decisions append dated actor/source/history to learnings and queue a planning notification; saving a choice never runs its plan. Reports and lifecycle observations stream as bounded safe activity.
