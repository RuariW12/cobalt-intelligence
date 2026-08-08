#!/usr/bin/env bash
# Start Cobalt.
#
#   ./start.sh                app only
#   ./start.sh --llm          app + ollama model server
#   ./start.sh --host-net     bypass Docker's bridge (VPN kill switches block it)
#   ./start.sh --gpu --llm    ollama on an NVIDIA GPU
#
# Flags combine. Stop everything with ./stop.sh
set -euo pipefail

cd "$(dirname "$0")"

PORT="${COBALT_PORT:-5173}"
[ -f .env ] && PORT="$(grep -E '^COBALT_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2 || true)"
PORT="${PORT:-5173}"

FILES=(-f docker-compose.yml)
# Passing any -f flag disables Compose's automatic merge of
# docker-compose.override.yml, so re-add it explicitly when present.
[ -f docker-compose.override.yml ] && FILES+=(-f docker-compose.override.yml)
PROFILES=()
HOST_NET=0

for arg in "$@"; do
  case "$arg" in
    --llm)      PROFILES+=(--profile llm) ;;
    --gpu)      FILES+=(-f docker-compose.gpu.yml) ;;
    --host-net) FILES+=(-f docker-compose.hostnet.yml); HOST_NET=1 ;;
    -h|--help)  sed -n '2,9p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *)          echo "unknown flag: $arg (try --help)" >&2; exit 2 ;;
  esac
done

command -v docker >/dev/null || { echo "docker is not installed" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "docker daemon is not running" >&2; exit 1; }

# A stale ./serve.sh or another service on the port stops the container binding.
if [ "$HOST_NET" -eq 0 ] && ss -ltn "sport = :$PORT" 2>/dev/null | grep -q LISTEN; then
  holder="$(ss -ltnp "sport = :$PORT" 2>/dev/null | grep -oP 'users:\(\("\K[^"]+' | head -1 || echo '?')"
  if ! docker compose "${FILES[@]}" ps --format '{{.Service}}' 2>/dev/null | grep -q web; then
    echo "port $PORT is already in use by: $holder" >&2
    echo "stop it, or set COBALT_PORT in .env to something else" >&2
    exit 1
  fi
fi

echo "starting cobalt..."
docker compose "${FILES[@]}" "${PROFILES[@]}" up -d --build

# Wait for the container to report healthy rather than guessing with sleep.
printf "waiting for health"
for _ in $(seq 1 60); do
  state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
           cobalt-web-1 2>/dev/null || echo starting)"
  case "$state" in
    healthy|running) echo " -> $state"; break ;;
    unhealthy|exited) echo " -> $state"; docker compose "${FILES[@]}" logs --tail 30 web; exit 1 ;;
    *) printf "."; sleep 1 ;;
  esac
done

URL="http://localhost:${PORT}"

# The container can be perfectly healthy while the host still cannot reach the
# published port — a VPN kill switch drops Docker bridge traffic. Check, so the
# failure is explained here rather than in the browser.
if curl -fsS -m 3 -o /dev/null "${URL}/api/health" 2>/dev/null; then
  echo
  echo "  cobalt is up -> ${URL}"
  [ ${#PROFILES[@]} -gt 0 ] && echo "  ollama       -> http://localhost:${OLLAMA_PORT:-11434}"
else
  echo
  echo "  container is healthy, but ${URL} is not reachable from this machine."
  if [ "$HOST_NET" -eq 1 ]; then
    echo "  host networking is already on — check the logs:  ./start.sh --help"
  else
    echo
    echo "  Most likely a VPN kill switch blocking Docker's bridge network."
    if command -v mullvad >/dev/null 2>&1; then
      echo "  Mullvad detected. Current setting: $(mullvad lan get 2>/dev/null || echo unknown)"
      echo "  Fix it properly:   mullvad lan set allow"
    fi
    echo "  Or bypass the bridge:  ./stop.sh && ./start.sh --host-net"
  fi
  exit 1
fi
