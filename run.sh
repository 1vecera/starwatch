#!/usr/bin/env bash
# Start Starwatch locally at http://127.0.0.1:5173/ (set PORT to change it).
# A fresh checkout serves the labelled simulated universe: no credentials, no paid collection.
set -euo pipefail
cd "$(dirname "$0")/app"
export SKIP_EXPORT=1
exec ./run.sh
