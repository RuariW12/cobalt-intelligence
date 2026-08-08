# ETL plan — sources, gaps, and deduplication

_Written 2026-08-08. Planning only; nothing built yet._

## Principle

**Fetch once, render many.** Every number is pulled a single time, stored once,
and read by whichever pages need it. Deduplication is a *rendering* decision,
not a fetching one — the same series appearing on two pages must never mean two
API calls.

That makes the pipeline: `fetch -> normalize -> store -> derive -> render`.

---

## Source map

### FRED — the single biggest win

One free API key covers **all of macroeconomics and all of interest rates &
credit**. 120 requests/minute, no paid tier, no commercial restriction for
personal use. Key from `fredaccount.stlouisfed.org`.

| Page | Series IDs |
| --- | --- |
| macro/inflation | `CPIAUCSL` `CPILFESL` `PCEPI` `PCEPILFE` `PPIFIS` |
| macro/labor | `UNRATE` `PAYEMS` `ICSA` `JTSJOL` `CES0500000003` |
| macro/growth | `GDPC1` `RSAFS` `INDPRO` `HOUST` |
| rates/treasuries | `FEDFUNDS` `DGS2` `DGS10` `DGS30` `T10Y2Y` |
| rates/credit | `BAMLC0A0CM` `BAMLH0A0HYM2` |

`T10Y2Y` is published directly, so the curve spread needs no derivation.
Verify each ID on first run — they are stable but worth asserting.

### Yahoo Finance (via `yfinance`) — everything with a ticker

Covers equities, ETFs, indexes, FX and the liquid futures. Unofficial endpoints:
tolerated for hobby-scale use, rate-limited aggressively past that. One daily
pull of ~60 tickers is comfortably inside that, but the pipeline must treat it
as *unreliable by design* — cache raw responses, tolerate failures, never let a
Yahoo outage abort the run.

- Indexes: `^GSPC` `^IXIC` `^DJI` `^N225` `^KS11` `000001.SS` `^HSI` `^STOXX`
- Companies: the 23 tickers already in the skeleton
- ETFs: all 16 tickers already in the skeleton
- Commodities: `GC=F` `SI=F` `HG=F` `CL=F` `BZ=F` `NG=F` `ALI=F`

**Fallback:** Stooq serves end-of-day CSV with no key and no rate limit. Worth
wiring as a secondary adapter for indexes and equities from the start, because
Yahoo *will* break at some point.

### Other sources

| Need | Source | Notes |
| --- | --- | --- |
| Bitcoin price, market cap, dominance | CoinGecko free tier | No key for basic use |
| Index weights / concentration | iShares `IVV` + SSGA `SPY` daily holdings CSV | Publicly published, no key. Gives NVDA weight and top-10 weight directly |
| Filings, capex, circularity | SEC EDGAR full-text search + RSS | Official, free, generous limits |
| Tech & science news | Hacker News (Algolia API), arXiv API | Both free, no key |
| General news | Publisher RSS direct | See below |
| Market open/closed | Exchange calendars, computed locally | No API needed |

### News

**Publisher RSS directly** is the cleanest legal route: fetch the feed, store
headline + link + timestamp, always link out, never mirror article bodies. That
respects copyright and is what the skeleton already assumes — headlines link to
source.

Avoid NewsAPI's free tier: it forbids commercial use, caps at 100 req/day and
delays articles 24 hours, which defeats "today's news".

**GDELT** is the strongest free structured option — no key, no registration,
global coverage with entity and theme tagging. Useful for the AI-bubble feed and
for tagging articles to sections automatically.

---

## Gaps — no good free source

Ranked by how much they matter.

**1. ISM Manufacturing & Services PMI — no free source, confirmed.**
ISM had all 22 series *removed from FRED in June 2016* over licensing, and their
terms grant only personal, non-commercial display. There is no free API.
_Recommended substitute:_ regional Fed manufacturing surveys, all free on FRED
and well correlated — Philadelphia Fed, Empire State, Dallas Fed, Kansas City —
plus the Chicago Fed National Activity Index. Arguably better than ISM alone,
since it shows regional dispersion.

**2. Tungsten — no free source at any price tier.**
Assessed by Fastmarkets/Argus only. There is no futures market to fall back on.
_Recommended:_ drop the price row entirely; track via REMX/SETM and news.

**3. Uranium, lithium, cobalt — no free spot.**
Confirmed: the metals APIs advertising these have no free tier (Metals-API
starts at $19.99/mo). _Recommended:_ proxy via URA, LIT and miner equities,
labelled explicitly as proxies — which the skeleton already does.

**4. Iron ore, nickel, aluminum — thin or absent.**
LME is not free. Yahoo carries `ALI=F` (aluminum) but it is thin; nickel and
iron ore have no reliable free ticker. _Recommended:_ proxy iron ore via
BHP/RIO/VALE, or drop nickel and iron ore to news-only.

**5. Nasdaq-100 forward P/E — no free source.**
Forward estimates are licensed. _Recommended:_ compute *trailing* P/E from
constituent data, and label it trailing. Directionally useful, honestly labelled.

**6. Hyperscaler capex guidance — no API, by nature.**
Stated on earnings calls quarterly. _Recommended:_ extract from EDGAR filings
with the local model; refresh quarterly, not daily.

**7. Private valuations (OpenAI, Anthropic, xAI) — news only.**
Only move when a round is announced. Extract from the news feed.

---

## Deduplication

The skeleton currently repeats content in five places. Proposals:

**a. Section overview pages repeat their children.**
`/macro`, `/rates`, `/commodities`, `/companies`, `/etfs`, `/indexes` each carry
a fixed snapshot duplicating rows from their subpages. _Proposal:_ replace the
fixed snapshot with **"biggest movers"** — the 2–3 largest absolute moves in
that section today, computed at render. Never repeats predictably, and says
something the subpages don't.

**b. `/ai-bubble` repeats five tickers from `/companies/tech`.**
NVDA, MSFT, AMZN, GOOGL, TSM, ASML appear on both. _Proposal:_ `/companies/tech`
owns the price table. `/ai-bubble` drops prices entirely and shows only
bubble-specific columns — index weight, capex, valuation multiple — linking out
for price. The thesis page should show what the sector page cannot.

**c. Uranium appears as URA on both `/commodities/energy` and `/etfs/materials`.**
_Proposal:_ `/commodities/energy` shows URA as the labelled uranium proxy;
`/etfs/materials` shows it with fund-specific columns (AUM, flows) rather than
repeating price.

**d. "Related headlines" could show the same article on many pages.**
_Proposal:_ dedupe by URL globally at ingest. Each article gets exactly one
canonical section plus entity tags. A data page shows articles matching its
entities, excluding any already shown on its parent page.

**e. Index vs ETF pairs — not duplication.**
`^GSPC`/VOO and `^IXIC`/QQQ are genuinely different instruments that diverge.
Leave as is.

---

---

## Decisions taken 2026-08-08

**Overview pages become links only.** `/macro`, `/rates`, `/indexes`,
`/commodities`, `/companies`, `/etfs` lose their snapshot tables entirely and
carry just the section list and the summary panel. No data, so no duplication.
They keep their refresh button, which now means *refresh every series in this
section* — the one place where page-scoped refresh covers more than one page.

**ISM is dropped, not substituted.** `/macro/growth` keeps Real GDP, retail
sales, industrial production and housing starts. No survey data. Accepted cost:
no forward-looking sentiment indicator; growth is read from hard data only,
which lags.

**Commodities with no free feed are removed from the tables**, rather than shown
as proxies. Removed: tungsten, uranium, lithium, cobalt, iron ore, nickel.
These metals now appear **only** on `/etfs/materials`, via REMX, SETM, LIT, URA
and COPX — which makes that page their single canonical home. Clean, and it
matches the fetch-once rule.

Consequences to handle:

- `/commodities/industrial` drops from seven rows to **copper alone** (aluminum
  `ALI=F` exists but is thin). The page may no longer justify existing —
  see open question below.
- `/commodities/energy` loses uranium, keeping WTI, Brent, natural gas and the
  Brent–WTI spread. Still a solid page.
- `/commodities/precious` is unaffected: gold, silver, and the ratio.
- The "assessed · proxy needed" tables are deleted, along with the source notes
  explaining the proxy relationship.
- `/ai-bubble` links "uranium & natural gas" to `/commodities/energy`; the
  uranium half of that must repoint to `/etfs/materials`.

## Storage sketch

SQLite, one file, no server.

```
instrument   id, symbol, name, kind, source, unit, canonical_page
series       id, instrument_id, metric, frequency
observation  series_id, ts, value          -- append only
article      id, url UNIQUE, title, source, published_at, section
article_tag  article_id, instrument_id
ingest_run   id, source, started, finished, status, rows, error
```

`observation` is append-only so revisions are visible — macro series get revised
and the history matters. `url UNIQUE` on `article` is what enforces (d).

## Cadence

Refresh scope differs by source, so the pipeline tracks freshness **per series,
not per page**:

- prices, news — daily (or on demand)
- macro releases — weekly/monthly; polling daily is wasteful but harmless
- capex, private valuations — quarterly / event-driven

A page's refresh button runs only the source adapters its series depend on. The
home page runs everything. This is why `instrument.canonical_page` exists.
