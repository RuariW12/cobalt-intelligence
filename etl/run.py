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
from datetime import datetime, timezone

from app.catalog import PAGES, SECTIONS
from etl.sources import fred, yahoo
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
    symbols, series = targets(section)

    result = {"section": section, "written": 0, "documents": 0, "failed": [], "sources": {}}

    if symbols:
        run_id = db.start_run(section, "yahoo", now)
        rows, failed = yahoo.fetch(symbols)
        written, suspect, docs = store_rows(rows, insts)
        db.finish_run(run_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "ok" if not failed else "partial", written,
                      f"{len(failed)} failed" if failed else None)
        result["written"] += written
        result["documents"] += docs
        result["failed"] += failed
        result["sources"]["yahoo"] = {"requested": len(symbols), "written": written,
                                      "failed": len(failed), "suspect": suspect}

    if series:
        if not fred.available():
            result["sources"]["fred"] = {"requested": len(series), "written": 0,
                                         "skipped": "FRED_API_KEY not set"}
        else:
            run_id = db.start_run(section, "fred", now)
            rows, failed = fred.fetch(series)
            written, suspect, docs = store_rows(rows, insts)
            db.finish_run(run_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "ok" if not failed else "partial", written,
                          f"{len(failed)} failed" if failed else None)
            result["written"] += written
            result["documents"] += docs
            result["failed"] += failed
            result["sources"]["fred"] = {"requested": len(series), "written": written,
                                         "failed": len(failed), "suspect": suspect}

    derived = compute_derived()
    if derived:
        written, _, docs = store_rows(derived, insts)
        result["written"] += written
        result["documents"] += docs
        result["sources"]["derived"] = {"written": written}

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="etl.run", description="Cobalt ingest")
    parser.add_argument("--section", default="all", choices=["all", *SECTIONS])
    args = parser.parse_args(argv)

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
