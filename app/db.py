"""SQLite access, shared by the web service (reads) and the ETL (writes).

One file, no server. `observation` is append-only keyed by timestamp so
revisions stay visible — macro series get revised, and overwriting would hide
that. Reads take the newest row per key.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

DB_PATH = Path(os.environ.get("COBALT_DB", "/data/cobalt.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS observation (
    kind        TEXT NOT NULL,          -- 'symbol' | 'series' | 'derived'
    key         TEXT NOT NULL,          -- 'GC=F', 'CPIAUCSL', 'gold-silver-ratio'
    ts          TEXT NOT NULL,          -- ISO8601 of the observation itself
    value       REAL,
    previous    REAL,
    change      REAL,
    pct         REAL,
    currency    TEXT,
    source      TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (kind, key, ts)
);

CREATE INDEX IF NOT EXISTS observation_recent ON observation (kind, key, ts DESC);

CREATE TABLE IF NOT EXISTS ingest_run (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    section     TEXT NOT NULL,
    source      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,          -- 'ok' | 'partial' | 'error'
    rows        INTEGER DEFAULT 0,
    error       TEXT
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    # WAL lets the web service read while an ingest is writing.
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def write_observations(rows: Iterable[dict]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    with connect() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO observation
               (kind, key, ts, value, previous, change, pct, currency, source, fetched_at)
               VALUES (:kind, :key, :ts, :value, :previous, :change, :pct, :currency,
                       :source, :fetched_at)""",
            rows,
        )
    return len(rows)


def latest() -> dict[tuple[str, str], sqlite3.Row]:
    """Newest observation per (kind, key), as a lookup for the renderer."""
    with connect() as conn:
        cur = conn.execute(
            """SELECT o.* FROM observation o
               JOIN (SELECT kind, key, MAX(ts) AS ts FROM observation GROUP BY kind, key) m
                 ON o.kind = m.kind AND o.key = m.key AND o.ts = m.ts"""
        )
        return {(r["kind"], r["key"]): r for r in cur.fetchall()}


def last_refresh() -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT MAX(finished_at) AS t FROM ingest_run WHERE status != 'error'"
        ).fetchone()
        return row["t"] if row and row["t"] else None


def start_run(section: str, source: str, started_at: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO ingest_run (section, source, started_at, status) VALUES (?,?,?,'running')",
            (section, source, started_at),
        )
        return int(cur.lastrowid)


def finish_run(run_id: int, finished_at: str, status: str, rows: int, error: str | None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE ingest_run SET finished_at=?, status=?, rows=?, error=? WHERE id=?",
            (finished_at, status, rows, error, run_id),
        )
