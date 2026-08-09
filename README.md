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
./cobalt-start.sh
```

Open <http://localhost:5173>. Stop with `./cobalt-stop.sh` — your data is in a named
volume and survives.

```sh
./cobalt-start.sh              app only
./cobalt-start.sh --llm        + the local model server
./cobalt-start.sh --gpu --llm  + the model server on an NVIDIA GPU
./cobalt-stop.sh               stop everything, keep data
./cobalt-stop.sh --wipe        also delete the database and model weights
```

If port 5173 is taken, set `COBALT_PORT` in `.env`.

### Behind a VPN

A kill switch that drops non-tunnel traffic (Mullvad, ProtonVPN and similar)
breaks Docker's bridge network — builds fail to reach PyPI and published ports
refuse connections even though the container is healthy. `./cobalt-start.sh` detects
this and switches to host networking automatically.

The cleaner fix, which keeps the portable setup everyone else uses:

```sh
mullvad lan set allow
```

---

## Running the local LLM

```sh
./cobalt-start.sh --llm
```

That checks Ollama is up (starting the service if not), builds the **cobalt**
model from `config/ollama/Modelfile`, points the app at it, and prints whether
it landed on the GPU:

```
  cobalt is up -> http://localhost:5173
  model        -> cobalt on http://127.0.0.1:11434
  processor    -> 100% GPU
```

If that last line says CPU, the model is running perhaps 20x slower than it
should — see below.

### Ollama runs on the host, not in a container

That is the default because it is the better trade with an NVIDIA card:

- **No NVIDIA Container Toolkit needed.** Ollama talks to the driver directly.
  Inside Docker it needs the toolkit, and without it falls back to CPU silently.
- **No duplicate weights.** The model you already pulled is used as is, rather
  than downloaded again into a volume.

Install Ollama from <https://ollama.com>, then pull the base model:

```sh
ollama pull qwen3.5:9b          # or set OLLAMA_BASE_MODEL
```

To run it in Docker anyway: `./cobalt-start.sh --container-ollama` — and read the GPU
section below first, or it will be CPU-only.

### Configuration

`config/ollama/Modelfile` defines the **cobalt** model: context window, sampling
parameters and system prompt, version-controlled in the repo. `./cobalt-start.sh --llm`
rebuilds it every run, which is cheap — it is a manifest over weights already on
disk, not another copy.

Two settings matter more than the rest:

- **`num_ctx 16384`.** Ollama defaults to 4096 and truncates past it *silently*.
  A day of headlines exceeds that, and the result looks like a working summary
  of partial data rather than an error.
- **`"think": false` on every request.** qwen3.5 is a reasoning model. Measured
  on an RTX 4070 Super with the same prompt:

  | | wall | tokens generated |
  | --- | --- | --- |
  | `think: true` | 52.7s | 3220 |
  | `think: false` | **2.4s** | 124 |

  The shorter run produced the better summary. This one cannot live in the
  Modelfile — `PARAMETER think` is rejected — so it belongs in the request body.

## Using an NVIDIA GPU

**Only needed if you run Ollama in a container** (`--container-ollama`). With
the default host-native Ollama the GPU already works, and `./cobalt-start.sh --llm`
prints `processor -> 100% GPU` to prove it.

Docker cannot see your GPU by default. Without the steps below the container
starts and **silently runs on CPU**.

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
./cobalt-start.sh --gpu --llm
```

### 4. Confirm the model is actually on the GPU

```sh
docker compose -f docker/compose.yml exec ollama ollama ps
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
docker compose -f docker/compose.yml run --rm etl --section macro
docker compose -f docker/compose.yml run --rm etl --section all
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
| `ollama` | Model server — only for `--container-ollama`. By default Ollama runs on the host. |
| `model-init` | Pulls the base weights into the container volume, then exits. Same caveat. |

**There is no database service.** SQLite is a file, not a server; it lives in
the `cobalt-data` volume that `web` and `etl` share. If this ever needs
concurrent writers or network access, that is when Postgres becomes a container.

```
cobalt-start.sh cobalt-stop.sh   the supported way to run it
config/ollama/     Modelfile defining the "cobalt" model
app/               FastAPI service
etl/               ingest pipeline (stub)
web/               the served root — nothing outside this directory is public
docker/            Dockerfile, compose.yml, and the gpu / vpn overlays
context/           design notes: the spec, sources, decisions and their reasoning
.dockerignore      stays at the root: it must sit at the build context root
```

### Editing the Python

The app only ever runs in Docker, so nothing needs installing to use it. But an
editor cannot resolve `fastapi` without a local interpreter that has it, which
shows up as a false "import could not be resolved" warning.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
```

Installing from the lock rather than `requirements.txt` means the editor checks
against exactly the versions the container runs. `.vscode/settings.json` already
points at `.venv`; other editors need the interpreter set once.

### Reproducibility

- `requirements.lock` pins every package, including transitive dependencies.
  Rebuilding on another machine or in a year resolves identically.
  Regenerate after editing `requirements.txt`:
  ```sh
  docker compose -f docker/compose.yml build web
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

**`pip` fails during build with a DNS error.** Usually a VPN kill switch (see
*Behind a VPN* above) — `./cobalt-start.sh` handles it. Otherwise your daemon has no
working DNS: add `{"dns": ["1.1.1.1"]}` to `/etc/docker/daemon.json` and
restart Docker.

**Port already in use.** Set `COBALT_PORT` in `.env`, or find the holder with
`ss -ltnp | grep 5173`. `./cobalt-start.sh` names the holder for you.

**Pages 404 but `/api/health` works.** The `web/` directory didn't make it into
the image. Rebuild with `docker compose build --no-cache web`.
