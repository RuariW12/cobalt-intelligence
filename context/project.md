# Cobalt — project spec

A personal, locally hosted market intelligence platform. Single user, runs on
localhost, no deployment target.

## Workflow

1. User runs a script in the terminal to launch the local server.
2. User opens it in a browser; the site shows the **last refreshed** data.
3. A **refresh button** in the site triggers a scraper / cleaning job that
   ingests new data from the selected APIs.
4. When the job completes, the site refreshes and shows current-day data.

Data comes from free, publicly available APIs (Yahoo Finance and similar).
An ETL workflow sits between the APIs and a local database.

## Pages

- **Home** — landing page, links to everything.
- **News** — politics (primarily US), economics, technology/science.
- **Economics** — an overview page with four sub-pages beneath it:
  - Rare metal tracker (gold, silver, tungsten, etc.)
  - Bitcoin tracker
  - Indices — S&P 500, Dow
  - Vanguard funds — VOO, VTI, VXUS
- **AI Bubble tracker** — market activity for key players in the AI space, plus
  relevant AI news.

## Ollama integration (deferred — not now)

A local model parses the app's database to summarize key workflows. Example: the
bubble tracker gets a daily summary slot where the model reads the updated data
and gives context. Same capability on other pages on demand — a "summarize
today's news?" button.

Explicitly deferred by the user; do not build until asked.
