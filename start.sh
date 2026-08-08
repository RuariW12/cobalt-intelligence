#!/usr/bin/env bash
# Start Cobalt.
#
#   ./start.sh              app only
#   ./start.sh --llm        app + ollama model server
#   ./start.sh --gpu --llm  ollama on an NVIDIA GPU
#   ./start.sh --vpn        force host networking (auto-detected normally)
#   ./start.sh --no-vpn     never use host networking
#
# Stop everything with ./stop.sh
set -euo pipefail

cd "$(dirname "$0")"

PORT="${COBALT_PORT:-5173}"
if [ -f .env ]; then
  from_env="$(grep -E '^COBALT_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2 || true)"
  [ -n "$from_env" ] && PORT="$from_env"
fi

FILES=(-f docker/compose.yml)
PROFILES=()
VPN=auto

for arg in "$@"; do
  case "$arg" in
    --llm)     PROFILES+=(--profile llm) ;;
    --gpu)     FILES+=(-f docker/compose.gpu.yml) ;;
    --vpn)     VPN=on ;;
    --no-vpn)  VPN=off ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *)         echo "unknown flag: $arg (try --help)" >&2; exit 2 ;;
  esac
done

command -v docker >/dev/null || { echo "docker is not installed" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "docker daemon is not running" >&2; exit 1; }

# A VPN kill switch that drops non-tunnel traffic breaks Docker's bridge for
# both builds and published ports. Detect it up front rather than failing with
# a DNS error during build or a blank page in the browser.
if [ "$VPN" = auto ]; then
  if command -v mullvad >/dev/null 2>&1 && mullvad lan get 2>/dev/null | grep -q block; then
    echo "VPN detected with local network sharing blocked -> using host networking."
    echo "  (to use the normal bridge instead:  mullvad lan set allow)"
    VPN=on
  else
    VPN=off
  fi
fi
[ "$VPN" = on ] && FILES+=(-f docker/compose.vpn.yml)

# Something already on the port stops the container binding. Only matters for
# the bridge path; host networking fails later with a clearer error.
if [ "$VPN" = off ] && ss -ltn "sport = :$PORT" 2>/dev/null | grep -q LISTEN; then
  if ! docker compose "${FILES[@]}" ps --format '{{.Service}}' 2>/dev/null | grep -q web; then
    holder="$(ss -ltnp "sport = :$PORT" 2>/dev/null | grep -oP 'users:\(\("\K[^"]+' | head -1 || echo '?')"
    echo "port $PORT is already in use by: $holder" >&2
    echo "stop it, or set COBALT_PORT in .env" >&2
    exit 1
  fi
fi

echo "starting cobalt..."
docker compose "${FILES[@]}" "${PROFILES[@]}" up -d --build

# Wait for the healthcheck rather than guessing with sleep.
printf "waiting for health"
for _ in $(seq 1 60); do
  state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
           cobalt-web-1 2>/dev/null || echo starting)"
  case "$state" in
    healthy)          echo " -> healthy"; break ;;
    unhealthy|exited) echo " -> $state"; docker compose "${FILES[@]}" logs --tail 30 web; exit 1 ;;
    *)                printf "."; sleep 1 ;;
  esac
done

URL="http://localhost:${PORT}"
echo

if curl -fsS -m 3 -o /dev/null "${URL}/api/health" 2>/dev/null; then
  echo "  cobalt is up -> ${URL}"
  [ ${#PROFILES[@]} -gt 0 ] && echo "  ollama       -> http://localhost:${OLLAMA_PORT:-11434}"
  exit 0
fi

# Healthy container, unreachable URL: almost always the bridge being blocked.
echo "  container is healthy, but ${URL} is not reachable."
if [ "$VPN" = on ]; then
  echo "  host networking is already on. Check:  docker compose ${FILES[*]} logs web"
else
  echo "  If a VPN is connected, retry with:  ./start.sh --vpn"
fi
exit 1
