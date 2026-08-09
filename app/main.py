"""Cobalt web service.

Pages are rendered from app/catalog.py through a single template. The ETL and
the model integration are not built yet — their endpoints answer 501 with a
stable JSON shape, so the frontend can be wired against the real contract
before the work behind it lands.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import render
from store import db
from app.catalog import PAGES, SECTIONS

BASE_DIR = Path(__file__).resolve().parent
WEB_ROOT = BASE_DIR.parent / "web"

DB_PATH = os.environ.get("COBALT_DB", "/data/cobalt.db")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:9b")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

db.init()

app = FastAPI(title="cobalt", docs_url="/api/docs", redoc_url=None)


# --- api -------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "pages": len(PAGES),
        "sections": SECTIONS,
        "db": DB_PATH,
        "db_exists": Path(DB_PATH).exists(),
        "ollama_url": OLLAMA_URL,
        "model": OLLAMA_MODEL,
    }


def _check_section(section: str) -> JSONResponse | None:
    if section not in SECTIONS:
        return JSONResponse(status_code=400, content={"error": f"unknown section: {section}"})
    return None


@app.post("/api/refresh")
async def refresh(section: str = "home") -> JSONResponse:
    """Run the ingest for one section, or everything when section=home."""
    if bad := _check_section(section):
        return bad
    from etl.run import ingest

    # Blocking network work: off the event loop, or the page stops serving
    # while an ingest runs.
    try:
        result = await run_in_threadpool(ingest, "all" if section == "home" else section)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": "ingest failed", "detail": str(exc)})
    return JSONResponse(result)


@app.post("/api/summarize")
async def summarize(section: str = "home") -> JSONResponse:
    """Ask the local model to summarise what a section currently holds."""
    if bad := _check_section(section):
        return bad

    data = await run_in_threadpool(render.digest, section)
    prompt = f"Section: {section}\n\n{data}"

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    # qwen3.5 reasons by default: ~20x slower here for a worse
                    # answer. This cannot be set in the Modelfile.
                    "think": False,
                },
            )
            r.raise_for_status()
            body = r.json()
    except httpx.HTTPError as exc:
        return JSONResponse(status_code=503, content={
            "error": "model unavailable",
            "detail": f"{exc.__class__.__name__} talking to {OLLAMA_URL}",
            "hint": "start it with ./start.sh --llm",
        })

    return JSONResponse({
        "section": section,
        "model": OLLAMA_MODEL,
        "summary": (body.get("response") or "").strip(),
        "tokens": body.get("eval_count"),
    })


# --- assets ----------------------------------------------------------------
# Mounted individually rather than at "/", so only these two directories are
# public and the page routes below stay reachable.

app.mount("/styles", StaticFiles(directory=WEB_ROOT / "styles"), name="styles")
app.mount("/scripts", StaticFiles(directory=WEB_ROOT / "scripts"), name="scripts")


# --- pages -----------------------------------------------------------------

def _render(request: Request, slug: str) -> HTMLResponse:
    page = render.build(slug)
    if page is None:
        return HTMLResponse("<h1>404</h1><p>No such page.</p>", status_code=404)
    return templates.TemplateResponse(request, "page.html", {"page": page})


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return _render(request, "")


@app.get("/sections/{path:path}", response_class=HTMLResponse)
def section_page(request: Request, path: str) -> HTMLResponse:
    # Links are written without a trailing slash; browsers and old bookmarks may
    # add one. Both resolve to the same page rather than redirecting.
    return _render(request, f"sections/{path.strip('/')}")
