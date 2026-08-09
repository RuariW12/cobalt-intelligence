"""Headlines, from publisher RSS.

Feeds directly from the publisher, parsed with the standard library. No news
API: the free tiers forbid commercial use, cap at a hundred requests a day and
delay articles by 24 hours, which defeats the point of a daily brief.

Only headline, link and timestamp are stored — never article text. The page
links out, which is what a feed is for and keeps this the right side of
copyright.

Parsed with xml.etree rather than feedparser to avoid a dependency for
something the standard library already does; RSS 2.0 and Atom differ mostly in
element names, handled below.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import httpx

ATOM = "{http://www.w3.org/2005/Atom}"
HEADERS = {"User-Agent": "Mozilla/5.0 (cobalt; personal news reader)"}

# Verified reachable and returning real items. Grouped by the section each one
# feeds; a publisher can appear in more than one.
FEEDS: tuple[tuple[str, str, str], ...] = (
    # section,    publisher,        url
    ("politics",  "NPR",            "https://feeds.npr.org/1014/rss.xml"),
    ("politics",  "The Hill",       "https://thehill.com/news/feed/"),
    ("politics",  "Politico",       "https://rss.politico.com/politics-news.xml"),
    ("economics", "CNBC",           "https://search.cnbc.com/rs/search/combinedcms/view.xml"
                                    "?partnerId=wrss01&id=20910258"),
    # MarketPulse rather than MarketWatch's top stories: the latter is mostly
    # personal-finance columns ("minimize taxes in retirement"), which is not
    # what this section is for.
    ("economics", "MarketWatch",    "https://feeds.content.dowjones.io/public/rss/mw_marketpulse"),
    ("economics", "BBC",            "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("economics", "Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("tech",      "Ars Technica",   "https://feeds.arstechnica.com/arstechnica/index"),
    ("tech",      "The Verge",      "https://www.theverge.com/rss/index.xml"),
    ("tech",      "Phys.org",       "https://phys.org/rss-feed/"),
    ("tech",      "Hacker News",    "https://hnrss.org/frontpage"),
    # Crypto sits under economics: the bitcoin page pulls these through the
    # `crypto` tag rather than by section, and they are market news first.
    ("economics", "CoinDesk",       "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("economics", "Decrypt",        "https://decrypt.co/feed"),
)


def _text(node, *names) -> str:
    for name in names:
        found = node.find(name)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


def _link(item) -> str:
    raw = _text(item, "link")
    if raw:
        return raw
    # Atom puts the URL in an attribute, and may list several
    for link in item.findall(f"{ATOM}link"):
        rel = link.get("rel", "alternate")
        if rel == "alternate" and link.get("href"):
            return link.get("href")
    return ""


def _when(item) -> str | None:
    raw = _text(item, "pubDate", "published", f"{ATOM}published", f"{ATOM}updated",
                "{http://purl.org/dc/elements/1.1/}date")
    if not raw:
        return None
    for parse in (parsedate_to_datetime,
                  lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))):
        try:
            dt = parse(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
        except (TypeError, ValueError):
            continue
    return None


def _clean_title(raw: str) -> str:
    """Feeds smuggle markup and entities into titles."""
    text = re.sub(r"<[^>]+>", "", raw)
    for entity, char in (("&amp;", "&"), ("&#39;", "'"), ("&quot;", '"'),
                         ("&apos;", "'"), ("&nbsp;", " "), ("&#8217;", "’")):
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", text).strip()


def fetch(feeds=FEEDS, timeout: float = 20.0) -> tuple[list[dict], list[str]]:
    """Return (articles, failed_publishers). One bad feed never fails the run."""
    out: list[dict] = []
    failed: list[str] = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with httpx.Client(headers=HEADERS, timeout=timeout, follow_redirects=True) as client:
        for section, publisher, url in feeds:
            try:
                r = client.get(url)
                r.raise_for_status()
                root = ET.fromstring(r.content)
            except Exception:
                failed.append(publisher)
                continue

            items = root.findall(".//item") or root.findall(f".//{ATOM}entry")
            for item in items:
                title = _clean_title(_text(item, "title", f"{ATOM}title"))
                link = _link(item)
                if not title or not link:
                    continue
                out.append({
                    "url": link.split("?utm_")[0],   # strip campaign noise so
                                                     # dedupe by URL actually works
                    "title": title,
                    "publisher": publisher,
                    "section": section,
                    "published_at": _when(item),
                    "fetched_at": now,
                })

    return out, failed
