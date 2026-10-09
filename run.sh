#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/app"
export SKIP_EXPORT=1
exec ./run.sh
