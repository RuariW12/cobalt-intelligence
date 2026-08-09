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


def write_history(key: str, points: list[tuple[str, float]]) -> int:
    if not points:
        return 0
    with connect() as conn:
        conn.executemany(
            "INSERT INTO history (key, as_of, close) VALUES (?,?,?) "
            "ON CONFLICT(key, as_of) DO UPDATE SET close=excluded.close",
            [(key, d, c) for d, c in points])
    return len(points)


def history(key: str, since: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT as_of, close FROM history WHERE key = ?"
    args: list = [key]
    if since:
        sql += " AND as_of >= ?"
        args.append(since)
    sql += " ORDER BY as_of"
    with connect() as conn:
        return conn.execute(sql, args).fetchall()


def history_start(key: str) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT MIN(as_of) AS d FROM history WHERE key=?", (key,)).fetchone()
        return row["d"] if row and row["d"] else None


# --- articles --------------------------------------------------------------

def write_articles(rows: Iterable[dict]) -> int:
    """Insert headlines, ignoring ones already stored under the same URL."""
    rows = list(rows)
    if not rows:
        return 0
    written = 0
    with connect() as conn:
        for r in rows:
            cur = conn.execute(
                """INSERT INTO article (url,title,publisher,section,published_at,fetched_at)
                   VALUES (:url,:title,:publisher,:section,:published_at,:fetched_at)
                   ON CONFLICT(url) DO NOTHING""", r)
            if cur.rowcount:
                written += 1
            row = conn.execute("SELECT id FROM article WHERE url=?", (r["url"],)).fetchone()
            if row and r.get("tags"):
                conn.executemany(
                    "INSERT OR IGNORE INTO article_tag (article_id, tag) VALUES (?,?)",
                    [(row["id"], t) for t in r["tags"]])
    return written


def articles(section: str | None = None, tags: list[str] | None = None,
             limit: int = 12) -> list[sqlite3.Row]:
    """Newest headlines, by section or by anything they mention."""
    sql = ["SELECT DISTINCT a.* FROM article a"]
    args: list = []
    if tags:
        sql.append("JOIN article_tag t ON t.article_id = a.id")
    sql.append("WHERE 1=1")
    if section:
        sql.append("AND a.section = ?")
        args.append(section)
    if tags:
        sql.append("AND t.tag IN (%s)" % ",".join("?" * len(tags)))
        args.extend(tags)
    sql.append("ORDER BY COALESCE(a.published_at, a.fetched_at) DESC LIMIT ?")
    args.append(limit)
    with connect() as conn:
        return conn.execute(" ".join(sql), args).fetchall()



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
                 section=excluded.section, category=excluded.category,
                 tags=excluded.tags, title=excluded.title, body=excluded.body,
                 created_at=excluded.created_at""",
            rows,
        )
    return len(rows)


def search_documents(section: str | None = None, tags: list[str] | None = None,
                     since: str | None = None, limit: int = 200,
                     latest_only: bool = True, doc_type: str | None = None,
                     any_tags: list[str] | None = None) -> list[sqlite3.Row]:
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
    for t in tags or []:                       # every tag must be present
        sql.append("AND (' ' || tags || ' ') LIKE ?")
        args.append(f"% {t} %")
    if any_tags:                               # at least one must be present
        sql.append("AND (" + " OR ".join("(' ' || tags || ' ') LIKE ?" for _ in any_tags) + ")")
        args.extend(f"% {t} %" for t in any_tags)
    if doc_type:
        sql.append("AND doc_type = ?")
        args.append(doc_type)
    if since:
        sql.append("AND as_of >= ?")
        args.append(since)
    sql.append("ORDER BY as_of DESC, section, ref_key LIMIT ?")
    args.append(limit)
    with connect() as conn:
        return conn.execute(" ".join(sql), args).fetchall()


# --- archive ---------------------------------------------------------------

def sections_with_instruments() -> dict[str, list[dict]]:
    """Everything tracked, grouped the way the site is, with entry counts.

    The count matters: a row with no data looks identical to one with ten years
    of it until you click. Two aggregates beat one query per instrument.
    """
    with connect() as conn:
        counts: dict[str, int] = {}
        for table in ("observation", "history"):
            for r in conn.execute(f"SELECT key, COUNT(*) n FROM {table} GROUP BY key"):
                counts[r["key"]] = counts.get(r["key"], 0) + r["n"]
        out: dict[str, list[dict]] = {}
        for r in conn.execute("SELECT * FROM instrument ORDER BY section, name"):
            row = dict(r)
            row["entries"] = counts.get(r["key"], 0)
            out.setdefault(r["section"], []).append(row)
    return out


def entries(key: str, kind: str, limit: int = 100, offset: int = 0
            ) -> tuple[list[dict], int]:
    """Historical rows for one instrument, newest first, with a total count.

    Prices and economic series live in different tables — `history` holds daily
    closes, `observation` holds dated readings with their own change. This
    hides that split so the archive can show one kind of row.
    """
    with connect() as conn:
        if kind == "symbol":
            total = conn.execute("SELECT COUNT(*) FROM history WHERE key=?",
                                 (key,)).fetchone()[0]
            rows = conn.execute(
                """SELECT as_of, value, value - prev AS change,
                          CASE WHEN prev > 0 THEN (value - prev) / prev * 100 END AS pct
                   FROM (SELECT as_of, close AS value,
                                LAG(close) OVER (ORDER BY as_of) AS prev
                         FROM history WHERE key = ?)
                   ORDER BY as_of DESC LIMIT ? OFFSET ?""",
                (key, limit, offset)).fetchall()
        else:
            total = conn.execute("SELECT COUNT(*) FROM observation WHERE key=?",
                                 (key,)).fetchone()[0]
            rows = conn.execute(
                """SELECT as_of, value, change, pct FROM observation
                   WHERE key = ? ORDER BY as_of DESC LIMIT ? OFFSET ?""",
                (key, limit, offset)).fetchall()
    return [dict(r) for r in rows], total


def find_instruments(q: str, limit: int = 40) -> list[sqlite3.Row]:
    """Match on name, ticker, key or any tag."""
    like = f"%{q.lower()}%"
    with connect() as conn:
        return conn.execute(
            """SELECT DISTINCT i.* FROM instrument i
               LEFT JOIN tag t ON t.key = i.key
               WHERE lower(i.name) LIKE ? OR lower(i.key) LIKE ?
                  OR lower(COALESCE(i.ticker,'')) LIKE ? OR lower(t.tag) LIKE ?
               ORDER BY i.section, i.name LIMIT ?""",
            (like, like, like, like, limit)).fetchall()


def find_articles(q: str | None = None, key: str | None = None,
                  limit: int = 50, offset: int = 0) -> tuple[list[sqlite3.Row], int]:
    """Headlines by free text, or everything tagged with one instrument."""
    where, args = ["1=1"], []
    join = ""
    if key:
        join = "JOIN article_tag t ON t.article_id = a.id"
        where.append("t.tag = ?")
        args.append(key)
    if q:
        where.append("lower(a.title) LIKE ?")
        args.append(f"%{q.lower()}%")
    clause = " AND ".join(where)
    with connect() as conn:
        total = conn.execute(
            f"SELECT COUNT(DISTINCT a.id) FROM article a {join} WHERE {clause}",
            args).fetchone()[0]
        rows = conn.execute(
            f"""SELECT DISTINCT a.* FROM article a {join} WHERE {clause}
                ORDER BY COALESCE(a.published_at, a.fetched_at) DESC
                LIMIT ? OFFSET ?""", [*args, limit, offset]).fetchall()
    return rows, total


def store_stats() -> dict:
    with connect() as conn:
        def one(sql, *a):
            return conn.execute(sql, a).fetchone()[0]
        return {
            "instruments": one("SELECT COUNT(*) FROM instrument"),
            "observations": one("SELECT COUNT(*) FROM observation"),
            "closes": one("SELECT COUNT(*) FROM history"),
            "articles": one("SELECT COUNT(*) FROM article"),
            "earliest": one("SELECT MIN(d) FROM (SELECT MIN(as_of) d FROM observation "
                            "UNION SELECT MIN(as_of) FROM history)"),
            "last_run": one("SELECT MAX(finished_at) FROM ingest_run"),
        }


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
