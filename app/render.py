"""Fills catalog rows with whatever the ETL has stored.

The catalog says what a page shows; this attaches the current numbers. A row
with no observation keeps its `placeholder` class and its em dashes, so an
un-ingested page looks deliberately empty rather than broken.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

from store import db
from app.catalog import PAGES

# Which stored field a table column wants. Anything unmapped (YTD, Mkt cap,
# Capex guide) stays an em dash until there is a source for it.
COLUMN_FIELD = {
    "price": "value", "level": "value",
    "change": "change", "24h": "change",
    "%": "pct",
    "ytd": "ytd_pct",
}

# How old a reading may be before the page says so. A price that stopped
# updating still renders, and without a marker yesterday's number reads as
# today's — worse than a gap. Macro releases are monthly by nature, so they
# get a far longer leash.
STALE_AFTER_DAYS = {"symbol": 4, "derived": 4, "series": 70}

DASH = "&mdash;"


def _num(v: float, currency: str | None = None) -> str:
    if v is None:
        return DASH
    a = abs(v)
    digits = 0 if a >= 10000 else (2 if a >= 1 else 4)
    return f"{v:,.{digits}f}"


def _signed(v: float | None, suffix: str = "") -> tuple[str, str | None]:
    if v is None:
        return DASH, None
    a = abs(v)
    digits = 0 if a >= 10000 else 2
    return f"{v:+,.{digits}f}{suffix}", ("up" if v > 0 else "down" if v < 0 else None)


def _cell(field: str, obs) -> tuple[str, str | None]:
    if obs is None:
        return DASH, None
    if field == "value":
        return _num(obs["value"], obs["currency"]), None
    if field == "change":
        return _signed(obs["change"])
    if field == "pct":
        return _signed(obs["pct"], "%")
    if field == "ytd_pct":
        return _signed(obs["ytd_pct"], "%")
    return DASH, None


def _age(obs) -> tuple[str | None, bool]:
    """(as_of, is_stale) for a stored observation."""
    if obs is None:
        return None, False
    try:
        age = (datetime.now(timezone.utc).date()
               - datetime.fromisoformat(obs["as_of"]).date()).days
    except (ValueError, TypeError):
        return obs["as_of"], False
    return obs["as_of"], age > STALE_AFTER_DAYS.get(obs["kind"], 4)


def build(slug: str) -> dict | None:
    page = PAGES.get(slug)
    if page is None:
        return None

    page = copy.deepcopy(page)
    latest = db.latest()
    stamp = db.last_refresh()
    page["refreshed"] = _humanise(stamp) if stamp else "never"

    for panel in page["panels"]:
        if panel["type"] == "quotes":
            for row in panel["rows"]:
                obs = latest.get(("symbol", row["symbol"])) if row.get("symbol") else None
                cells = []
                if row.get("ticker"):
                    cells.append({"text": row["ticker"], "cls": "ticker"})
                # columns[0] is the name, already rendered by the template
                for col in panel["columns"][1:]:
                    if row.get("ticker") and col.strip().lower() == "ticker":
                        continue
                    text, cls = _cell(COLUMN_FIELD.get(col.strip().lower(), ""), obs)
                    cells.append({"text": text, "cls": cls})
                row["cells"] = cells
                row["has_data"] = obs is not None
                row["as_of"], row["stale"] = _age(obs)

        elif panel["type"] == "metrics":
            for row in panel["rows"]:
                if row.get("series"):
                    obs = latest.get(("series", row["series"]))
                elif row.get("derived"):
                    obs = latest.get(("derived", row["derived"]))
                else:
                    obs = None
                row["value_text"] = _num(obs["value"]) if obs else DASH
                row["change_text"], row["change_cls"] = (
                    _signed(obs["change"]) if obs else (DASH, None))
                row["has_data"] = obs is not None
                row["as_of"], row["stale"] = _age(obs)

    return page


def _humanise(iso: str) -> str:
    try:
        t = datetime.fromisoformat(iso)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
    except ValueError:
        return iso
    delta = (datetime.now(timezone.utc) - t).total_seconds()
    if delta < 90:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)} min ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return t.strftime("%Y-%m-%d %H:%M UTC")


def digest(section: str, days: int = 400, limit: int = 120) -> str:
    """What the model reads: retrieved documents, not a re-derived table.

    Each document is already a dated, tagged sentence, so retrieval is a
    metadata filter rather than a formatting job — and the same rows will feed
    an embedding index later without being rebuilt.
    """
    # A wide floor, not a window: this only excludes series that have stopped
    # updating entirely. Recency per instrument is handled by latest_only.
    since = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    rows = db.search_documents(section=section, since=since, limit=limit,
                               latest_only=True)
    if not rows:
        return "(no data has been ingested yet)"

    by_section: dict[str, list[str]] = {}
    for r in rows:
        by_section.setdefault(r["section"] or "other", []).append(r["body"])

    out: list[str] = []
    for name, bodies in by_section.items():
        out.append(f"## {name}")
        out.extend(bodies)
        out.append("")
    return "\n".join(out).strip()
