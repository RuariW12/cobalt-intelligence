# Running Cobalt in containers

## What is and isn't a container

| Piece | Container? | Why |
| --- | --- | --- |
| Web service (frontend + API) | **yes** — `web` | One FastAPI process serves the static pages *and* the endpoints. A separate nginx would add a moving part with nothing to gain at one user. |
| ETL | **yes**, same image — `etl` | Shares code with the web service, so it must share an image. Runs as a one-shot command, not a long-lived service. |
| Database | **no** | SQLite is a file, not a server. It lives in the `cobalt-data` volume, shared by `web` and `etl`. Adding a Postgres container would be pure overhead until something needs concurrent writers or network access. |
| Ollama / Qwen | **yes** — `ollama`, behind the `llm` profile | Off by default so a plain `up` doesn't idle several GB of RAM or trigger a multi-GB pull. |
| Model weights | volume `ollama-models` | Named so `docker compose down` never costs a re-download. |

## Commands

```sh
docker compose up -d                       # app only, http://localhost:8080
docker compose --profile llm up -d         # app + ollama (CPU)
docker compose --profile llm run --rm model-init   # pull the model, once
docker compose run --rm etl --section macro        # one-shot ingest
docker compose logs -f web
docker compose down                        # volumes survive
```

With an NVIDIA GPU:

```sh
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile llm up -d
```

## Host notes

**GPU passthrough needs the NVIDIA Container Toolkit, which is not installed
here.** Without it the ollama container starts and silently runs on CPU — for a
9B model that is the difference between seconds and minutes per summary.

```sh
sudo apt install nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Alternative that needs no toolkit: run ollama natively on the host, skip the
`llm` profile, and point the app at it —
`OLLAMA_URL=http://172.17.0.1:11434` on Linux,
`http://host.docker.internal:11434` on macOS/Windows. This is the *only* option
on Apple Silicon, where Docker Desktop cannot pass through the GPU.

**BuildKit on this host has no DNS on its default bridge**, so `pip install`
fails during a build. `docker-compose.yml` therefore sets `build.network: host`,
which fixes it and is harmless on hosts that resolve normally. Reproduce with:

```sh
printf 'FROM alpine\nRUN getent hosts pypi.org\n' > /tmp/t/Dockerfile
docker build --no-cache /tmp/t          # fails
docker build --no-cache --network=host /tmp/t   # works
```

## Layout this assumes

`web/` is the served root and holds *only* what should be public. It was split
out of the repo root for exactly that reason — mounting the repo root would
serve `Dockerfile`, `.env` and the source. Verified: those all 404.

URLs did not change in the move, because every path in the pages is
root-absolute.

## Backup

```sh
docker run --rm -v cobalt_cobalt-data:/d -v "$PWD":/b alpine \
  tar czf /b/cobalt-data.tar.gz -C /d .
```
