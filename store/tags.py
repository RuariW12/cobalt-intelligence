"""Tagging — the vocabulary retrieval filters on.

Tags come from three places, cheapest first:

  structural   section and category, straight from the catalog
  inferred     asset class, from the shape of the key
  thematic     hand-mapped economic meaning, e.g. copper -> china, growth-proxy

The thematic layer is the one that earns its keep. "What does the AI buildout
touch?" cannot be answered by section alone — it spans semiconductors, power
and materials, which sit on three different pages.
"""

from __future__ import annotations

import re

# Economic meaning, not classification. Keep these few and deliberate: every
# tag here should be one somebody would actually retrieve on.
THEMES: dict[str, tuple[str, ...]] = {
    # metals
    "GC=F": ("precious-metals", "safe-haven", "inflation-hedge"),
    "SI=F": ("precious-metals", "industrial-demand", "inflation-hedge"),
    "HG=F": ("industrial-metals", "china", "growth-proxy", "electrification"),
    "ALI=F": ("industrial-metals", "china", "growth-proxy"),
    # energy
    "CL=F": ("oil", "energy", "inflation-input", "geopolitics"),
    "BZ=F": ("oil", "energy", "inflation-input", "geopolitics"),
    "NG=F": ("natural-gas", "energy", "power-demand", "datacenter-power"),
    # rates and credit
    "FEDFUNDS": ("monetary-policy", "rates", "policy-rate"),
    "DGS2": ("rates", "treasuries", "policy-expectations"),
    "DGS10": ("rates", "treasuries", "discount-rate", "housing"),
    "DGS30": ("rates", "treasuries", "long-end"),
    "T10Y2Y": ("rates", "yield-curve", "recession-signal"),
    "BAMLC0A0CM": ("credit", "investment-grade", "risk-appetite"),
    "BAMLH0A0HYM2": ("credit", "high-yield", "risk-appetite", "recession-signal"),
    # inflation
    "CPIAUCSL": ("inflation", "consumer-prices"),
    "CPILFESL": ("inflation", "core", "consumer-prices"),
    "PCEPI": ("inflation", "fed-target"),
    "PCEPILFE": ("inflation", "core", "fed-target"),
    "PPIFIS": ("inflation", "producer-prices", "pipeline-pressure"),
    # labour
    "UNRATE": ("labor", "slack"),
    "PAYEMS": ("labor", "hiring"),
    "ICSA": ("labor", "leading-indicator", "weekly"),
    "JTSJOL": ("labor", "demand-for-workers"),
    "CES0500000003": ("labor", "wages", "inflation-input"),
    # growth
    "GDPC1": ("growth", "output"),
    "RSAFS": ("growth", "consumer-spending"),
    "INDPRO": ("growth", "industrial-activity"),
    "HOUST": ("growth", "housing", "rate-sensitive", "leading-indicator"),
    # crypto
    "BTC-USD": ("crypto", "risk-appetite", "liquidity-proxy"),
    # Strategy: the common is a leveraged bitcoin proxy, the preferred is the
    # funding line behind it. Tagged so a bitcoin query pulls both.
    "MSTR": ("crypto", "bitcoin-proxy", "treasury-company", "leverage"),
    "STRC": ("crypto", "bitcoin-proxy", "treasury-company", "funding-cost"),
}

# Whole groups that share meaning, matched after the exact table above.
GROUPS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("NVDA", "AVGO", "AMD", "TSM", "ASML", "ARM"),
     ("semiconductors", "ai-supply-chain")),
    (("MSFT", "GOOGL", "AMZN", "META", "ORCL"),
     ("hyperscaler", "ai-capex", "ai-supply-chain")),
    (("CRWV", "SMCI", "VRT", "CEG"),
     ("ai-buildout", "datacenter-power", "ai-supply-chain")),
    (("XOM", "CVX", "COP", "2222.SR"), ("energy", "oil")),
    (("JPM", "BAC", "GS", "BRK-B"), ("financials", "credit", "risk-appetite")),
    (("WMT", "KO", "MCD"), ("consumer", "demand")),
    (("CAT", "DE", "HON", "GE", "SIEGY"), ("industrial-activity", "capex")),
    (("URA", "LIT", "REMX", "SETM", "COPX"),
     ("materials-proxy", "critical-materials", "electrification")),
    (("GDX", "SLV", "PPLT", "PALL"), ("precious-metals", "materials-proxy")),
    (("^GSPC", "^IXIC", "^DJI", "VTI", "VOO", "QQQ", "IWM", "VT"),
     ("equities", "us-market")),
    (("^N225", "^KS11", "000001.SS", "^HSI", "^STOXX", "VXUS", "EEM"),
     ("equities", "international")),
)


def asset_class(key: str, kind: str, section: str) -> str:
    if kind == "series":
        return "indicator"
    if kind == "derived":
        return "derived"
    if key.endswith("=F"):
        return "future"
    if key.startswith("^") or re.match(r"^\d{6}\.", key):
        return "index"
    if key.endswith("-USD"):
        return "crypto"
    if section == "etfs":
        return "etf"
    return "equity"


def slug(text: str) -> str:
    """A tag-safe token: lowercase, no punctuation, hyphenated."""
    text = re.sub(r"&[a-z]+;", " ", text or "")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text


def for_instrument(key: str, kind: str, section: str, category: str | None) -> list[str]:
    tags = {section, asset_class(key, kind, section)}
    if category:
        tags.add(slug(category))

    tags.update(THEMES.get(key, ()))
    for members, themes in GROUPS:
        if key in members:
            tags.update(themes)

    return sorted(t for t in tags if t)
