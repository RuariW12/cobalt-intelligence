"""ETL package — adapters, normalisation and storage.

Not built yet. Planned layout, per context/etl-plan.md:

    sources/fred.py       macro + rates + credit spreads
    sources/yahoo.py      equities, ETFs, indexes, futures
    sources/stooq.py      end-of-day fallback for yahoo
    sources/coingecko.py  bitcoin
    sources/holdings.py   index weights from iShares/SSGA CSVs
    sources/news.py       publisher RSS + GDELT
    store.py              SQLite schema and writes
    derive.py             computed series (ratios, spreads, weights)
    run.py                CLI entrypoint: python -m etl.run --section macro

Shares an image with the web service, so the container runs it as a one-shot
command rather than a long-lived service.
"""
