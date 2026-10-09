#!/usr/bin/env bash
# Starwatch: export the collected snapshot (if the production checkpoint is available), then serve the app.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p web/data
if [ -f tools/export_real.py ] && [ "${SKIP_EXPORT:-0}" != "1" ]; then
  uv run --with duckdb python tools/export_real.py || echo "Real-data export failed; the app falls back to the simulated universe."
fi
# public aggregates for the About page (stdlib only; reads web/data/real.js when present)
python3 tools/export_stats.py >/dev/null 2>&1 || true
[ -f web/data/real.js ] || echo "window.SW_RAW=null;" > web/data/real.js
[ -f web/data/issue-topics.js ] || echo "window.SW_ISSUES=null;" > web/data/issue-topics.js
[ -f web/data/stats.js ] || echo "window.SW_STATS=null;" > web/data/stats.js
# optional enrichments (party programs, news mentions); the app hides their panels when they are null
[ -f web/data/programs.js ] || echo "window.SW_PROGRAMS=null;" > web/data/programs.js
[ -f web/data/articles.js ] || echo "window.SW_ARTICLES=null;" > web/data/articles.js
PORT="${PORT:-5173}"
echo "Starwatch → http://127.0.0.1:${PORT}/"
exec uv run --offline python tools/serve.py --port "${PORT}"
