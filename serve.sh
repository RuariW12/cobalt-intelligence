#!/usr/bin/env bash
# Serve the static pages with no backend and no Docker.
# The refresh and summarize buttons need the app: use `docker compose up`.
set -euo pipefail

PORT="${1:-8080}"
cd "$(dirname "$0")/web"

echo "cobalt (static only) -> http://localhost:${PORT}"
exec python3 -m http.server "$PORT" --bind 127.0.0.1
