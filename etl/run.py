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

from app import db
from app.catalog import PAGES, SECTIONS
from etl.sources import fred, yahoo

# Series computed from other observations rather than fetched.
DERIVED = {
    "gold-silver-ratio": ("GC=F", "SI=F", lambda a, b: a / b if b else None),
    "brent-wti-spread": ("BZ=F", "CL=F", lambda a, b: a - b),
}


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
    return sorted(set(symbols)), sorted(set(series))


def compute_derived(now: str) -> list[dict]:
    latest = db.latest()
    out = []
    for name, (a_key, b_key, fn) in DERIVED.items():
        a, b = latest.get(("symbol", a_key)), latest.get(("symbol", b_key))
        if not a or not b:
            continue
        try:
            value = fn(a["value"], b["value"])
        except Exception:
            continue
        if value is None:
            continue
        out.append({
            "kind": "derived", "key": name, "ts": now, "value": value,
            "previous": None, "change": None, "pct": None, "currency": None,
            "source": "derived", "fetched_at": now,
        })
    return out


def ingest(section: str = "all") -> dict:
    db.init()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    symbols, series = targets(section)

    result = {"section": section, "written": 0, "failed": [], "sources": {}}

    if symbols:
        run_id = db.start_run(section, "yahoo", now)
        rows, failed = yahoo.fetch(symbols)
        written = db.write_observations(rows)
        db.finish_run(run_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "ok" if not failed else "partial", written,
                      f"{len(failed)} failed" if failed else None)
        result["written"] += written
        result["failed"] += failed
        result["sources"]["yahoo"] = {"requested": len(symbols), "written": written,
                                      "failed": len(failed)}

    if series:
        if not fred.available():
            result["sources"]["fred"] = {"requested": len(series), "written": 0,
                                         "skipped": "FRED_API_KEY not set"}
        else:
            run_id = db.start_run(section, "fred", now)
            rows, failed = fred.fetch(series)
            written = db.write_observations(rows)
            db.finish_run(run_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "ok" if not failed else "partial", written,
                          f"{len(failed)} failed" if failed else None)
            result["written"] += written
            result["failed"] += failed
            result["sources"]["fred"] = {"requested": len(series), "written": written,
                                         "failed": len(failed)}

    derived = compute_derived(datetime.now(timezone.utc).isoformat(timespec="seconds"))
    if derived:
        result["written"] += db.write_observations(derived)
        result["sources"]["derived"] = {"written": len(derived)}

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="etl.run", description="Cobalt ingest")
    parser.add_argument("--section", default="all", choices=["all", *SECTIONS])
    args = parser.parse_args(argv)

    r = ingest(args.section)
    print(f"section={r['section']} written={r['written']}")
    for name, info in r["sources"].items():
        print(f"  {name}: {info}")
    if r["failed"]:
        print(f"  failed: {', '.join(r['failed'][:12])}"
              f"{' ...' if len(r['failed']) > 12 else ''}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
