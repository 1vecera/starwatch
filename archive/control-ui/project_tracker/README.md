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
