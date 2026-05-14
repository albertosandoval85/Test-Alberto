"""
News fetcher from free RSS feeds.
Fuentes: Yahoo Finance, Reuters, MarketWatch, El Economista, Expansión.
"""
from __future__ import annotations

import time
import threading
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional
from email.utils import parsedate

try:
    import feedparser as _feedparser
    _HAS_FEEDPARSER = True
except Exception:
    _HAS_FEEDPARSER = False

_cache: dict[str, tuple[float, list]] = {}
_cache_lock = threading.Lock()
NEWS_TTL = 120  # 2 minutos

RSS_FEEDS = {
    "US Markets": [
        "https://finance.yahoo.com/rss/topstories",
        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "https://www.marketwatch.com/rss/topstories",
    ],
    "Reuters Business": [
        "https://feeds.reuters.com/reuters/businessNews",
        "https://feeds.reuters.com/reuters/companyNews",
    ],
    "México": [
        "https://feeds.eleconomista.com.mx/noticias/economia",
        "https://expansion.mx/rss",
        "https://www.elfinanciero.com.mx/rss/homepage.xml",
    ],
    "Crypto": [
        "https://cointelegraph.com/rss",
        "https://bitcoinmagazine.com/.rss/full/",
    ],
    "Commodities & Energy": [
        "https://oilprice.com/rss/main",
    ],
}

# Fallback si feedparser falla con algunos feeds
EXTRA_FEEDS = [
    "https://finance.yahoo.com/rss/headline?s=^GSPC",
    "https://finance.yahoo.com/rss/headline?s=BTC-USD",
]


def _parse_rfc822_date(date_str: str) -> datetime:
    try:
        t = parsedate(date_str)
        if t:
            return datetime(*t[:6])
    except Exception:
        pass
    return datetime.now()


def _parse_feed_xml(content: bytes, url: str) -> list[dict]:
    """Parse RSS/Atom feed with stdlib XML parser."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        try:
            # Strip BOM and retry
            content = content.lstrip(b'\xef\xbb\xbf')
            root = ET.fromstring(content)
        except Exception:
            return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = []
    source_title = url

    # RSS 2.0
    channel = root.find("channel")
    if channel is not None:
        ch_title = channel.findtext("title", default=url)
        source_title = ch_title or url
        for item in channel.findall("item")[:15]:
            title = item.findtext("title", default="Sin título")
            link = item.findtext("link", default="")
            summary = item.findtext("description", default="")
            pub_date = item.findtext("pubDate", default="")
            items.append({
                "title": title.strip(),
                "link": link.strip(),
                "summary": summary[:200] if summary else "",
                "date": _parse_rfc822_date(pub_date),
                "source": source_title,
            })
        return items

    # Atom
    for entry in root.findall("{http://www.w3.org/2005/Atom}entry")[:15]:
        title_el = entry.find("{http://www.w3.org/2005/Atom}title")
        title = title_el.text if title_el is not None else "Sin título"
        link_el = entry.find("{http://www.w3.org/2005/Atom}link")
        link = (link_el.get("href", "") if link_el is not None else "")
        updated = entry.findtext("{http://www.w3.org/2005/Atom}updated", default="")
        items.append({
            "title": (title or "").strip(),
            "link": link,
            "summary": "",
            "date": datetime.now(),
            "source": source_title,
        })
    return items


def fetch_feed(url: str, timeout: int = 8) -> list[dict]:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; BloombergTerminal/1.0)"}
        resp = requests.get(url, timeout=timeout, headers=headers)
        if resp.status_code != 200:
            return []

        if _HAS_FEEDPARSER:
            feed = _feedparser.parse(resp.content)
            items = []
            for entry in feed.entries[:15]:
                date = datetime.now()
                for attr in ("published_parsed", "updated_parsed"):
                    t = getattr(entry, attr, None)
                    if t:
                        try:
                            date = datetime(*t[:6])
                            break
                        except Exception:
                            pass
                items.append({
                    "title": entry.get("title", "Sin título"),
                    "link": entry.get("link", ""),
                    "summary": entry.get("summary", ""),
                    "date": date,
                    "source": feed.feed.get("title", url),
                })
            return items

        return _parse_feed_xml(resp.content, url)
    except Exception:
        return []


def get_all_news(max_per_category: int = 8) -> dict[str, list[dict]]:
    """Obtiene noticias de todas las fuentes agrupadas por categoría."""
    all_news: dict[str, list[dict]] = {}

    def fetch_category(category: str, urls: list[str]):
        items = []
        for url in urls:
            with _cache_lock:
                cached = _cache.get(url)
                if cached and (time.time() - cached[0]) < NEWS_TTL:
                    items.extend(cached[1])
                    continue
            fetched = fetch_feed(url)
            with _cache_lock:
                _cache[url] = (time.time(), fetched)
            items.extend(fetched)

        # Deduplicar por título y ordenar por fecha
        seen = set()
        unique = []
        for item in sorted(items, key=lambda x: x["date"], reverse=True):
            key = item["title"][:60]
            if key not in seen:
                seen.add(key)
                unique.append(item)

        all_news[category] = unique[:max_per_category]

    threads = []
    for category, urls in RSS_FEEDS.items():
        t = threading.Thread(target=fetch_category, args=(category, urls), daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join(timeout=12)

    return all_news


def get_latest_news(n: int = 30) -> list[dict]:
    """Obtiene las últimas N noticias de todas las fuentes ordenadas por fecha."""
    all_cats = get_all_news(max_per_category=15)
    combined = []
    for items in all_cats.values():
        combined.extend(items)

    seen = set()
    unique = []
    for item in sorted(combined, key=lambda x: x["date"], reverse=True):
        key = item["title"][:60]
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique[:n]


def get_ticker_news(symbol: str, n: int = 10) -> list[dict]:
    """Obtiene noticias de Yahoo Finance para un ticker específico."""
    url = f"https://finance.yahoo.com/rss/headline?s={symbol}"
    key = f"ticker_news:{symbol}"

    with _cache_lock:
        cached = _cache.get(key)
        if cached and (time.time() - cached[0]) < NEWS_TTL:
            return cached[1][:n]

    items = fetch_feed(url)
    with _cache_lock:
        _cache[key] = (time.time(), items)

    return items[:n]


def fmt_news_age(dt: datetime) -> str:
    delta = datetime.now() - dt
    s = int(delta.total_seconds())
    if s < 60:
        return f"hace {s}s"
    if s < 3600:
        return f"hace {s//60}m"
    if s < 86400:
        return f"hace {s//3600}h"
    return f"hace {s//86400}d"
