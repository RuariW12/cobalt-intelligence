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


def available() -> bool:
    return bool(os.environ.get("FRED_API_KEY"))


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
                r = client.get(OBS, params={
                    "series_id": sid, "api_key": key, "file_type": "json",
                    "sort_order": "desc", "limit": 2,
                })
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
