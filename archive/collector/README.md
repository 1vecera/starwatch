> **Archived.** This is the first Starwatch engine, written in the opening hours of the Agents 0.0.7 hackathon (8–9 October 2026). It researched one politician at a time and streamed the run to a single screen. The public product moved to the ten-city evidence pipeline in [`../../pipeline`](../../pipeline) and the static app in [`../../app`](../../app). The stage table below shows the original scaffold; identity resolution, the collectors, transcription, claim extraction, writing and rendering were implemented afterwards and are covered by `tests/`. Kept for reference; not maintained.

# Starwatch

Starwatch researches a public politician's public social media live. You give it a person, one identifying anchor (official website, party, city or IČO) and a goal; it collects their posts and videos through Apify Actors, transcribes the videos with ElevenLabs Scribe, and writes a goal-specific brief in which every fact links to its source.

## Run it

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv run starwatch
```

Open <http://127.0.0.1:8000>. Enter a subject, an anchor and a goal, then press Run; S1 streams the run's steps as they happen.

The app starts without credentials and says which are missing; steps that need a missing credential report themselves as `skipped`. Set them in the environment, or copy `.env.example` to `.env` and fill it in (`.env` is never committed):

| Variable | Used by |
| --- | --- |
| `APIFY_TOKEN` | collectors (Apify Actors) |
| `ELEVENLABS_API_KEY` | transcription (Scribe v2) |
| `ANTHROPIC_API_KEY` | claim extraction and brief writing |

Other settings: `STARWATCH_PORT` (default 8000), `STARWATCH_HOST`, `STARWATCH_DATA_DIR` (default `data/`), `STARWATCH_RELOAD=1` for auto-reload while editing Python, and `STARWATCH_STEP_PAUSE_S` to slow every step down for UI work, which S1 labels on screen.

Tests: `uv run pytest`.

## How a run works

`POST /api/runs` creates a run and starts the pipeline in the background. The pipeline (`starwatch/pipeline.py`) runs stages in order; the steps within a stage run at the same time:

| Stage | Step module | Status |
| --- | --- | --- |
| Resolve identity | `steps/identity.py` | not implemented |
| Collect: website, Facebook, Instagram, TikTok, YouTube, X | `collectors/<platform>.py` | not implemented |
| Transcribe | `steps/transcribe.py` | not implemented |
| Extract claims | `steps/extract.py` | not implemented |
| Plan and write | `steps/write.py` | not implemented |
| Render | `steps/render.py` | not implemented |

A step that raises `NotImplementedError` is reported as `not_implemented`, never as done. A missing credential makes it `skipped`; any other exception makes it `failed` with the message, and the run continues. Every collector outcome becomes a coverage row (`collected`, `unavailable`, `not_found`, `skipped`), so an empty platform is never a silent zero.

### Progress events

`GET /api/runs/<run_id>/events` is a server-sent event stream. Every connection replays the run from its first event, so a screen opened mid-run or after the run builds the same state; `Last-Event-ID` or `?after=<seq>` resumes. Event types, all JSON with `seq`, `ts`, `type` and `run_id`:

- `run.started`: subject, anchor, goal and how it was chosen, mode, credential presence, and the `plan` (every step with its group, Actor ID and item cap).
- `step.status`: `step`, `status` (`queued`, `running`, `done`, `failed`, `skipped`, `not_implemented`), optional `count` and `note`.
- `step.item`: one collected item reaching its lane: `item.id`, `platform`, `kind`, `url`, `published_at`, `thumb` (a local `/runs/...` URL), `media_kind`, `width`, `height`, `text`.
- `step.data`: structured step output, such as identity's `accounts` and `rejected`, or a `summary` line for a downstream step.
- `run.finished`: final `status`, `coverage` and `costs`.

### Storage

Run data stays out of Git, under `data/`:

```text
data/starwatch.sqlite3        index of runs
data/runs/<run_id>/
  manifest.json               input, goal, mode (live or cached), status, steps, coverage, costs
  events.jsonl                the event stream, replayable
  items.json                  collected items after allowlist projection
  media/                      images, covers and thumbnails downloaded at collection time
```

`transcripts.json` and `brief.json` are written by their steps. The brief's JSON schema is typed in `starwatch/models.py` (`Brief`); a fact without evidence or an inference without fact IDs cannot be constructed.

## Building on it

- **Collectors.** Implement `run()` in `starwatch/collectors/<platform>.py`. Take the account from `ctx.accounts_for(platform)`, call `run_actor(self.spec, {...}, token=ctx.credential("APIFY_TOKEN"), on_items=...)`, project each raw item into a `CollectedItem`, save its image with `ctx.download_media(...)` and send it with `ctx.item_arrived(self.id, item)`. `run_actor` (`collectors/apify.py`) polls the Actor's dataset while it runs, so items reach S1 as they arrive, and passes the caps in `collectors/actors.py` to Apify as `maxItems` and `maxTotalChargeUsd`. Add the run's `usage_usd` to `ctx.costs.apify_usd`. Comments and follower lists stay off.
- **Steps.** Implement `run()` in `starwatch/steps/<step>.py`; read and write the shared `RunContext` (`steps/base.py`).
- **Screens.** Static files in `starwatch/web/`, served at `/static/`. `run-stream.js` starts and follows runs for any screen. `tokens.css` is one `:root` block of `--sw-` custom properties and screen CSS uses only those tokens; replace that block with the Claude Design hand-off.

Each builder owns separate files, so collectors, steps and screens can be built in parallel without touching each other.

## Rules the code keeps

Public sources only. No comments or commenter data, no follower lists, no inferred sensitive traits and no score of any person; confidence describes claims. Collected text is untrusted model input and is rendered as text, never as HTML. Every screen labels whether it shows a live or cached run.
