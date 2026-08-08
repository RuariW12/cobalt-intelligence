# Status

_Last updated: 2026-08-08_

## Exists

```
cobalt/
  Dockerfile              web service image; also runs the ETL
  docker-compose.yml      web + etl + ollama (llm profile) + volumes
  docker-compose.gpu.yml  NVIDIA overlay
  .env.example            copy to .env
  requirements.txt
  app/main.py             FastAPI: serves web/, stubs /api/refresh + /api/summarize
  etl/                    empty package; planned layout in its docstring
  serve.sh                static-only fallback, no backend
  context/                this directory
  web/                    THE SERVED ROOT — nothing else is public
    index.html            home page — the link index for everything
    styles/               8 files, main.css is the manifest
    scripts/              main.js (deferred), theme.js (sync, in <head>)
    sections/             one directory per section, one index.html per page
      news/               + politics, economics, tech
      macro/              + inflation, labor, growth
      rates/              + treasuries, credit
      indexes/            + us, international
      commodities/        single page: precious / industrial / energy groups
      companies/          + tech, industrial, energy, financials, consumer
      etfs/               + broad, international, materials
      ai-bubble/
      bitcoin/
      relationships/
```

29 pages. Directory-per-route, so the static file server resolves
`/sections/macro/inflation` with no backend and no routing table.

## Conventions in the markup

- Every page: breadcrumb, `h1`, masthead with refresh icon, `hr`, summary panel,
  then content. Only `/sections/relationships` omits the refresh (it ingests
  nothing of its own).
- Content components: `.metric` rows (one figure + change), `.quotes` tables
  (several numeric columns), `.stories` (headlines), `.chain` (relationships).
- Skeleton rows carry `.placeholder`, which dims them to `--skeleton`. Removing
  that class is what makes a row look live.

## Not built yet

- No backend, no database, no ETL, no API integrations.
- `#refresh` spins forever; `#summarize` shows the loader forever. Neither calls
  anything.
- Ollama integration — deferred by the user.

## Known data gaps

Four tracked commodities have no free spot feed and need proxies: **tungsten**
(assessed by paid services only), **lithium**, **cobalt**, **uranium**. The
practical stand-ins are LIT, REMX, SETM and URA — see the source notes on
`/sections/commodities/industrial` and `/sections/commodities/energy`.

## Open decision

The refresh and summarize buttons need a server that can run a job on request; a
static file server can't. Picking a backend (Flask / FastAPI) is the next real
decision. It would also let the masthead — currently copy-pasted into all 32
pages — collapse into one template partial.
