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

# Interpretive tags: useful to the model, far too broad to select headlines
# with. `geopolitics` sits on oil, so a crypto sanctions story once surfaced on
# the commodities page.
BROAD_TAGS = {"geopolitics", "risk-appetite", "liquidity-proxy", "growth-proxy",
              "leverage", "funding-cost", "derived"}


def _tracked_tags(pages) -> set[str]:
    """Instrument keys and themes tracked across the given pages."""
    wanted: set[str] = set()
    for page in pages:
        for panel in page["panels"]:
            for row in panel.get("rows", []):
                key = row.get("symbol") or row.get("series") or row.get("derived")
                if key:
                    wanted.add(key)
                    wanted.update(t for t in db.tags_for(key) if t not in BROAD_TAGS)
    return wanted


def format_value(v: float | None) -> str:
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
        return format_value(obs["value"]), None
    if field == "change":
        return _signed(obs["change"])
    if field == "pct":
        return _signed(obs["pct"], "%")
    if field == "ytd_pct":
        return _signed(obs["ytd_pct"], "%")
    return DASH, None


def _spread(rows: list, limit: int) -> list:
    """One story per publisher in turn, until the slots are full.

    Sorting purely by recency hands the page to whichever feed posts most
    often — Hacker News filled every slot and pushed Ars Technica and The Verge
    off entirely. Rows arrive newest-first, so taking them round-robin keeps
    recency within each publisher while guaranteeing a mix across them.
    """
    by_publisher: dict[str, list] = {}
    for r in rows:
        by_publisher.setdefault(r["publisher"], []).append(r)

    out: list = []
    while len(out) < limit and any(by_publisher.values()):
        for queue in by_publisher.values():
            if queue:
                out.append(queue.pop(0))
                if len(out) >= limit:
                    break
    return out


def _headlines(slug: str, page: dict, limit: int) -> list[dict]:
    """Which stories belong on this page.

    News pages filter by their own subsection. Every other page asks by what it
    tracks — the instrument keys it shows plus their themes — so an NVIDIA
    story reaches both /companies/tech and /ai-bubble without being filed twice.
    """
    if slug.startswith("sections/news"):
        parts = slug.split("/")
        section = parts[2] if len(parts) > 2 else None
        rows = _spread(db.articles(section=section, limit=limit * 6), limit)
    else:
        wanted = _tracked_tags([page])
        if not wanted:
            return []
        rows = _spread(db.articles(tags=sorted(wanted), limit=limit * 6), limit)

    out = []
    for r in rows:
        when = r["published_at"] or r["fetched_at"]
        out.append({
            "title": r["title"], "url": r["url"], "publisher": r["publisher"],
            "when": humanise(when) if when else "",
            "section": r["section"],
        })
    return out


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
    page["refreshed"] = humanise(stamp) if stamp else "never"

    for panel in page["panels"]:
        if panel["type"] == "stories":
            panel["articles"] = _headlines(slug, page, len(panel.get("items") or []) or 6)

        elif panel["type"] == "quotes":
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
                row["value_text"] = format_value(obs["value"]) if obs else DASH
                row["change_text"], row["change_cls"] = (
                    _signed(obs["change"]) if obs else (DASH, None))
                row["has_data"] = obs is not None
                row["as_of"], row["stale"] = _age(obs)

    return page


def humanise(iso: str) -> str:
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

    Two kinds are pulled and labelled separately — the figures for this
    section, and the headlines about what it tracks. Combining them is the
    point of the app: the numbers say what moved, the headlines say why.
    """
    since = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    out: list[str] = []

    data = db.search_documents(section=section, since=since, limit=limit,
                               doc_type="observation", latest_only=True)
    if data:
        out.append("## current figures")
        out.extend(r["body"] for r in data)
        out.append("")

    recent = (datetime.now(timezone.utc).date() - timedelta(days=4)).isoformat()
    if section in ("news", "home", "all"):
        news = db.search_documents(section="news", since=recent, limit=40,
                                   doc_type="article", latest_only=False)
    else:
        wanted = _page_tags(section)
        news = (db.search_documents(any_tags=sorted(wanted), since=recent, limit=15,
                                    doc_type="article", latest_only=False)
                if wanted else [])
    if news:
        out.append("## headlines")
        out.extend(r["body"] for r in news)

    return "\n".join(out).strip() or "(no data has been ingested yet)"


def _page_tags(section: str) -> set[str]:
    """Everything tracked anywhere in a section."""
    return _tracked_tags([p for p in PAGES.values() if p["section"] == section])
