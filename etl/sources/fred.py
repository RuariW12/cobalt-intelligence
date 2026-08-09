"""FRED — every macro, treasury and credit-spread series.

Needs a free key from https://fredaccount.stlouisfed.org, in FRED_API_KEY.
Without one this source reports itself unavailable rather than failing the run,
so the rest of the ingest still works.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx

OBS = "https://api.stlouisfed.org/fred/series/observations"

# FRED serves most series as levels. A page promising "CPI, year over year"
# and then printing 332.57 — the index level — is wrong in the way that is
# hardest to notice, so ask FRED for the transform the page actually means.
#   pc1  percent change from a year ago
#   pch  percent change from the previous period
#   pca  compounded annual rate of change
#   chg  change in level
# (series, units, display unit)
TRANSFORMS: dict[str, tuple[str, str]] = {
    "CPIAUCSL": ("pc1", "% y/y"),
    "CPILFESL": ("pc1", "% y/y"),
    "PCEPI": ("pc1", "% y/y"),
    "PCEPILFE": ("pc1", "% y/y"),
    "PPIFIS": ("pc1", "% y/y"),
    "CES0500000003": ("pc1", "% y/y"),
    "RSAFS": ("pch", "% m/m"),
    "INDPRO": ("pch", "% m/m"),
    "GDPC1": ("pca", "% annualised"),
    "PAYEMS": ("chg", "thousands, m/m"),
    # Everything else is already the number the page wants: rates and spreads
    # are percentages, the unemployment rate is a percentage, claims and
    # openings and housing starts are counts.
}


# Series we take as published, but which still need their unit stated — a bare
# "4.10" for unemployment or "199,000" for claims is ambiguous on its own.
NATIVE_UNITS: dict[str, str] = {
    "UNRATE": "%",
    "ICSA": "claims, weekly",
    "JTSJOL": "openings",
    "HOUST": "thousands, annualised",
    "FEDFUNDS": "%",
    "DGS2": "%", "DGS10": "%", "DGS30": "%",
    "T10Y2Y": "percentage points",
    "BAMLC0A0CM": "percentage points", "BAMLH0A0HYM2": "percentage points",
}


def display_unit(series_id: str) -> str | None:
    if series_id in TRANSFORMS:
        return TRANSFORMS[series_id][1]
    return NATIVE_UNITS.get(series_id)


def available() -> bool:
    return bool(os.environ.get("FRED_API_KEY"))


def _observations(client, sid: str, key: str, *, limit: int | None,
                  since: str | None = None) -> list[dict]:
    """Raw observations for one series, oldest first, with the right transform."""
    params = {
        "series_id": sid, "api_key": key, "file_type": "json",
        "sort_order": "asc",
    }
    if sid in TRANSFORMS:
        params["units"] = TRANSFORMS[sid][0]
    if since:
        params["observation_start"] = since
    if limit:
        params["sort_order"] = "desc"
        params["limit"] = limit
    r = client.get(OBS, params=params)
    r.raise_for_status()
    obs = [o for o in r.json().get("observations", []) if o.get("value") not in (".", None)]
    return list(reversed(obs)) if limit else obs


def history(series_ids: list[str], since: str | None = None,
            timeout: float = 60.0) -> tuple[list[dict], list[str]]:
    """Every observation FRED holds for these series.

    The daily refresh asks for the last two values, which is all a dashboard
    needs but leaves no past to look at. This fetches the series to inception
    so the archive has something in it. Meant to be run once, not per refresh —
    a treasury series is sixteen thousand points and none of them change.
    """
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        return [], list(series_ids)

    out: list[dict] = []
    failed: list[str] = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with httpx.Client(timeout=timeout) as client:
        for sid in series_ids:
            try:
                obs = _observations(client, sid, api_key, limit=None, since=since)
            except Exception:
                failed.append(sid)
                continue
            previous = None
            for o in obs:
                try:
                    value = float(o["value"])
                except (TypeError, ValueError):
                    continue
                out.append({
                    "kind": "series", "key": sid, "ts": o["date"],
                    "value": value, "previous": previous,
                    "change": None, "pct": None, "ytd_pct": None, "currency": None,
                    "source": "fred", "fetched_at": now,
                })
                previous = value
    return out, failed


def fetch(series_ids: list[str], timeout: float = 20.0) -> tuple[list[dict], list[str]]:
    key = os.environ.get("FRED_API_KEY")
    if not key:
        return [], list(series_ids)

    out: list[dict] = []
    failed: list[str] = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with httpx.Client(timeout=timeout) as client:
        for sid in series_ids:
            try:
                params = {
                    "series_id": sid, "api_key": key, "file_type": "json",
                    "sort_order": "desc", "limit": 2,
                }
                if sid in TRANSFORMS:
                    params["units"] = TRANSFORMS[sid][0]
                r = client.get(OBS, params=params)
                r.raise_for_status()
                obs = [o for o in r.json().get("observations", []) if o.get("value") not in (".", None)]
                if not obs:
                    failed.append(sid)
                    continue
                value = float(obs[0]["value"])
                prev = float(obs[1]["value"]) if len(obs) > 1 else None
                change = (value - prev) if prev is not None else None
                out.append({
                    "kind": "series", "key": sid,
                    "ts": obs[0]["date"],
                    "value": value, "previous": prev, "change": change,
                    # A percentage-point move in a rate is not a percent change;
                    # leave pct empty and let the page show the level and delta.
                    "pct": None,
                    "currency": None,
                    "source": "fred", "fetched_at": now,
                })
            except Exception:
                failed.append(sid)

    return out, failed
