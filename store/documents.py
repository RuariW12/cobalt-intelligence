"""Turning observations into retrievable documents.

A table row is a poor unit of retrieval: it means nothing without its header,
its units, and the date it belongs to. So every observation also becomes one
self-contained sentence that carries all of that inline.

    2026-08-08 — Gold (GC=F), commodities/precious: 4,399.70 USD / troy oz,
    +157.70 (+3.72%) versus the previous session.
    [tags: commodities precious future precious-metals safe-haven inflation-hedge]

That is what gets embedded later, and what comes back from a search. It reads
correctly on its own, which is exactly what a model needs when a chunk arrives
with no surrounding context.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _num(v: float | None) -> str:
    if v is None:
        return "n/a"
    a = abs(v)
    digits = 0 if a >= 10000 else (2 if a >= 1 else 4)
    return f"{v:,.{digits}f}"


def _signed(v: float | None, suffix: str = "") -> str | None:
    if v is None:
        return None
    a = abs(v)
    return f"{v:+,.{0 if a >= 10000 else 2}f}{suffix}"


def sentence(inst: dict, obs: dict) -> str:
    """One fact, readable without any surrounding context."""
    where = inst["section"] + (f"/{inst['category']}" if inst.get("category") else "")
    ident = f"{inst['name']}"
    if inst.get("ticker") and inst["ticker"] != inst["name"]:
        ident += f" ({inst['ticker']})"
    elif inst["key"] != inst["name"]:
        ident += f" ({inst['key']})"

    head = f"{obs['as_of']} — {ident}, {where}: {_num(obs['value'])}"
    if inst.get("unit"):
        head += f" {inst['unit']}"

    # Wording has to match the cadence: a monthly macro release does not have
    # a "previous session", and calling it one invites the model to read a
    # month's move as a day's.
    against = {"symbol": "the previous session",
               "series": "the prior release"}.get(inst["kind"], "the prior reading")
    move = _signed(obs.get("change"))
    pct = _signed(obs.get("pct"), "%")
    if move and pct and inst["kind"] == "symbol":
        head += f", {move} ({pct}) versus {against}"
    elif move:
        head += f", {move} versus {against}"
    else:
        head += ", no prior reading to compare"

    if obs.get("ytd_pct") is not None:
        head += f"; {_signed(obs['ytd_pct'], '%')} year to date"
    if inst.get("period"):
        head += f" [{inst['period']}]"
    if obs.get("quality") == "suspect":
        head += " — FLAGGED: implausible move for a price, treat as suspect"
    return head + "."


def build(inst: dict, obs: dict, tags: list[str]) -> dict:
    return {
        "doc_type": "observation",
        "ref_key": inst["key"],
        "as_of": obs["as_of"],
        "section": inst["section"],
        "category": inst.get("category"),
        # Space-delimited so a LIKE '% tag %' filter works with no join, and so
        # the string is directly readable when a chunk is shown to the model.
        "tags": " ".join(tags),
        "title": f"{inst['name']} {obs['as_of']}",
        "body": sentence(inst, obs),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
