"""ETL entrypoint — not implemented yet.

Exists so `docker compose run --rm etl` fails with an explanation rather than
a ModuleNotFoundError. The pipeline design lives in context/etl-plan.md.
"""

from __future__ import annotations

import argparse
import sys

SECTIONS = [
    "all", "news", "macro", "rates", "indexes", "commodities",
    "companies", "etfs", "ai-bubble", "bitcoin",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="etl.run", description="Cobalt ingest")
    parser.add_argument("--section", default="all", choices=SECTIONS,
                        help="which section to ingest (default: all)")
    args = parser.parse_args(argv)

    print(f"ETL not implemented yet (requested section: {args.section})", file=sys.stderr)
    print("Design: context/etl-plan.md", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
