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


# --- tagging headlines -----------------------------------------------------

# Themes a headline can carry without naming any instrument. This is what lets
# a macro page pull relevant stories: nothing on /macro/inflation is a company,
# so entity matching alone would leave it empty.
# (pattern, tags, exclusion). Broad market words are ambiguous across domains:
# "power bank" is not a lender and a bitcoin miner is not a copper mine, so the
# rules that need it carry an exclusion that vetoes the match.
KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (r"inflation|consumer price|cpi\b|deflation", ("inflation",)),
    (r"federal reserve|\bfed\b|fomc|rate cut|rate hike|powell",
     ("monetary-policy", "rates")),
    (r"treasury yield|bond market|yield curve", ("rates", "treasuries")),
    (r"jobs report|unemployment|payroll|jobless|hiring|layoff", ("labor",)),
    (r"\bgdp\b|recession|economic growth", ("growth",)),
    (r"oil price|crude|opec|barrel", ("oil", "energy")),
    (r"natural gas|lng\b", ("natural-gas", "energy")),
    (r"\bgold\b|bullion|silver price", ("precious-metals",)),
    (r"copper|lithium|rare earth|critical mineral", ("industrial-metals",)),
    (r"uranium|nuclear (power|plant|reactor)", ("energy", "datacenter-power")),
    (r"bitcoin|crypto|ethereum", ("crypto",)),
    (r"artificial intelligence|\bai\b|chatgpt|openai|anthropic|llm\b",
     ("ai-supply-chain",)),
    (r"data ?cent(er|re)|gpu\b|semiconductor|chip(maker|s)?\b",
     ("semiconductors", "ai-supply-chain")),
    (r"tariff|trade war|sanction|export control", ("geopolitics",)),
    (r"housing|mortgage|home sales", ("housing",)),
    (r"\bs&p 500\b|nasdaq|dow jones|stock market|\bstocks\b|wall street|\bequities\b",
     ("equities", "us-market"), r"crypto|bitcoin|tokeni[sz]ed"),
    # deliberately not bare "shares": "Buttigieg shares his theory" is not a
    # markets story
    (r"\bshare price|\bshareholders?\b|\bipo\b|\bbuyback", ("equities",)),
    # "banks" plural and "central bank" only: the singular catches power banks,
    # food banks and river banks
    (r"central bank|\bbanks\b|\bbanking\b|\blenders?\b|\bcredit\b|bond market|\bdefaults?\b",
     ("financials", "credit"), r"power bank|blood bank|food bank|bank holiday"),
    (r"\beconom(y|ic|ies)\b|recession|\boutput\b", ("growth",)),
    (r"manufactur|\bfactor(y|ies)\b|industrial production", ("industrial-activity",)),
    (r"consumer spending|retail sales|\bshoppers?\b|consumer credit",
     ("consumer-spending", "demand")),
    (r"\bmining\b|\bminers?\b|rare earth|critical mineral",
     ("materials-proxy", "critical-materials"), r"bitcoin|crypto|hashrate|data ?mining"),
    (r"nikkei|hang seng|shanghai composite|asian markets?|european stocks",
     ("equities", "international")),
)

_KEYWORDS = tuple(
    (re.compile(rule[0], re.I), rule[1],
     re.compile(rule[2], re.I) if len(rule) > 2 and rule[2] else None)
    for rule in KEYWORDS)

# Names too short or too common to match safely: "GE", "Strategy", "Apple" in a
# fruit story. Tickers are matched case-sensitively for the same reason — "CAT"
# is a company, "cat" is not.
MIN_NAME_LEN = 5
MIN_TICKER_LEN = 3

# Instrument names that are ordinary English words. Matching these on the name
# alone tagged "Silver nanocatalysts switch reaction sites" as a precious-metals
# story. They only count when the headline also reads like market news.
AMBIGUOUS_NAMES = {
    "gold", "silver", "copper", "aluminum", "strategy", "energy",
    "consumer", "industrial", "financials", "growth",
}

MARKET_CONTEXT = re.compile(
    r"\b(pric|futures|market|rall|slump|surge|record high|record low|ounce|"
    r"barrel|tonne|demand|supply|output|trader|investor|export|import|"
    r"stockpile|inventor|miner|refinery|commodit)", re.I)


def build_matchers(instruments: dict) -> list[tuple[re.Pattern, str, tuple[str, ...]]]:
    """Compile one matcher per instrument, plus its themes.

    A headline mentioning NVIDIA should tag as `NVDA` *and* inherit
    `semiconductors` and `ai-supply-chain`, so it reaches the AI page as well
    as the company page.
    """
    out = []
    for key, inst in instruments.items():
        name = (inst["name"] or "").strip()
        ticker = (inst["ticker"] or "").strip()
        themes = tuple(THEMES.get(key, ())) + tuple(
            t for members, ts in GROUPS if key in members for t in ts)

        if len(name) >= MIN_NAME_LEN:
            out.append((re.compile(rf"\b{re.escape(name)}\b", re.I), key, themes,
                        name.lower() in AMBIGUOUS_NAMES))
        if len(ticker) >= MIN_TICKER_LEN:
            # case-sensitive: "CAT" is a company, "cat" is not
            out.append((re.compile(rf"\b{re.escape(ticker)}\b"), key, themes, False))
    return out


def for_article(title: str, matchers) -> list[str]:
    tags: set[str] = set()
    market_news = bool(MARKET_CONTEXT.search(title))
    for pattern, key, themes, needs_context in matchers:
        if not pattern.search(title):
            continue
        if needs_context and not market_news:
            continue
        tags.add(key)
        tags.update(themes)
    for pattern, themes, veto in _KEYWORDS:
        if pattern.search(title) and not (veto and veto.search(title)):
            tags.update(themes)
    return sorted(tags)
