"""Populate `instrument` from the catalog.

The catalog already knows every row's name, unit, section and panel; the store
needs that to describe an observation in a sentence. Syncing rather than
duplicating keeps one source of truth — change the catalog and the store's
descriptions follow on the next ingest.
"""

from __future__ import annotations

from app.catalog import PAGES
from etl.sources.fred import display_unit
from store import clean, db, tags as tagging

SOURCE_OF = {"symbol": "yahoo", "series": "fred", "derived": "derived"}


def instruments_from_catalog() -> list[dict]:
    out: dict[str, dict] = {}
    for slug, page in PAGES.items():
        for panel in page["panels"]:
            category = panel.get("heading")
            for row in panel.get("rows", []):
                if row.get("symbol"):
                    key, kind = row["symbol"], "symbol"
                elif row.get("series"):
                    key, kind = row["series"], "series"
                elif row.get("derived"):
                    key, kind = row["derived"], "derived"
                else:
                    continue
                section = page["section"]
                out[key] = {
                    "key": key,
                    "kind": kind,
                    "name": clean.clean_unit(row["name"]) or row["name"],
                    "ticker": row.get("ticker"),
                    # For FRED series the transform decides the unit, not the
                    # catalog: "% y/y" is only true because we asked for pc1.
                    "unit": (display_unit(key) if kind == "series"
                             else clean.clean_unit(row.get("unit"))),
                    "period": clean.clean_unit(row.get("period")),
                    "section": section,
                    "category": tagging.slug(category) if category else None,
                    "page": slug,
                    "asset_class": tagging.asset_class(key, kind, section),
                    "source": SOURCE_OF.get(kind, "unknown"),
                }
    return list(out.values())


def sync() -> int:
    rows = instruments_from_catalog()
    db.upsert_instruments(rows)
    for r in rows:
        db.replace_tags(r["key"], tagging.for_instrument(
            r["key"], r["kind"], r["section"], r["category"]))
    return len(rows)
