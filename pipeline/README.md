# Starwatch evidence backend

The Python backend collects bounded public evidence, keeps uncertain account ownership explicit, and exposes immutable DuckDB checkpoints through a local read API. Source data, credentials, authorization receipts, worker outputs and retained media stay outside Git.

## Local use

Use Python 3.12 or newer and the locked environment with `uv sync`. Point commands at the project home containing the existing official registry, relevance selection and source lake. Run these commands from this worktree.

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

## Validation

```bash
mkdir -p tmp/tests
TMPDIR="$PWD/tmp/tests" IDENTITY_TEST_SCRATCH="$PWD/tmp/tests/identity" \
  uv run --offline python -m unittest discover -s tests
```

Tests exercise spending and crash recovery, source/privacy filtering, independent provenance, historical contradictions, exact claim spans, atomic publication, media limits and local API boundaries. Real-source checks and current collection coverage are retained in the project home's ignored production report and versioned manifests.
