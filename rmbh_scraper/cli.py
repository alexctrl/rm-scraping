"""Command line interface.

    python -m rmbh_scraper crawl [--data-dir data] [--images] [--workers 4]
    python -m rmbh_scraper get 3240 --purpose sale
    python -m rmbh_scraper search --purpose sale --type 2 [--bedrooms 3] [--neighborhood 44]
    python -m rmbh_scraper types --purpose rent
    python -m rmbh_scraper neighborhoods --purpose sale --type 2
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .client import RENT, SALE, RMBHClient
from .crawler import Crawler

PURPOSE_ARG = {"rent": RENT, "aluguel": RENT, "1": RENT, "sale": SALE, "venda": SALE, "2": SALE}


def _purpose(v: str) -> int:
    try:
        return PURPOSE_ARG[v.lower()]
    except KeyError:
        raise argparse.ArgumentTypeError("purpose must be rent|sale") from None


def _dump(obj) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rmbh_scraper", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--delay", type=float, default=0.25, help="min seconds between requests (default 0.25)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("crawl", help="full crawl + incremental update of the JSON database")
    c.add_argument("--data-dir", default="data")
    c.add_argument("--images", action="store_true", help="download listing images (only new ones)")
    c.add_argument("--workers", type=int, default=4)
    c.add_argument("--purpose", type=_purpose, action="append", help="limit to rent or sale (repeatable)")
    c.add_argument("--force", action="store_true", help="accept a run that found far fewer listings than before")

    g = sub.add_parser("get", help="fetch one listing detail")
    g.add_argument("code", type=int)
    g.add_argument("--purpose", type=_purpose, required=True)

    s = sub.add_parser("search", help="run a search and print result cards")
    s.add_argument("--purpose", type=_purpose, required=True)
    s.add_argument("--type", type=int, default=0, help="property type id (see `types`); 0 = broad")
    s.add_argument("--bedrooms", type=int)
    s.add_argument("--neighborhood", type=int, action="append", help="neighbourhood id (repeatable)")

    t = sub.add_parser("types", help="list property types for a purpose")
    t.add_argument("--purpose", type=_purpose, required=True)

    n = sub.add_parser("neighborhoods", help="list neighbourhoods for purpose + type")
    n.add_argument("--purpose", type=_purpose, required=True)
    n.add_argument("--type", type=int, required=True)

    a = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    client = RMBHClient(min_interval=a.delay)

    if a.cmd == "crawl":
        crawler = Crawler(
            client,
            data_dir=a.data_dir,
            workers=a.workers,
            download_images=a.images,
            purposes=tuple(a.purpose) if a.purpose else (RENT, SALE),
        )
        report = crawler.run(force=a.force)
        _dump({k: (len(v) if isinstance(v, list) else v) for k, v in report.items()})
    elif a.cmd == "get":
        d = client.get_listing(a.code, a.purpose)
        if d is None:
            print(f"listing {a.code} not found", file=sys.stderr)
            return 1
        _dump(d)
    elif a.cmd == "search":
        _dump(client.search(a.purpose, a.type, bedrooms=a.bedrooms, neighborhoods=a.neighborhood))
    elif a.cmd == "types":
        _dump(client.get_property_types(a.purpose))
    elif a.cmd == "neighborhoods":
        _dump(client.get_neighborhoods(a.purpose, a.type))
    return 0
