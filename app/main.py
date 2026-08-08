"""Cobalt web service.

Serves the static pages and exposes the endpoints those pages call. The ETL and
the model integration are not built yet — their endpoints answer 501 with a
stable JSON shape, so the frontend can be wired against the real contract
before the work behind it lands.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"

DB_PATH = os.environ.get("COBALT_DB", "/data/cobalt.db")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:9b")

# Sections a refresh can be scoped to. Matches <body data-section="..."> in the
# pages; "home" means everything.
SECTIONS = {
    "home", "news", "macro", "rates", "indexes", "commodities",
    "companies", "etfs", "ai-bubble", "bitcoin", "relationships",
}

app = FastAPI(title="cobalt", docs_url="/api/docs", redoc_url=None)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "db": DB_PATH,
        "db_exists": Path(DB_PATH).exists(),
        "ollama_url": OLLAMA_URL,
        "model": OLLAMA_MODEL,
        "web_root": str(WEB_ROOT),
    }


@app.post("/api/refresh")
def refresh(section: str = "home") -> JSONResponse:
    """Run the ingest for one section, or everything when section=home."""
    if section not in SECTIONS:
        return JSONResponse(status_code=400, content={"error": f"unknown section: {section}"})
    return JSONResponse(
        status_code=501,
        content={"error": "not implemented", "detail": "ETL pipeline not built yet",
                 "section": section},
    )


@app.post("/api/summarize")
def summarize(section: str = "home") -> JSONResponse:
    """Ask the local model to summarise what a section currently holds."""
    if section not in SECTIONS:
        return JSONResponse(status_code=400, content={"error": f"unknown section: {section}"})
    return JSONResponse(
        status_code=501,
        content={"error": "not implemented", "detail": "model integration not built yet",
                 "section": section, "model": OLLAMA_MODEL},
    )


# Mounted last so the /api routes above take precedence. html=True serves
# <dir>/index.html and already 307s "/sections/macro" to "/sections/macro/",
# which is how every page links, so no redirect handling is needed here.
app.mount("/", StaticFiles(directory=WEB_ROOT, html=True), name="web")
