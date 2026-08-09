"""ETL entrypoint.

Walks app/catalog.py to learn what a section needs, fetches it, and writes
observations. Because the catalog also drives rendering, a page and its ingest
cannot drift apart.

    python -m etl.run --section commodities
    python -m etl.run --section all
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

from app.catalog import PAGES, SECTIONS
from etl.sources import fred, news, yahoo
from store import clean, db, documents
from store import tags as tagging
from store.catalog_sync import sync as sync_instruments

# Series computed from other observations rather than fetched.
#
# Each entry names its inputs and how to combine them. `field` selects which
# part of the input observation to use: "value" for a price, "ytd_pct" for a
# year-to-date spread.
DERIVED: dict[str, dict] = {
    "gold-silver-ratio": {
        "inputs": ("GC=F", "SI=F"), "field": "value",
        "fn": lambda a, b: (a / b) if b else None,
    },
    "brent-wti-spread": {
        "inputs": ("BZ=F", "CL=F"), "field": "value",
        "fn": lambda a, b: a - b,
    },
    "qqq-iwm-ytd": {
        "inputs": ("QQQ", "IWM"), "field": "ytd_pct",
        "fn": lambda a, b: a - b,
    },
    "spy-rsp-ytd": {
        "inputs": ("SPY", "RSP"), "field": "ytd_pct",
        "fn": lambda a, b: a - b,
    },
}

# Fetched only to feed a derived series — they appear on no page. SPY and RSP
# are the cap-weighted and equal-weighted S&P; their YTD gap is the
# concentration measure the AI-bubble page is built around.
EXTRA_INPUTS = ("SPY", "RSP")

# Declared in the catalog but deliberately not computed:
#   nvda-sp500-weight, sp500-top10-weight  need index constituent weights.
#     The iShares holdings CSV now returns a consent page rather than a file,
#     so there is no free source wired up. Left empty rather than approximated.
#   ndx-trailing-pe  needs per-constituent earnings; forward P/E is licensed.
UNIMPLEMENTED = ("nvda-sp500-weight", "sp500-top10-weight", "ndx-trailing-pe")


def targets(section: str) -> tuple[list[str], list[str]]:
    """(yahoo symbols, fred series) needed by a section, or all of them."""
    symbols: list[str] = []
    series: list[str] = []
    for page in PAGES.values():
        if section not in ("all", "home") and page["section"] != section:
            continue
        for panel in page["panels"]:
            for row in panel.get("rows", []):
                if row.get("symbol"):
                    symbols.append(row["symbol"])
                if row.get("series"):
                    series.append(row["series"])
    # Inputs that feed derived series but appear on no page.
    if section in ("all", "home", "etfs", "ai-bubble"):
        symbols.extend(EXTRA_INPUTS)
    return sorted(set(symbols)), sorted(set(series))


def compute_derived() -> list[dict]:
    """Build derived observations from what is already stored.

    Dating matters: a derived value belongs to the day of its inputs, not to
    the moment it was computed. Stamping it with "now" made the gold/silver
    ratio appear a day newer than the gold and silver it comes from.
    """
    latest = db.latest()
    out = []
    for name, spec in DERIVED.items():
        a_key, b_key = spec["inputs"]
        a, b = latest.get(("symbol", a_key)), latest.get(("symbol", b_key))
        if not a or not b:
            continue

        field = spec["field"]
        try:
            value = spec["fn"](a[field], b[field])
        except (TypeError, KeyError, ZeroDivisionError):
            continue
        if value is None:
            continue

        # The same function over the inputs' own previous values gives a real
        # change, without needing stored history.
        previous = None
        if field == "value" and a["previous"] is not None and b["previous"] is not None:
            try:
                previous = spec["fn"](a["previous"], b["previous"])
            except (TypeError, ZeroDivisionError):
                previous = None

        as_of = min(a["as_of"], b["as_of"])
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out.append({
            "kind": "derived", "key": name, "ts": as_of, "value": value,
            "previous": previous, "change": None, "pct": None, "ytd_pct": None,
            "currency": None, "source": "derived", "fetched_at": now,
        })
    return out


def store_rows(raw: list[dict], insts: dict) -> tuple[int, int, int]:
    """Clean, persist, and turn into retrievable documents.

    Returns (written, suspect, documents). Cleaning happens here rather than in
    each source so every source gets the same guarantees.
    """
    cleaned, docs = [], []
    suspect = 0
    for row in raw:
        inst = insts.get(row["key"])
        obs = clean.observation(row, inst["asset_class"] if inst else "")
        if obs is None:
            continue
        if obs["quality"] == "suspect":
            suspect += 1
        cleaned.append(obs)
        if inst:
            docs.append(documents.build(dict(inst), obs, db.tags_for(row["key"])))

    written = db.write_observations(cleaned)
    db.write_documents(docs)
    return written, suspect, len(docs)


def ingest(section: str = "all") -> dict:
    db.init()
    sync_instruments()
    insts = db.instruments()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    symbols, series_ids = targets(section)

    result = {"section": section, "written": 0, "documents": 0, "failed": [], "sources": {}}

    if symbols:
        run_id = db.start_run(section, "yahoo", now)
        rows, failed, history = yahoo.fetch(symbols)
        # The quote response already contains the year's closes; storing them
        # makes the charts free rather than a second round of requests.
        for sym, points in history.items():
            db.write_history(sym, points)
        written, suspect, docs = store_rows(rows, insts)
        db.finish_run(run_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "ok" if not failed else "partial", written,
                      f"{len(failed)} failed" if failed else None)
        result["written"] += written
        result["documents"] += docs
        result["failed"] += failed
        result["sources"]["yahoo"] = {"requested": len(symbols), "written": written,
                                      "failed": len(failed), "suspect": suspect}

    if series_ids:
        if not fred.available():
            result["sources"]["fred"] = {"requested": len(series_ids), "written": 0,
                                         "skipped": "FRED_API_KEY not set"}
        else:
            run_id = db.start_run(section, "fred", now)
            rows, failed = fred.fetch(series_ids)
            written, suspect, docs = store_rows(rows, insts)
            db.finish_run(run_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "ok" if not failed else "partial", written,
                          f"{len(failed)} failed" if failed else None)
            result["written"] += written
            result["documents"] += docs
            result["failed"] += failed
            result["sources"]["fred"] = {"requested": len(series_ids), "written": written,
                                         "failed": len(failed), "suspect": suspect}

    # News is section-independent: one sweep of the feeds serves every page,
    # and the URL unique constraint means re-running is cheap and idempotent.
    if section in ("all", "home", "news") or True:
        run_id = db.start_run(section, "news", now)
        try:
            items, failed_feeds = news.fetch()
            matchers = tagging.build_matchers(insts)
            seen: set[str] = set()
            tagged = []
            for a in items:
                if a["url"] in seen:
                    continue
                seen.add(a["url"])
                a["tags"] = tagging.for_article(a["title"], matchers)
                tagged.append(a)
            new = db.write_articles(tagged)
            db.write_documents([documents.article(a) for a in tagged])
            db.finish_run(run_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "ok" if not failed_feeds else "partial", new,
                          ", ".join(failed_feeds) or None)
            result["sources"]["news"] = {
                "fetched": len(items), "new": new,
                "tagged": sum(1 for a in tagged if a["tags"]),
                "failed_feeds": failed_feeds,
            }
        except Exception as exc:
            db.finish_run(run_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "error", 0, str(exc))
            result["sources"]["news"] = {"error": str(exc)}

    derived = compute_derived()
    if derived:
        written, _, docs = store_rows(derived, insts)
        result["written"] += written
        result["documents"] += docs
        result["sources"]["derived"] = {"written": written}

    return result


def backfill_prices(rng: str = "10y") -> dict:
    """Pull a long price history for every tracked symbol.

    Charts backfill on demand, so depth ends up uneven — ten years for whatever
    you happened to open, one year for the rest. The archive should not have
    that shape, so this levels it in one pass.
    """
    db.init()
    symbols, _ = targets("all")
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_id = db.start_run("all", "yahoo-backfill", started)

    written, failed = 0, []
    for symbol in symbols:
        try:
            points = yahoo.series(symbol, rng, "1d")
            written += db.write_history(symbol, points)
        except Exception:
            failed.append(symbol)
        time.sleep(yahoo.PAUSE_SECONDS)

    db.finish_run(run_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "ok" if not failed else "partial", written,
                  ", ".join(failed) or None)
    return {"symbols": len(symbols), "written": written, "failed": failed}


def backfill(since: str | None = None) -> dict:
    """Load every FRED series to inception.

    Run once. The daily ingest deliberately asks for only the last two values
    of each series, which is all the dashboard renders — but it means the
    archive starts empty. This fills in the past so there is something to look
    back at, and so a chart of CPI covers more than a fortnight.

    Observations only: writing a document per historical point would add tens
    of thousands of rows to the model's retrieval surface, all of them stale by
    definition. The latest value of each series already has its document.
    """
    db.init()
    sync_instruments()
    insts = db.instruments()

    _, series_ids = targets("all")
    if not fred.available():
        return {"error": "FRED_API_KEY not set"}

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_id = db.start_run("all", "fred-backfill", started)

    rows, failed = fred.history(series_ids, since=since)
    cleaned = []
    for row in rows:
        inst = insts.get(row["key"])
        obs = clean.observation(row, inst["asset_class"] if inst else "")
        if obs:
            cleaned.append(obs)
    written = db.write_observations(cleaned)

    db.finish_run(run_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "ok" if not failed else "partial", written,
                  ", ".join(failed) or None)

    by_series = {}
    for o in cleaned:
        by_series[o["key"]] = by_series.get(o["key"], 0) + 1
    return {"series": len(series_ids), "written": written,
            "failed": failed, "per_series": by_series}


def retag() -> int:
    """Re-apply the tag vocabulary to every stored headline.

    Tagging happens at ingest, so widening the keyword patterns would otherwise
    only affect articles fetched afterwards — leaving a corpus half-tagged
    under two different vocabularies.
    """
    db.init()
    sync_instruments()
    matchers = tagging.build_matchers(db.instruments())
    n = 0
    with db.connect() as conn:
        rows = conn.execute("SELECT id, title FROM article").fetchall()
        for r in rows:
            tags = tagging.for_article(r["title"], matchers)
            conn.execute("DELETE FROM article_tag WHERE article_id=?", (r["id"],))
            if tags:
                conn.executemany(
                    "INSERT OR IGNORE INTO article_tag (article_id, tag) VALUES (?,?)",
                    [(r["id"], t) for t in tags])
                n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="etl.run", description="Cobalt ingest")
    parser.add_argument("--section", default="all", choices=["all", *SECTIONS])
    parser.add_argument("--retag", action="store_true",
                        help="re-apply tags to stored headlines and exit")
    parser.add_argument("--backfill", action="store_true",
                        help="load every FRED series to inception and exit")
    parser.add_argument("--since", metavar="YYYY-MM-DD",
                        help="with --backfill, do not go back further than this")
    args = parser.parse_args(argv)

    if args.retag:
        print(f"re-tagged {retag()} headlines")
        return 0

    if args.backfill:
        p = backfill_prices()
        print(f"backfilled {p['written']} daily closes across {p['symbols']} symbols"
              + (f" ({len(p['failed'])} failed)" if p["failed"] else ""))
        r = backfill(args.since)
        if "error" in r:
            print(r["error"], file=sys.stderr)
            return 1
        print(f"backfilled {r['written']} observations across {r['series']} series")
        for key, n in sorted(r["per_series"].items(), key=lambda kv: -kv[1]):
            print(f"  {key:16} {n}")
        if r["failed"]:
            print("  failed:", ", ".join(r["failed"]), file=sys.stderr)
        return 0

    r = ingest(args.section)
    print(f"section={r['section']} written={r['written']} documents={r['documents']}")
    for name, info in r["sources"].items():
        print(f"  {name}: {info}")
    if r["failed"]:
        print(f"  failed: {', '.join(r['failed'][:12])}"
              f"{' ...' if len(r['failed']) > 12 else ''}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
