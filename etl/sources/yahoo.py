"""Yahoo Finance — equities, ETFs, indexes, futures and crypto.

Uses the chart endpoint, which serves quotes without a key, cookie or crumb.
That is why this needs no yfinance and no pandas: those exist largely to handle
the authenticated endpoints, and pulling them in would roughly triple the image.

Unofficial and unsupported: Yahoo can change or rate-limit it without notice.
Every failure is per-symbol and never aborts the run.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Mozilla/5.0 (cobalt; personal use)"}

# Polite by default: this is someone else's undocumented endpoint.
PAUSE_SECONDS = 0.15


def _previous_close(result: dict, meta: dict) -> float | None:
    """The prior *session's* close.

    Not `chartPreviousClose`: with range=5d that is the close before the whole
    range — five sessions back — so using it reports a week's move as a day's.
    Futures also return `previousClose: null`, so neither meta field is
    reliable on its own. Walk the daily series instead and take the last close
    from a session earlier than the current one.
    """
    try:
        stamps = result.get("timestamp") or []
        closes = result["indicators"]["quote"][0]["close"]
        market_day = datetime.fromtimestamp(
            meta.get("regularMarketTime") or time.time(), timezone.utc).date()
        for ts, close in zip(reversed(stamps), reversed(closes)):
            if close is None:
                continue
            if datetime.fromtimestamp(ts, timezone.utc).date() < market_day:
                return float(close)
    except Exception:
        pass
    return meta.get("previousClose") or meta.get("chartPreviousClose")


def _ytd_pct(result: dict, price: float) -> float | None:
    """Percent change from the first close of the current year.

    With range=ytd the first point in the series *is* the year's opening
    session, so this needs no second request and no stored history.
    """
    try:
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        if not closes:
            return None
        first = float(closes[0])
        return (price / first - 1.0) * 100.0 if first else None
    except Exception:
        return None


def fetch(symbols: list[str], timeout: float = 15.0) -> tuple[list[dict], list[str]]:
    """Return (observations, failed_symbols)."""
    out: list[dict] = []
    failed: list[str] = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with httpx.Client(headers=HEADERS, timeout=timeout, follow_redirects=True) as client:
        for symbol in symbols:
            try:
                # range=ytd rather than 5d: the same single request then carries
                # both the prior session close and the year's opening close, so
                # YTD costs no extra call.
                r = client.get(CHART.format(symbol=symbol),
                               params={"range": "ytd", "interval": "1d"})
                r.raise_for_status()
                result = r.json()["chart"]["result"][0]
                meta = result["meta"]
                price = meta.get("regularMarketPrice")
                if price is None:
                    failed.append(symbol)
                    continue
                prev = _previous_close(result, meta)
                ytd = _ytd_pct(result, price)
                change = (price - prev) if prev is not None else None
                out.append({
                    "kind": "symbol",
                    "key": symbol,
                    "ts": datetime.fromtimestamp(
                        meta.get("regularMarketTime", time.time()), timezone.utc
                    ).isoformat(timespec="seconds"),
                    "value": price,
                    "previous": prev,
                    "change": change,
                    "pct": (change / prev * 100) if change is not None and prev else None,
                    "ytd_pct": ytd,
                    "currency": meta.get("currency"),
                    "source": "yahoo",
                    "fetched_at": now,
                })
            except Exception:
                failed.append(symbol)
            time.sleep(PAUSE_SECONDS)

    return out, failed
