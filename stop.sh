#!/usr/bin/env bash
# Stop Cobalt.
#
#   ./stop.sh            stop and remove containers; data and models are kept
#   ./stop.sh --wipe     also delete the volumes (database AND model weights)
#
# Every overlay and profile is passed so nothing is left running, whichever
# way it was started.
set -euo pipefail

cd "$(dirname "$0")"

WIPE=0
for arg in "$@"; do
  case "$arg" in
    --wipe)    WIPE=1 ;;
    -h|--help) sed -n '2,7p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *)         echo "unknown flag: $arg (try --help)" >&2; exit 2 ;;
  esac
done

command -v docker >/dev/null || { echo "docker is not installed" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "docker daemon is not running" >&2; exit 1; }

# Include every overlay: `down` only removes what the merged config declares,
# so a stack started with --vpn or --gpu must be torn down the same way.
FILES=(-f docker/compose.yml -f docker/compose.gpu.yml -f docker/compose.vpn.yml)
# Compose reads .env from the project directory, which defaults to the
# compose file's directory — docker/ — not the repo root. Without this the
# .env you actually edit is silently ignored.
[ -f .env ] && FILES=(--env-file .env "${FILES[@]}")
PROFILES=(--profile llm --profile tools)

if [ "$WIPE" -eq 1 ]; then
  echo "This deletes the database and the downloaded model weights."
  printf "Type 'wipe' to confirm: "
  read -r reply
  [ "$reply" = "wipe" ] || { echo "aborted"; exit 1; }
  docker compose "${FILES[@]}" "${PROFILES[@]}" down --volumes --remove-orphans
  echo "stopped; volumes deleted"
else
  docker compose "${FILES[@]}" "${PROFILES[@]}" down --remove-orphans
  echo "stopped; volumes kept ($(docker volume ls -q --filter name=cobalt | tr '\n' ' '))"
fi
