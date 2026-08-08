# Cobalt — project spec

A personal, locally hosted market intelligence platform. Single user, runs on
localhost, no deployment target.

## Workflow

1. User runs a script in the terminal to launch the local server.
2. User opens it in a browser; the site shows the **last refreshed** data.
3. A **refresh button** in the site triggers a scraper / cleaning job that
   ingests new data from the selected APIs. Scope depends on where it sits:
   the one on the **home page refreshes everything**; the one on any **section
   page refreshes only that page**. The ETL therefore needs per-source jobs
   that can be run individually or as a full sweep.
4. When the job completes, the site refreshes and shows current-day data.

Data comes from free, publicly available APIs (Yahoo Finance and similar).
An ETL workflow sits between the APIs and a local database.

## Primary purpose

Prioritize understanding **economic relationships and trends**, not just
portfolio tracking. The full instrument list and the relationship chains to
observe live in `updated-context.md` — that file is the source of truth for
*what* gets tracked.

## Pages

- **Home** — landing page, links to everything.
- **News** — politics (primarily US), economics, technology/science.
- **Macroeconomics** — inflation, labor, growth.
- **Interest rates & credit** — policy & treasuries, credit spreads.
- **Market indexes** — United States, international.
- **Commodities & materials** — precious, industrial & battery, energy.
- **Key companies** — tech/AI, industrial, energy, financials, consumer.
- **ETFs** — broad market, international, materials & commodities.
- **Trackers** — AI bubble tracker (market activity for key AI players plus
  relevant AI news), bitcoin.
- **Relationships** — the causal chains listed in `updated-context.md`.

## Ollama integration (deferred — not now)

A local model parses the app's database to summarize key workflows. Example: the
bubble tracker gets a daily summary slot where the model reads the updated data
and gives context. Same capability on other pages on demand — a "summarize
today's news?" button.

Explicitly deferred by the user; do not build until asked.
