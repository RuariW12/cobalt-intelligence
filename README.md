# Cobalt

A personal, locally hosted market intelligence platform. Tracks macroeconomics,
interest rates, market indexes, commodities, key companies and ETFs, pulls news
alongside them, and summarises any section with a local LLM.

Everything runs on your own machine. No accounts, no cloud, no telemetry.

---

## Quick start

Requires [Docker](https://docs.docker.com/get-docker/) with Compose v2.

```sh
git clone <your-repo-url> cobalt
cd cobalt
cp .env.example .env      # optional for now; needed once the ETL lands
docker compose up -d
```

Open <http://localhost:5173>.

To stop: `docker compose down`. Your data lives in a named volume and survives.

If port 5173 is taken, set `COBALT_PORT=5174` in `.env`.

### Without Docker

The pages are static, so you can browse them with no backend at all:

```sh
./serve.sh          # http://localhost:5173
```

The refresh and summarize buttons need the app; everything else works.

---

## Running the local LLM

The model server is **off by default** so a plain `up` doesn't idle several GB
of RAM or trigger a multi-gigabyte download. Enable it with the `llm` profile.

### 1. Pick a model

Set `OLLAMA_MODEL` in `.env`. Sizing guide for a 12 GB GPU:

| Model size | Q4 weights | Fits 12 GB with 16k context? |
| --- | --- | --- |
| 8–9B | ~5 GB | comfortably |
| 14B | ~9 GB | yes, with `OLLAMA_KV_CACHE_TYPE=q8_0` |
| 24B+ | 14 GB+ | no — spills to system RAM and crawls |

Summarisation here is prefill-heavy (long input, short output), and CPU offload
hurts prefill far more than generation, so staying inside VRAM matters more
than parameter count.

Verify the exact tag exists before setting it — model names change between
generations:

```sh
docker compose --profile llm up -d ollama
docker compose exec ollama ollama list
```

### 2. Start it and pull the weights

```sh
docker compose --profile llm up -d
docker compose --profile llm run --rm model-init     # one-time download
```

The weights land in the `ollama-models` volume, so `docker compose down` never
costs you a re-download.

---

## Using an NVIDIA GPU

Docker cannot see your GPU by default. Without the steps below the container
starts and **silently runs on CPU** — for a 9B model that is the difference
between seconds and minutes per summary.

### 1. Install the NVIDIA Container Toolkit

Driver first — check with `nvidia-smi`. Then, on Debian/Ubuntu:

```sh
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt update && sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Fedora/RHEL use `dnf` with the equivalent repo; Arch has
`nvidia-container-toolkit` in the AUR.

### 2. Verify Docker can see the GPU

```sh
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

Your GPU should be listed. If this fails, nothing below will work.

### 3. Start with the GPU overlay

```sh
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile llm up -d
```

### 4. Confirm the model is actually on the GPU

```sh
docker compose exec ollama ollama ps
```

The `PROCESSOR` column should read `100% GPU`. Anything mentioning CPU means
the toolkit isn't wired up — recheck step 2.

### No GPU, or on a Mac?

It still runs; generation is just slower. Docker Desktop **cannot** pass through
Apple Silicon GPUs, so on a Mac run Ollama natively instead and point the app at
it — skip the `llm` profile and set in `.env`:

```sh
OLLAMA_URL=http://host.docker.internal:11434     # macOS / Windows
OLLAMA_URL=http://172.17.0.1:11434               # Linux, host-native ollama
```

---

## Ingesting data

```sh
docker compose run --rm etl --section macro     # one section
docker compose run --rm etl --section all       # everything
```

Most series come from [FRED](https://fredaccount.stlouisfed.org), which needs a
free API key in `.env` as `FRED_API_KEY`. Prices come from Yahoo Finance and
need no key.

Not implemented yet — the command currently exits with a pointer to the design
in [`context/etl-plan.md`](context/etl-plan.md).

---

## How it fits together

| Service | Role |
| --- | --- |
| `web` | FastAPI. Serves the pages and the API on port 8000 in-container. |
| `etl` | Same image, one-shot ingest command. |
| `ollama` | Model server. `llm` profile only. |
| `model-init` | Pulls the model, then exits. `llm` profile only. |

**There is no database service.** SQLite is a file, not a server; it lives in
the `cobalt-data` volume that `web` and `etl` share. If this ever needs
concurrent writers or network access, that is when Postgres becomes a container.

```
app/        FastAPI service
etl/        ingest pipeline (stub)
web/        the served root — nothing outside this directory is public
context/    design notes: the spec, sources, decisions and their reasoning
```

### Reproducibility

- `requirements.lock` pins every package, including transitive dependencies.
  Rebuilding on another machine or in a year resolves identically.
  Regenerate after editing `requirements.txt`:
  ```sh
  docker compose build web
  docker run --rm cobalt:latest pip freeze > requirements.lock
  ```
- The base image `python:3.12-slim` and `ollama/ollama` are both multi-arch, so
  amd64 and arm64 hosts build from the same file.
- Set `TZ` in `.env` (e.g. `TZ=America/New_York`). Containers default to UTC,
  which shifts what counts as "today" for news and market sessions.

### Backup

```sh
docker run --rm -v cobalt_cobalt-data:/d -v "$PWD":/b alpine \
  tar czf /b/cobalt-data.tar.gz -C /d .
```

---

## Troubleshooting

**`pip` fails during build with a DNS error.** Your Docker daemon has no
working DNS on its build network. Fix it daemon-side by adding
`{"dns": ["1.1.1.1"]}` to `/etc/docker/daemon.json` and restarting Docker. As a
Linux-only workaround, copy `docker-compose.override.yml.example` to
`docker-compose.override.yml` — Compose merges it automatically.

**Port already in use.** Set `COBALT_PORT` in `.env`, or find the holder with
`ss -ltnp | grep 5173`.

**Pages 404 but `/api/health` works.** The `web/` directory didn't make it into
the image. Rebuild with `docker compose build --no-cache web`.
