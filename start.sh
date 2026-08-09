#!/usr/bin/env bash
# Start Cobalt.
#
#   ./start.sh              app only
#   ./start.sh --llm        app + the local model (host ollama by default)
#   ./start.sh --gpu --llm  ollama on an NVIDIA GPU
#   ./start.sh --container-ollama  run ollama in Docker instead of on the host
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
# Compose reads .env from the project directory, which defaults to the
# compose file's directory — docker/ — not the repo root. Without this the
# .env you actually edit is silently ignored.
[ -f .env ] && FILES=(--env-file .env "${FILES[@]}")
LLM=0
CONTAINER_OLLAMA=0
OLLAMA_HOST_URL="http://127.0.0.1:11434"
BASE_MODEL="${OLLAMA_BASE_MODEL:-qwen3.5:9b}"
PROFILES=()
VPN=auto

for arg in "$@"; do
  case "$arg" in
    --llm)     LLM=1 ;;
    --container-ollama) LLM=1; CONTAINER_OLLAMA=1; PROFILES+=(--profile llm) ;;
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

if [ "$LLM" = 1 ] && [ "$CONTAINER_OLLAMA" = 0 ]; then
  # Host-native ollama is the right default with an NVIDIA card: it uses the
  # driver directly, so no container toolkit is needed, and the weights are
  # already on disk rather than duplicated into a volume.
  if ! curl -fsS -m 3 -o /dev/null "${OLLAMA_HOST_URL}/api/tags" 2>/dev/null; then
    echo "ollama is not answering on ${OLLAMA_HOST_URL}; trying to start it..."
    systemctl start ollama 2>/dev/null || sudo systemctl start ollama 2>/dev/null || true
    for _ in $(seq 1 20); do
      curl -fsS -m 2 -o /dev/null "${OLLAMA_HOST_URL}/api/tags" 2>/dev/null && break
      sleep 1
    done
  fi

  if curl -fsS -m 3 -o /dev/null "${OLLAMA_HOST_URL}/api/tags" 2>/dev/null; then
    if ! ollama list 2>/dev/null | grep -q "^${BASE_MODEL%%:*}"; then
      echo "base model ${BASE_MODEL} is not present. Pull it with:  ollama pull ${BASE_MODEL}" >&2
      exit 1
    fi
    # Cheap: a manifest over existing weights, so re-running keeps the
    # Modelfile and the loaded model in sync with no download.
    echo "building the 'cobalt' model from config/ollama/Modelfile..."
    ollama create cobalt -f config/ollama/Modelfile >/dev/null 2>&1 \
      || { echo "ollama create failed" >&2; exit 1; }

    # Under host networking the container shares this loopback; on the bridge
    # it needs the gateway alias declared in compose.
    if [ "$VPN" = on ]; then
      export OLLAMA_URL="$OLLAMA_HOST_URL"
    else
      export OLLAMA_URL="http://host.docker.internal:11434"
    fi
    export OLLAMA_MODEL=cobalt
  else
    echo "could not reach or start ollama on the host." >&2
    echo "either start it, or run the containerised one:  ./start.sh --container-ollama" >&2
    exit 1
  fi
fi

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
  if [ "$LLM" = 1 ]; then
    echo "  model        -> cobalt on ${OLLAMA_URL:-container}"
    # Match the processor column by content, not position: the SIZE column
    # ("6.0 GB") is two fields, which shifts everything after it.
    proc="$(ollama ps 2>/dev/null | grep -oE '[0-9]+%[[:space:]]*(GPU|CPU)' | head -1)"
    if [ -n "$proc" ]; then
      case "$proc" in
        *GPU*) echo "  processor    -> $proc" ;;
        *)     echo "  processor    -> $proc  <- not on the GPU; check nvidia-smi" ;;
      esac
    fi
  fi
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
