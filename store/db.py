"""Connection handling, schema, and the reads/writes both halves of the app use.

SQLite, one file, no server. `observation` is append-only keyed by date so
revisions stay visible — macro series get revised, and overwriting would erase
the fact that they changed.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

DB_PATH = Path(os.environ.get("COBALT_DB", "/data/cobalt.db"))
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    # WAL lets the web service keep serving pages while an ingest writes.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA_PATH.read_text())
        # A crash mid-ingest leaves a run marked 'running' forever, which makes
        # last_refresh() and any future health check lie. Reap them on startup.
        conn.execute(
            """UPDATE ingest_run SET status='error', error='interrupted',
                   finished_at=datetime('now')
               WHERE status='running' AND started_at < datetime('now','-1 hour')""")


# --- instruments -----------------------------------------------------------

def upsert_instruments(rows: Iterable[dict]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    with connect() as conn:
        conn.executemany(
            """INSERT INTO instrument
                 (key, kind, name, ticker, unit, period, section, category, page,
                  asset_class, source)
               VALUES (:key,:kind,:name,:ticker,:unit,:period,:section,:category,:page,
                       :asset_class,:source)
               ON CONFLICT(key) DO UPDATE SET
                 name=excluded.name, ticker=excluded.ticker, unit=excluded.unit,
                 period=excluded.period, section=excluded.section,
                 category=excluded.category, page=excluded.page,
                 asset_class=excluded.asset_class, source=excluded.source""",
            rows,
        )
    return len(rows)


def instruments() -> dict[str, sqlite3.Row]:
    with connect() as conn:
        return {r["key"]: r for r in conn.execute("SELECT * FROM instrument")}


def replace_tags(key: str, tags: Iterable[str]) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM tag WHERE key = ?", (key,))
        conn.executemany("INSERT OR IGNORE INTO tag (key, tag) VALUES (?,?)",
                         [(key, t) for t in tags])


def tags_for(key: str) -> list[str]:
    with connect() as conn:
        return [r["tag"] for r in
                conn.execute("SELECT tag FROM tag WHERE key=? ORDER BY tag", (key,))]


# --- observations ----------------------------------------------------------

def write_observations(rows: Iterable[dict]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    with connect() as conn:
        conn.executemany(
            """INSERT INTO observation
                 (kind,key,as_of,ts,value,previous,change,pct,ytd_pct,currency,quality,
                  source,fetched_at)
               VALUES (:kind,:key,:as_of,:ts,:value,:previous,:change,:pct,:ytd_pct,:currency,
                       :quality,:source,:fetched_at)
               ON CONFLICT(kind,key,as_of) DO UPDATE SET
                 ts=excluded.ts, value=excluded.value, previous=excluded.previous,
                 change=excluded.change, pct=excluded.pct, ytd_pct=excluded.ytd_pct,
                 currency=excluded.currency,
                 quality=excluded.quality, source=excluded.source,
                 fetched_at=excluded.fetched_at""",
            rows,
        )
    return len(rows)


def latest() -> dict[tuple[str, str], sqlite3.Row]:
    """Newest observation per (kind, key)."""
    with connect() as conn:
        cur = conn.execute(
            """SELECT o.* FROM observation o
               JOIN (SELECT kind,key,MAX(as_of) AS as_of FROM observation
                     GROUP BY kind,key) m
                 ON o.kind=m.kind AND o.key=m.key AND o.as_of=m.as_of"""
        )
        return {(r["kind"], r["key"]): r for r in cur.fetchall()}


# --- documents -------------------------------------------------------------

def write_documents(rows: Iterable[dict]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    with connect() as conn:
        conn.executemany(
            """INSERT INTO document
                 (doc_type,ref_key,as_of,section,category,tags,title,body,created_at)
               VALUES (:doc_type,:ref_key,:as_of,:section,:category,:tags,:title,:body,
                       :created_at)
               ON CONFLICT(doc_type,ref_key,as_of) DO UPDATE SET
                 tags=excluded.tags, title=excluded.title, body=excluded.body,
                 created_at=excluded.created_at""",
            rows,
        )
    return len(rows)


def search_documents(section: str | None = None, tags: list[str] | None = None,
                     since: str | None = None, limit: int = 200,
                     latest_only: bool = True) -> list[sqlite3.Row]:
    """Retrieval by metadata. Embeddings can rank within this later; filtering
    on tag and date first keeps that candidate set small and on-topic.

    `latest_only` returns the newest document per instrument rather than
    everything in a window. That matters because cadences differ wildly: a
    price is hours old, CPI is six weeks old and still current. A plain date
    window silently drops every macro series and reports "no data" for a
    section that is fully populated.
    """
    base = "document"
    if latest_only:
        base = """(SELECT d.* FROM document d
                   JOIN (SELECT doc_type, ref_key, MAX(as_of) AS as_of
                         FROM document GROUP BY doc_type, ref_key) m
                     ON d.doc_type=m.doc_type AND d.ref_key=m.ref_key
                    AND d.as_of=m.as_of)"""
    sql = [f"SELECT * FROM {base} WHERE 1=1"]
    args: list = []
    if section and section not in ("home", "all"):
        sql.append("AND section = ?")
        args.append(section)
    for t in tags or []:
        sql.append("AND (' ' || tags || ' ') LIKE ?")
        args.append(f"% {t} %")
    if since:
        sql.append("AND as_of >= ?")
        args.append(since)
    sql.append("ORDER BY as_of DESC, section, ref_key LIMIT ?")
    args.append(limit)
    with connect() as conn:
        return conn.execute(" ".join(sql), args).fetchall()


# --- runs ------------------------------------------------------------------

def start_run(section: str, source: str, started_at: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO ingest_run (section,source,started_at,status) VALUES (?,?,?,'running')",
            (section, source, started_at))
        return int(cur.lastrowid)


def finish_run(run_id: int, finished_at: str, status: str, rows: int,
               error: str | None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE ingest_run SET finished_at=?,status=?,rows=?,error=? WHERE id=?",
            (finished_at, status, rows, error, run_id))


def last_refresh() -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT MAX(finished_at) AS t FROM ingest_run WHERE status != 'error'"
        ).fetchone()
        return row["t"] if row and row["t"] else None
