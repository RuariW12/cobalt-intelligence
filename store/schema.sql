-- Cobalt's central store.
--
-- Three layers, deliberately separate:
--   instrument   what we track, and how to describe it     (from the catalog)
--   observation  the numbers, append-only by date          (from the sources)
--   document     one dated, tagged sentence per fact       (what the model reads)
--
-- The document layer exists so retrieval never has to interpret a table. Each
-- row is a self-contained natural-language statement carrying its own date and
-- tags, which is the shape RAG wants: filter by tag and date, embed the body,
-- feed back whole rows.

CREATE TABLE IF NOT EXISTS instrument (
    key         TEXT PRIMARY KEY,       -- 'GC=F', 'CPIAUCSL', 'gold-silver-ratio'
    kind        TEXT NOT NULL,          -- symbol | series | derived
    name        TEXT NOT NULL,          -- 'Gold'
    ticker      TEXT,
    unit        TEXT,                   -- 'USD / troy oz'
    period      TEXT,                   -- 'year over year'
    section     TEXT NOT NULL,          -- 'commodities'
    category    TEXT,                   -- 'precious'  (the panel it sits in)
    page        TEXT NOT NULL,          -- catalog slug
    asset_class TEXT,                   -- future | index | equity | etf | crypto | indicator
    source      TEXT                    -- yahoo | fred | derived
);

CREATE TABLE IF NOT EXISTS observation (
    kind        TEXT NOT NULL,
    key         TEXT NOT NULL,
    as_of       TEXT NOT NULL,          -- DATE, the observation's own day
    ts          TEXT,                   -- full timestamp when the source gave one
    value       REAL NOT NULL,
    previous    REAL,
    change      REAL,
    pct         REAL,
    ytd_pct     REAL,          -- % change since the first close of the year
    currency    TEXT,
    quality     TEXT NOT NULL DEFAULT 'ok',   -- ok | suspect
    source      TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (kind, key, as_of)
);

CREATE INDEX IF NOT EXISTS observation_recent ON observation (kind, key, as_of DESC);

CREATE TABLE IF NOT EXISTS tag (
    key         TEXT NOT NULL,
    tag         TEXT NOT NULL,
    PRIMARY KEY (key, tag)
);

CREATE INDEX IF NOT EXISTS tag_by_tag ON tag (tag);

-- The retrieval surface. `body` is a complete sentence; `tags` is a
-- space-delimited string so a LIKE filter works without a join.
CREATE TABLE IF NOT EXISTS document (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type    TEXT NOT NULL,          -- observation | article | summary
    ref_key     TEXT,
    as_of       TEXT NOT NULL,          -- DATE, for time-scoped retrieval
    section     TEXT,
    category    TEXT,
    tags        TEXT NOT NULL,
    title       TEXT,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (doc_type, ref_key, as_of)
);

CREATE INDEX IF NOT EXISTS document_lookup ON document (section, as_of DESC);
CREATE INDEX IF NOT EXISTS document_date ON document (as_of DESC);

CREATE TABLE IF NOT EXISTS ingest_run (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    section     TEXT NOT NULL,
    source      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,
    rows        INTEGER DEFAULT 0,
    error       TEXT
);
