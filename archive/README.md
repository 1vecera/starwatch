# Archive

Earlier code from the Agents 0.0.7 hackathon night (8–9 October 2026), kept so the history of the entry stays readable. Nothing here is needed to run Starwatch. The current product is the static app in [`../app`](../app) and the evidence pipeline in [`../pipeline`](../pipeline); the [root README](../README.md) describes current behaviour and limitations.

| Directory | What it was | Superseded by |
| --- | --- | --- |
| [collector](collector/) | The first Starwatch engine: FastAPI, SQLite and server-sent events. One politician, one identifying anchor and one research goal in; Apify collection, ElevenLabs Scribe transcription and a goal-specific brief with every fact linked to its source out. | `pipeline/` (collection and evidence graph) and `app/` (screens) |
| [skeleton](skeleton/), [vis-atlas](vis-atlas/), [vis-press](vis-press/) | Snapshots of the collector engine: its initial scaffold and two visual directions for its run screen. | `collector/`, then `app/` |
| [explore](explore/), [prioritize](prioritize/) | Snapshots of the `czlake` pipeline while it explored the official candidate registry and ranked which candidates and lists to collect first. | `pipeline/` |
| [workspace](workspace/) | The hackathon's local project-control room: a dashboard over the project's task list with a Kanban board, decisions, an architecture graph (React and XYFlow) and worker activity. A coordination tool, not part of the product. | Not continued |
| [project-tracker](project-tracker/), [control-api](control-api/), [control-ui](control-ui/) | Earlier versions of the same control room. | `workspace/` |

## Status

- `collector/` and `workspace/` still pass their own tests (`uv sync && uv run pytest` in `collector/`, `uv sync && uv run --with pytest pytest` in `workspace/`). The other snapshots are not maintained and may not run.
- Historical READMEs describe their own checkpoint and may mention local paths, ports or setup steps that no longer apply.
- Collected research data, fixtures and media were never committed. Credentials are read from the environment; `.env.example` files list variable names only.
