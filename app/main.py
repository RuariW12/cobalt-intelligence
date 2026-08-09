"""Cobalt web service.

Pages are rendered from app/catalog.py through a single template. The ETL and
the model integration are not built yet — their endpoints answer 501 with a
stable JSON shape, so the frontend can be wired against the real contract
before the work behind it lands.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import render
from etl.sources.yahoo import intraday as yahoo_intraday
from etl.sources.yahoo import series as yahoo_series
from store import db
from app.catalog import PAGES, SECTIONS

BASE_DIR = Path(__file__).resolve().parent
WEB_ROOT = BASE_DIR.parent / "web"

DB_PATH = os.environ.get("COBALT_DB", "/data/cobalt.db")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:9b")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Stylesheets in cascade order. Linked individually rather than chained through
# a manifest of @imports: the browser revalidates the manifest, sees the same
# @import URLs and serves the imported files from cache, so a CSS edit stays
# invisible until a hard refresh. Separate links each carry their own version.
#
#   tokens    palette and type faces; the only literal colours
#   base      page frame, centred column, typography, breadcrumb, theme toggle
#   masthead  title row, refresh icon and its spin animation
#   summary   llm panel, ask button, three-dot loader
#   news      headlines and section tags
#   markets   metric rows and quote tables
#   chart     svg line charts and their controls
STYLESHEETS = ("tokens", "base", "masthead", "summary", "news", "markets", "chart")
SCRIPTS = ("theme", "main", "chart")


def _assets() -> dict:
    """Versioned asset URLs.

    The version is the newest mtime across the assets, so any edit changes every
    URL and the browser cannot serve a stale file — no hard refresh, ever.
    """
    paths = [WEB_ROOT / "styles" / f"{n}.css" for n in STYLESHEETS]
    paths += [WEB_ROOT / "scripts" / f"{n}.js" for n in SCRIPTS]
    try:
        version = int(max(p.stat().st_mtime for p in paths))
    except OSError:
        version = 0
    return {
        "styles": [f"/styles/{n}.css?v={version}" for n in STYLESHEETS],
        "scripts": {n: f"/scripts/{n}.js?v={version}" for n in SCRIPTS},
    }

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


# --- history, for the charts -----------------------------------------------

# Each view names the window it needs and how to backfill it if the store is
# short. Intraday is fetched live and never stored: it is superseded within
# minutes and would bloat a table built for daily closes.
RANGES: dict[str, dict] = {
    "1D":  {"intraday": ("1d", "5m")},
    "1W":  {"days": 7,    "fetch": ("1mo", "1d")},
    "1M":  {"days": 31,   "fetch": ("3mo", "1d")},
    "YTD": {"ytd": True,  "fetch": ("ytd", "1d")},
    "1Y":  {"days": 365,  "fetch": ("1y", "1d")},
    "5Y":  {"days": 1826, "fetch": ("5y", "1d")},
    "10Y": {"days": 3652, "fetch": ("10y", "1d")},
}


@app.get("/api/history")
async def history(key: str, range: str = "YTD") -> JSONResponse:
    spec = RANGES.get(range.upper())
    if spec is None:
        return JSONResponse(status_code=400, content={
            "error": f"unknown range: {range}", "valid": list(RANGES)})

    inst = db.instruments().get(key)

    if "intraday" in spec:
        rng, interval = spec["intraday"]
        try:
            points = await run_in_threadpool(yahoo_intraday, key, rng, interval)
        except Exception as exc:
            return JSONResponse(status_code=502, content={
                "error": "intraday unavailable", "detail": str(exc)})
        return JSONResponse(_series_payload(key, inst, range, points))

    today = date.today()
    since = (date(today.year, 1, 1) if spec.get("ytd")
             else today - timedelta(days=spec["days"])).isoformat()

    rows = await run_in_threadpool(db.history, key, since)
    have_from = await run_in_threadpool(db.history_start, key)

    # Backfill only when the store genuinely does not reach far enough back —
    # a few days of slack absorbs weekends and holidays.
    if have_from is None or (have_from > since
                             and (date.fromisoformat(have_from) - date.fromisoformat(since)).days > 5):
        rng, interval = spec["fetch"]
        try:
            fetched = await run_in_threadpool(yahoo_series, key, rng, interval)
            await run_in_threadpool(db.write_history, key, fetched)
            rows = await run_in_threadpool(db.history, key, since)
        except Exception:
            pass  # serve whatever is stored rather than failing the chart

    points = [(r["as_of"], r["close"]) for r in rows]
    return JSONResponse(_series_payload(key, inst, range, points))


def _series_payload(key: str, inst, rng: str, points: list) -> dict:
    first = points[0][1] if points else None
    last = points[-1][1] if points else None
    return {
        "key": key,
        "name": (inst["name"] if inst else key),
        "unit": (inst["unit"] if inst else None),
        "range": rng.upper(),
        "points": points,
        "change_pct": ((last / first - 1) * 100) if first and last else None,
    }


# --- assets ----------------------------------------------------------------
# Mounted individually rather than at "/", so only these two directories are
# public and the page routes below stay reachable.

class RevalidatingStatic(StaticFiles):
    """Serve assets with `Cache-Control: no-cache`.

    Not "do not cache" — the browser still stores the file, but must revalidate
    before reuse, so an edit shows up on an ordinary reload. Without this,
    stylesheets pulled in through main.css's @import chain are especially
    sticky: the browser revalidates main.css, sees the same @import URLs, and
    serves the imported files straight from cache. Editing base.css then has no
    visible effect until a hard refresh, which looks exactly like a CSS bug.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/styles", RevalidatingStatic(directory=WEB_ROOT / "styles"), name="styles")
app.mount("/scripts", RevalidatingStatic(directory=WEB_ROOT / "scripts"), name="scripts")


# --- pages -----------------------------------------------------------------

def _render(request: Request, slug: str) -> HTMLResponse:
    page = render.build(slug)
    if page is None:
        return HTMLResponse("<h1>404</h1><p>No such page.</p>", status_code=404)
    return templates.TemplateResponse(request, "page.html",
                                     {"page": page, **_assets()})


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return _render(request, "")


@app.get("/sections/{path:path}", response_class=HTMLResponse)
def section_page(request: Request, path: str) -> HTMLResponse:
    # Links are written without a trailing slash; browsers and old bookmarks may
    # add one. Both resolve to the same page rather than redirecting.
    return _render(request, f"sections/{path.strip('/')}")
