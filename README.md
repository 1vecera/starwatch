# Starwatch

**Find the issue. Follow the evidence.**

Starwatch is a visual workspace for exploring public political activity across ten Czech cities. Start on a map, find a person or party/list, inspect posts and videos, follow quoted statements to their sources, and compare observed activity with its dates and coverage gaps.

Built by Daniel Večeřa, team DANDAPANDA, for the Agents 0.0.7 hackathon in Prague on 8–9 October 2026, Social Media Deep Research track.

## Run the interface

Install Python 3.12+ and [uv](https://docs.astral.sh/uv/), then run:

```sh
./run.sh
```

Open **http://127.0.0.1:5173/**. The public checkout starts with the explicitly labelled simulated universe. It requires no API credentials and launches no paid collection. The optional online map uses OpenFreeMap; a local geographic fallback is included.

The hackathon's collected research database, source media, recordings, credentials and private project notes are not distributed in this repository. The recorded demonstration uses the separately retained local evidence snapshot. To connect your own authorized checkpoint, see [the export contract](app/tools/RAW_FORMAT.md) and [pipeline setup](pipeline/README.md); `app/tools/export_real.py --project /path/to/project` accepts an explicit project root.

## Screens

| Screen | Purpose |
| --- | --- |
| Star Atlas | Explore Czechia, a city, parties/lists, people and their source assets. |
| Spotlight | Inspect one entity, its posts, quoted statements, observed metrics and source links. |
| Pulse | Compare entities with separate measures and visible observation windows. |
| Radar | Inspect a watchlist and observed baseline/replay activity. |
| Studio | Organize cited evidence, edit a local draft and preview it; nothing is published. |
| By the numbers | Inspect available coverage by platform, city and list. |

## Repository map

| Directory | Contents |
| --- | --- |
| [app](app/) | Current static HTML/CSS/JavaScript app, MapLibre/ECharts, branded assets, checkpoint exporter and local video-range server. |
| [pipeline](pipeline/) | Python/DuckDB evidence graph, public-source ingestion, account-ownership checks, deterministic research selection, bounded collection accounting, classification validation and read API. |
| [collector](collector/) | Earlier FastAPI/SQLite research engine, SSE progress, Apify adapters, transcription and evidence-linked research steps. |
| [workspace](workspace/) | Local project workspace with Markdown overview, Kanban, decisions, architecture feedback, activity and agent CLI. |
| [archive](archive/) | Earlier source snapshots and visual prototypes, retained for completeness. They are historical, not the current entry point. |

Each Python component has its own `pyproject.toml` and lockfile. The workspace's React/XYFlow frontend includes source and its compiled local bundle. The archive excludes retained research fixtures; those prototypes may require local inputs.

## Evidence and limitations

The local demo snapshot checked on 9 October contained 10,697 attributed public posts from 88 independently anchored accounts, alongside the 5,405 valid registered candidacies and 127 lists in the ten-city universe. These are different populations: registry inclusion does not mean an account or post was found. Instagram and Facebook have observed posts; other platforms and historical coverage remain incomplete.

Metrics are dated observations, not measurements of electoral support. A source statement is not independently verified truth. Account ownership, asset authorship, mention, depicted person and quoted speaker remain separate evidence questions. Unknown values and missing coverage are retained. Municipal candidate vote totals may include whole-list allocation and must not be read as preference-only votes.

Collection happened during the hackathon, but the app consumes exported snapshots. Scheduled continuous monitoring, complete histories and a full live goal-dependent research flow are not demonstrated by the current app. Studio uses local templates, and its drafts are never sent. The sign-in screen is a prototype, not production authentication. The local servers bind to loopback and are not a hardened public deployment.

## Validation

```sh
cd app
uv run --with pytest pytest tools/test_serve.py

cd ../pipeline
uv sync
uv run --with pytest pytest

cd ../collector
uv sync
uv run pytest

cd ../workspace
uv sync
uv run --with pytest pytest
```

The app's `tools/walkthrough.mjs` and `tools/check-atlas-c.mjs` are browser checks for the locally collected demonstration and need its data plus Playwright. They are not prerequisites for starting the public simulated interface.

## Tools

Apify Actors collect public sources; Python, DuckDB and PyIceberg organize evidence; ElevenLabs Scribe supports retained transcription in the research engine. The video soundtrack was generated with ElevenLabs Music. The app uses static JavaScript, MapLibre and ECharts; the separate workspace uses React and XYFlow. Credentials are supplied locally through environment variables, never through committed files.

Third-party components retain their own notices and licenses. No additional license grant for the project source is declared in this submission.
