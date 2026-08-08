#!/usr/bin/env bash
# Serve the cobalt frontend on localhost.
set -euo pipefail

PORT="${1:-8080}"
cd "$(dirname "$0")"

echo "cobalt -> http://localhost:${PORT}"
exec python3 -m http.server "$PORT" --bind 127.0.0.1
