# Starwatch pipeline (`czlake`)

The evidence side of [Starwatch](../README.md). It turns the official 2026 candidate registry and public social accounts into an immutable DuckDB evidence graph that the app's exporter reads. It collects bounded public evidence with Apify Actors, keeps uncertain account ownership explicit, and serves each checkpoint read-only through a local API. Source data, credentials, authorization receipts, worker outputs and retained media stay outside Git.

| Stage | Main modules |
| --- | --- |
| Official data: municipalities, 2026 candidacies, 2022 results (ČSÚ volby.cz open data) | `build/universe.py`, `build/fetch_volby.py`, `build/stage_volby.py`, `build/ballot2026.py`, `production_elections.py` |
| Account discovery and ownership review | `production_social_discovery.py`, `production_identity.py`, `production_facebook_binding.py`, `production_new_platforms.py` |
| Capped Apify collection with a spending ledger | `production_budget.py`, `production_collect.py`, `apify_run.py` |
| Media, portraits, logos and web text with source bindings | `production_media.py`, `production_images.py`, `production_portraits.py`, `production_logos.py`, `production_web.py` |
| Topic labels with independent review | `production_labels.py`, `production_topic_graph.py` |
| Checkpoint export and read API | `production_graph.py`, `production_api.py` |

The app's exporter (`../app/tools/export_real.py`) reads a checkpoint and writes the snapshot the static screens load. The Apify Actors, inputs and costs are documented in [the Apify recipes](../docs/apify-recipes.md).

## Local use

Use Python 3.12 or newer and the locked environment with `uv sync`. Point commands at the project home containing the existing official registry, relevance selection and source lake. Run these commands from this directory.

```bash
export CZLAKE_PROJECT=/absolute/path/to/project
uv run python -m czlake.production_collect --root "$CZLAKE_PROJECT/data/production" status
uv run python -m czlake.production_collect --root "$CZLAKE_PROJECT/data/production" reconcile
```

Collection requires an initialized, hash-pinned authorization and complete night accounting snapshot. Every paid manifest pins its exact input, current actor pricing, item limit, timeout, memory and provider spending cap. `run --manifest PATH` reserves before making a request. One coordinator owns paid starts, accounting imports and shared checkpoint writes; delegated preparation writes to isolated directories.

An uncertain start retains its full exposure. Recovery requires the exact run ID from the durable response receipt; a similar later run is insufficient. Bills retain their cap until fresh terminal count evidence, complete prices and the settlement buffer agree. Historical unresolved provisions remain reserved. Managed `APIFY_TOKEN` is read from the environment and is never stored in receipts.

Generate a new checkpoint with original reviewed identity files, frozen classification packets and optional retained-media and web supplements:

```bash
uv run python -m czlake.production_graph \
  --source-root "$CZLAKE_PROJECT" \
  --production-root "$CZLAKE_PROJECT/data/production" \
  --identity "$CZLAKE_PROJECT/data/production/identity-review-001.json" \
  --output "$CZLAKE_PROJECT/tmp/production/read" \
  --checkpoint-id unique-checkpoint-name

uv run python -m czlake.production_api \
  --root "$CZLAKE_PROJECT/tmp/production/read" --port 8123
```

Additional graph options are `--identity-reviews`, `--label-bundle`, `--media-index`, `--image-index`, `--web-supplement`, `--logo-supplement` and `--election-supplement`. The exporter verifies source hashes and integrity gates before atomically replacing `current.json`; immutable checkpoint directories remain available to readers. A failed export leaves the old pointer intact.

## Read contract

The server binds to `127.0.0.1` by default. It has no write, arbitrary SQL, arbitrary file download or permissive CORS route, and rejects unexpected Host/Origin headers. Each request pins one checkpoint, verifies its manifest, and opens DuckDB read-only.

- `/api/checkpoint`, `/api/health`, `/api/coverage`
- `/api/cities`, `/api/entities`, `/api/entities/{id}`
- `/api/accounts`, `/api/assets`, `/api/assets/{id}`
- `/api/claims`, `/api/topics`, `/api/metrics`
- `/api/web-assets`, `/api/web-assets/{id}`, `/api/publishers`
- `/api/photos`, `/api/photos/{id}`, `/api/photos/{id}/blob`, `/api/photo-coverage`
- `/api/media`, `/api/media/{id}`, `/api/media/{id}/blob`
- `/api/topics/{id}` and its assets, entities, claims, related, web-sources and metrics collections
- `/api/election-lists`, `/api/election-candidates`, `/api/election-links`

Collections use bounded `limit`/`offset` pagination. Pass the returned `checkpoint_id` on later requests to prevent mixing versions; a changed pointer returns 409. Social account/asset routes expose admitted ownership. Web routes expose separately retained source text and explicitly unknown associations. Internal filesystem paths are omitted.

Account ownership, public visibility, publication ownership, subject, depicted person and quoted speaker are separate facts. Public ownership anchors do not prove profile visibility. Claims are reviewed source statements, not verified truth; unknown speakers remain null. Exact caption offsets use Unicode code points. JavaScript consumers should slice `Array.from(context_text)` for these offsets.

Metrics retain grain, source, observation time and null reasons. Snapshot mode deduplicates identical same-time observations and preserves conflicting values as unknown. Recent-N samples and deeper bounded histories do not prove complete date-window coverage. Discovered URLs, provider rows, distinct parent assets, verified assets and downloaded media are separate counts.

## Retention and provenance

`production_identity` supports bounded public HTTP retrieval, cached/offline operation, immutable result versions and cumulative request ledgers. `production_social_discovery` binds retained search results to exact candidate queries and preserves original versus derived URLs. Their account links are proposals until reviewed. `production_labels` validates original classifier/reviewer paths, distinct registered identities, exact packets and hashes; correction packets require the exact predecessor label hash.

`production_media` validates allowed public CDN sources and exact source pointers before downloading. It supports multiple plans, content reuse, cumulative byte reservations, bounded concurrency, restart uncertainty, stream-size/deadline checks and local hashes. Its index records failed or unavailable media explicitly. The local read API serves admitted original media after checking source bindings, hashes, lengths and MIME; MP4 downloads support a single bounded HTTP byte range.

Source photos have separate per-person coverage and source-image records. A named official profile photo and an owned account avatar are different kinds of evidence; neither uses facial recognition or establishes a depicted person's identity. Generic logos, signatures, group pictures and article-author thumbnails require explicit exclusion or an unknown outcome. The photo blob route serves only admitted original raster bytes from approved local roots after verifying the pinned source pointer, URL, content hash, length and image type. It cannot fetch an arbitrary URL or read an arbitrary file.

Official logos are exported in `list-logos.json` and `list-logo-coverage.json`, retaining exact website image evidence and official registry membership. A member party's logo is labelled separately from a coalition brand. SVGs must contain only passive local content.

Historical election exports preserve every 2022 source row, list votes, raw vote share, official adjusted percentage and seats. Candidate totals include whole-list vote allocation and are not a separately measured preference-only count. Matches to current candidacies retain exact registry evidence and explicit uncertainty; list-code/composition matches provide historical context rather than established coalition continuity.

Topic navigation uses accepted, current classification records, exact evidence spans and independently registered reviewers. Related topics describe co-occurrence, not causation. Public YouTube, X and TikTok observations retain the same owner/source separation as Instagram and Facebook; platform visibility and exact returned author identity are required before admission.

## Programmes and articles

`czlake.campaign` adds two optional launch files to an exported snapshot: each list's own 2026 programme with promises whose Czech quotes are verified verbatim against the fetched text (`programs.js`), and Czech news articles that name a list or a leading candidate together with its city (`articles.js`). It caches every response, enforces cumulative spend caps for Exa, Bedrock and Apify, and rebuilds identical files with `--offline`.

```bash
uv run python -m czlake.campaign --snapshot ../app/web/data/real.js --cache ../tmp/campaign \
  programs --lists relevant --out ../app/web/data/programs.js
uv run python -m czlake.campaign --snapshot ../app/web/data/real.js --cache ../tmp/campaign \
  articles --lists all --programs ../app/web/data/programs.js --out ../app/web/data/articles.js
uv run pytest tests/test_campaign_*.py
```

The recipe, costs and failure modes are in [docs/collection/programs-and-articles.md](../docs/collection/programs-and-articles.md).

## Validation

```bash
uv sync
uv run --with pytest pytest
```

The suite also runs under the standard library runner (`uv run python -m unittest discover -s tests`). Test scratch stays in ignored `tmp/` directories; set `IDENTITY_TEST_SCRATCH` to move the identity fixtures elsewhere.

Tests exercise spending and crash recovery, source/privacy filtering, independent provenance, historical contradictions, exact claim spans, atomic publication, media limits and local API boundaries. They use local fixtures only and never call Apify or another paid service. Real-source checks and collection coverage are recorded in the project's ignored production reports and versioned manifests, not in this repository.
