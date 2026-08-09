"""Cleaning — everything a raw fetch must survive before it is stored.

Sources lie in mundane ways: nulls, stale weekend quotes, a percentage that
disagrees with its own change, a field that arrives as a string. Catching that
here means the rest of the system can assume observations are sane, and means
a bad number never reaches the model as though it were a fact.

Nothing is silently dropped. A row that fails a sanity check is kept and marked
`quality='suspect'`, because a suspicious number you can see beats a gap you
cannot explain.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone

# A day's move beyond this is almost certainly a data error rather than a
# market event — a split, a bad tick, or the wrong previous close. Crypto
# genuinely does move this much, so it is exempt.
IMPLAUSIBLE_DAILY_PCT = 25.0

# Only prices get a percent change and a plausibility check. For an indicator
# the value is often already a rate ("+0.08 % m/m"), so a percent change of a
# percent is meaningless — and small denominators make it explode, which
# flagged perfectly good payroll and production prints as suspect.
PRICE_LIKE = {"future", "index", "equity", "etf", "crypto"}
NEVER_SUSPECT = {"crypto"}


def _f(v) -> float | None:
    """Coerce to float, rejecting NaN/inf and unparseable strings."""
    if v is None or v == "" or v == ".":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _as_of(row: dict) -> str:
    """The observation's own date, not the time we fetched it.

    Everything downstream filters by date — RAG retrieval especially — so this
    has to be the day the number belongs to.
    """
    ts = row.get("ts")
    if ts:
        try:
            return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            m = re.match(r"(\d{4}-\d{2}-\d{2})", str(ts))
            if m:
                return m.group(1)
    return date.today().isoformat()


def observation(row: dict, asset_class: str = "") -> dict | None:
    """Normalise one fetched row. Returns None only if there is no usable value."""
    value = _f(row.get("value"))
    if value is None:
        return None

    previous = _f(row.get("previous"))
    change = _f(row.get("change"))
    pct = _f(row.get("pct"))

    # Derive rather than trust: a source's change and its own prices sometimes
    # disagree, and the prices are what we display.
    if previous is not None:
        change = value - previous
        if asset_class in PRICE_LIKE:
            pct = (change / previous * 100.0) if previous else None
        else:
            pct = None   # change is in the series' own units (points, thousands)

    quality = "ok"
    if (pct is not None and asset_class in PRICE_LIKE
            and asset_class not in NEVER_SUSPECT
            and abs(pct) > IMPLAUSIBLE_DAILY_PCT):
        quality = "suspect"

    return {
        "kind": row["kind"],
        "key": row["key"],
        "as_of": _as_of(row),
        "ts": row.get("ts"),
        "value": round(value, 6),
        "previous": round(previous, 6) if previous is not None else None,
        "change": round(change, 6) if change is not None else None,
        "pct": round(pct, 4) if pct is not None else None,
        "ytd_pct": (round(_f(row.get("ytd_pct")), 4)
                    if _f(row.get("ytd_pct")) is not None else None),
        "currency": (row.get("currency") or None),
        "quality": quality,
        "source": row["source"],
        "fetched_at": row.get("fetched_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def clean_unit(unit: str | None) -> str | None:
    """Strip the HTML entities the catalog carries for display."""
    if not unit:
        return None
    return (unit.replace("&amp;", "&").replace("&middot;", "·")
                .replace("&ndash;", "–").replace("&mdash;", "—").strip())
