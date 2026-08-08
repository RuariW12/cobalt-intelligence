# Status

_Last updated: 2026-08-08_

## Exists

```
cobalt/
  index.html      home page — link lists for news / economics / trackers
  serve.sh        ./serve.sh [port] -> python3 -m http.server on 127.0.0.1:8080
  styles/
    main.css      base theme
  context/        this directory
```

Static only. `serve.sh` runs Python's stdlib file server — there is no backend.

## Not built yet

- Every link on the home page points at a route that does not exist (`/news`,
  `/econ/metals`, ...). They 404 today.
- `#refresh` on the home page is a placeholder with no handler.
- No backend, no database, no ETL, no API integrations.
- Ollama integration — deferred by the user.

## Open decision

The refresh button needs a server that can run a job on request; a static file
server can't. Picking a backend (Flask / FastAPI) is the next real decision, and
it also determines how the sub-pages get served. Not yet decided.
