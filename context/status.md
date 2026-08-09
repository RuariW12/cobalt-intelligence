# Status

_Last updated: 2026-08-08_

## Exists

See README.md for how to run it. Layout:

```
cobalt/
  start.sh stop.sh        the supported entrypoints
  docker/                 Dockerfile, compose.yml, compose.gpu.yml, compose.vpn.yml
  app/main.py             FastAPI: routes, stubs /api/refresh + /api/summarize
  app/catalog.py          THE source of truth: every page, panel and row
  app/templates/          base.html + page.html — all 29 pages render from these
  etl/                    stub package; planned layout in its docstring
  requirements.txt        direct deps; requirements.lock pins everything
  config/ollama/          Modelfile defining the "cobalt" model (ctx, temp, prompt)
  context/                this directory
  web/                    static assets only — the pages are rendered, not files
    styles/               8 files, main.css is the manifest
    scripts/              main.js (deferred), theme.js (sync, in <head>)
```

29 pages, all from the catalog: home; news (+politics, economics, tech); macro
(+inflation, labor, growth); rates (+treasuries, credit); indexes (+us,
international); commodities; companies (+tech, industrial, energy, financials,
consumer); etfs (+broad, international, materials); ai-bubble; bitcoin.

URLs are unchanged from the static version, and both `/sections/macro` and
`/sections/macro/` resolve without a redirect.

## Conventions in the markup

- Chrome (crumb, h1, masthead, summary panel) lives in `base.html` only.
- Content components: `.metric` rows (one figure + change), `.quotes` tables
  (several numeric columns), `.stories` (headlines).
- Skeleton rows carry `.placeholder`, which dims them to `--skeleton`. Removing
  that class is what makes a row look live.

## Not built yet

- No backend, no database, no ETL, no API integrations.
- `#refresh` spins forever; `#summarize` shows the loader forever. Neither calls
  anything.
- Ollama integration — the model is configured and reachable, but nothing
  calls it yet. `/api/summarize` still returns 501.

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
