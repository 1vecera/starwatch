# Local Starwatch control room

From the control-room checkout, run `uv run python -m project_tracker --root /path/to/project --port 8110`, then open http://127.0.0.1:8110/. Python 3.13+ is the only server dependency. React and actual `@xyflow/react` are bundled locally; rebuild with `npm ci --prefix project_tracker/frontend && npm run build --prefix project_tracker/frontend`. Keep this private project tool out of a public Starwatch submission.

The opening workspace is the editable product one-pager beside a clear Kanban. On narrow layouts they stack. `docs/product-state.md` is the single maintained product/spec explanation; the root README and build notes link to it. Decisions, technical evidence, architecture/feedback and activity/direct messages are collapsed supporting sections on the same page. The board opens with active work first, concise titles, status and owner. Completed and archived cards are hidden until selected; archive is reversible. Open a card for its description, evidence, comments, original prose and history. Creation, editing, drag/drop and status-menu moves remain real TODO writes.

TODO.md remains the only progress record: stable IDs, fields and edit history live in adjacent metadata while original prose and sections remain. Incoming state preserves an open task draft; revision conflicts require an explicit reapply, and only edited fields are reapplied. Reloads retain saved records, and the chief composer retains unsent text locally.

## Product Markdown editing

Choose Edit Markdown, edit with an inert preview, and Save product page. Saves update only the exact root `docs/product-state.md`, bounded to 48,000 UTF-8 bytes. CommonMark headings, lists, emphasis, code and source links render without raw HTML, active content or external image loading. Relative links resolve only to approved project sources; external HTTP(S) links are deliberate navigation. Draft text and its original document version stay in browser storage across reloads when available; storage failures keep the tab draft and show a warning. Close keeps a draft, while discarding requires confirmation.

Agent file changes appear through the existing state stream/poll. A changed file disables saving until Daniel reviews its latest Markdown and chooses to retain/merge his draft or use the latest text. A save-time race returns HTTP409 with the current file while preserving the draft. Product saves compare the document's SHA-256 version independently of unrelated task progress. Agents must use the same locked, version-checked `product.save` operation, with their actual actor, for writes; do not overwrite the file with a stale direct copy.

The shared CLI mutation shape is `{"op":"product.save","base_version":"VERSION_FROM_STATE_PRODUCT","markdown":"# Updated product\n"}`. Read `state.product.version` and `state.product.markdown`, prepare a draft under this checkout's `tmp/`, then submit through `./scripts/control-room --actor hos-control mutate --no-dispatch`. Path fields and other-file editing are rejected. Every saved previous version is retained verbatim at `tmp/control-room/product-history/<sha256>.md`; the mutation result and audit record name it. To recover, read that file and submit it as a new version-checked save. The journal commits the document, previous version and audit together; interrupted saves recover under the existing record lock. Local source and navigation recovery copies from this simplification remain under root `tmp/control-room/backups/*-one-page/`.

Decisions save listed or custom choices, rationale, comments and auditable revisions. Choices append dated actor/source records to learnings; automatic notifications remain held while quiet. Saving a planning choice does not execute it. Canonical task/decision ownership follows the current task brief; the simplification handoff authorizes bounded reconciliation while root waits. Evidence links source authority, current audits, reported artifacts and dated observations; reports are inspectable evidence, not readiness claims. Next.js/DuckDB target choices do not imply completed migration. Atlas art work and this internal workspace are separate scopes.

Expand Architecture and feedback for the readable product flow. Choose all groups, research or orchestration for other levels. The real XYFlow canvas supports pan, zoom, fit, node movement and connections. Select a block for details, approved evidence previews, related work and feedback; edits and layout persist. Statuses distinguish implemented, cached-only, held, planned and missing work.

Activity streams report changes and registered Herdr lifecycle observations with observed time and a five-second polling fallback. A finished or idle turn never means a backlog task is finished. The fixed chief is w6:p24/session `01a11d9e-1dad-7221-8c92-ea48d4094a3b` in the project root; each delivery rechecks its identity and rejects unknown, blocked or replaced sessions. Messages persist held or queued before any structured-argv Herdr submission. Submitted means delivery accepted, and acknowledged requires the explicit CLI reply. A delivery interrupted before confirmation is an uncertain failure requiring inspection and explicit retry; it is never automatically resent. The UI has no arbitrary agent target or shell command endpoint.

The root must contain TODO.md. The first migration backs up TODO, learnings, auxiliary records and the legacy inbox under `tmp/control-room/backups/`. All writers use `tmp/control-room/records.lock`, read the freshest revision and commit atomic files through a recoverable journal. Decisions, graph, activity and outbox live in `tmp/control-room/records.json`; they are not a second task database. Existing inert notes in `tmp/project-tracker/inbox.jsonl` remain preserved and available through the legacy read state; they are not silently sent.

The server binds only to 127.0.0.1. Local Host/Origin checks protect reads and writes; HTTP mutations require JSON and a project revision, or the exact document version for product.save. Payloads and files are bounded. Evidence uses approved IDs with symlink/traversal checks; previews redact credentials and unrelated paths. React renders user text inertly. The service never collects, spends, publishes or changes outside systems. The internal workspace does not invent countdowns, deadline-based milestones or readiness scores. Independent event facts remain available through the event source. Current budget authority comes from the rescope source; observed service spend and unknown consolidated totals stay separate.

## Quiet policy

Daniel has paused unsolicited worker pings. The durable policy is in the shared records; absent/unknown policy defaults to quiet. CLI messages, automatic choice notifications (including choices recorded as Daniel), legacy queued messages and background/manual dispatch all use the worker gate. Claimed actor text cannot select the direct route or reopen policy. Held messages keep history and never count as delivered; no time or restart automatically releases them.

Daniel's deliberate Send, retry and policy controls use `/api/browser-control`, a separate route requiring a same-origin browser fetch context and an ephemeral intent token from `/api/browser-intent`. The token is excluded from control snapshots, SSE and the CLI; JSON cannot supply the trusted delivery class. Direct messages record Daniel. Existing local Host/Origin checks still apply. Worker `message.send` compatibility retains a held message while quiet, but workers should write progress and reports instead.

Reopen worker delivery only with the explicit dashboard control and confirmation. It permits new notifications; older held messages stay held until Daniel releases each one with a separate confirmed action. Closing quiet mode holds pending worker messages under the same record lock used through each bounded delivery, so activation cannot race a new prompt. Previously submitted or acknowledged messages retain their truthful status. There is no automatic future release.

## CLI

The single entry point is `./scripts/control-room`; it finds the canonical project root through Git and calls the same store as HTTP. Set `CONTROL_ROOM_ROOT=/path/to/fixture` to use a different project root, or use the explicit module form `uv run python -m project_tracker.cli --root /path/to/project ...`.

CLI mutations default to the neutral author `Agent CLI`. Agents should name their actual worker with `--actor hos-control` before the command; an explicit JSON `actor` takes precedence. Use `--actor Daniel` only when recording his actual instruction or choice. Browser edits continue to record Daniel. The wrapper preserves this default; generated acknowledgements explicitly name hos-chief.

```bash
./scripts/control-room state
./scripts/control-room tasks
./scripts/control-room mutate --json '{"op":"task.create","title":"Review final subject","owner":"Daniel","priority":"high","status":"ready"}'
./scripts/control-room mutate --json '{"op":"task.update","id":"task-ID","patch":{"description":"Checked source evidence","priority":"urgent"}}'
./scripts/control-room mutate --json '{"op":"task.move","id":"task-ID","status":"review"}'
./scripts/control-room --actor hos-control mutate --json '{"op":"progress.record","task_id":"task-ID","text":"Evidence verified","evidence":["report:hos-brief"]}'
./scripts/control-room mutate --json '{"op":"task.comment","id":"task-ID","text":"Review the anchor"}'
./scripts/control-room mutate --json '{"op":"task.update","id":"task-ID","patch":{"archived":true}}'
```

```bash
./scripts/control-room decisions
./scripts/control-room mutate --json '{"op":"decision.create","title":"Choose demo anchor","options":[{"id":"a","label":"Verified website","detail":"Reviewed evidence"},{"id":"b","label":"Official profile","detail":"Review owner"}]}'
./scripts/control-room mutate --json '{"op":"decision.update","id":"decision-ID","patch":{"owner":"Daniel"}}'
./scripts/control-room --actor hos-control mutate --json '{"op":"decision.choose","id":"decision-ID","choice":"a","rationale":"Verified identity"}'
./scripts/control-room --actor hos-control mutate --json '{"op":"decision.choose","id":"decision-ID","custom_choice":"Another reviewed anchor","rationale":"Source check"}'
./scripts/control-room architecture
./scripts/control-room mutate --json '{"op":"architecture.update","id":"atlas","patch":{"data":{"status":"planned","description":"Art handoff under review"}}}'
./scripts/control-room mutate --json '{"op":"architecture.feedback","id":"atlas","text":"Make the goal switch visible"}'
./scripts/control-room mutate --json '{"op":"architecture.layout","positions":[{"id":"atlas","x":700,"y":320}]}'
```

```bash
./scripts/control-room messages
./scripts/control-room --actor hos-chief mutate --json '{"op":"message.ack","id":"message-ID","reply":"Reviewed; explicit reply"}'
./scripts/control-room tail --follow
```

`mutate` accepts JSON stdin when `--json` is omitted. Add `actor` and an explicitly fetched `base_revision` to the envelope for agent edits that must conflict if the project changed; CLI otherwise selects the freshest revision while locked. HTTP conflicts return 409/current state and CLI conflicts exit 2. `--no-dispatch` saves a notification held or queued according to the durable policy. `worker.register`/`worker.update` record bounded project worker identities and TODO rows; they never start agents.

## Run, verification and rollback

```bash
uv sync
uv run python scripts/control-room-service.py start --root /path/to/project --port 8110
uv run python scripts/control-room-service.py status --root /path/to/project --port 8110
uv run python scripts/control-room-service.py stop --root /path/to/project --port 8110
uv run python -m unittest tests.test_tracker tests.test_control_store tests.test_control_integration -q
uv run --with playwright python -m tests.browser_smoke
uv run --with ruff ruff check project_tracker tests scripts
uv run --with pyright pyright project_tracker scripts
```

The detached service survives worker pane closure. Its log and PID/start-time/argv/cwd identity record are under root `tmp/control-room/service-PORT.*`; stop refuses an identity mismatch. There is no automatic system restart. Keep the old project-tracker checkout at 789305a for rollback. Stop only the verified new service, then run the old checkout's command `uv --directory /home/vecera/code/agents007-hackathon/.claude/worktrees/project-tracker run python -m project_tracker --root /home/vecera/code/agents007-hackathon --port 8110`. The old reader tolerates the new adjacent task metadata, so records remain intact. To restore pre-migration data, first preserve current edits and deliberately restore the reviewed backup; do not blindly replace a newer TODO.

Browser verification uses disposable files and an isolated headless context. Its Herdr transport is explicitly faked; records, HTTP, CLI acknowledgement and streaming are real. The earlier designated benign ping and handoff remain in history. Quiet-policy verification uses disposable records and a fake transport; this change sends no real chief ping, completion notification or outside message.
