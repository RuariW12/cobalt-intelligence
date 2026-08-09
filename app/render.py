"""Fills catalog rows with whatever the ETL has stored.

The catalog says what a page shows; this attaches the current numbers. A row
with no observation keeps its `placeholder` class and its em dashes, so an
un-ingested page looks deliberately empty rather than broken.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

from app import db
from app.catalog import PAGES

# Which stored field a table column wants. Anything unmapped (YTD, Mkt cap,
# Capex guide) stays an em dash until there is a source for it.
COLUMN_FIELD = {
    "price": "value", "level": "value",
    "change": "change", "24h": "change",
    "%": "pct",
}

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
    return DASH, None


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


def digest(section: str) -> str:
    """Plain-text view of a section's current data, for the model."""
    latest = db.latest()
    lines: list[str] = []
    for slug, page in PAGES.items():
        if page["section"] != section and section not in ("home", "all"):
            continue
        rows_out: list[str] = []
        for panel in page["panels"]:
            for row in panel.get("rows", []):
                key = (("symbol", row["symbol"]) if row.get("symbol")
                       else ("series", row["series"]) if row.get("series")
                       else ("derived", row["derived"]) if row.get("derived")
                       else None)
                obs = latest.get(key) if key else None
                if not obs:
                    continue
                bits = [f"{row['name']}: {_num(obs['value'])}"]
                if obs["change"] is not None:
                    bits.append(f"change {obs['change']:+,.2f}")
                if obs["pct"] is not None:
                    bits.append(f"({obs['pct']:+.2f}%)")
                if row.get("unit"):
                    bits.append(f"[{row['unit']}]")
                rows_out.append("  " + " ".join(bits))
        if rows_out:
            lines.append(f"{page['h1']}:")
            lines.extend(rows_out)
    return "\n".join(lines) if lines else "(no data has been ingested yet)"
