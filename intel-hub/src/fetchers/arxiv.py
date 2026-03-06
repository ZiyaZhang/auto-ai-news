"""arXiv API fetcher.

Uses the arXiv Atom API (no key required) to search for recent papers.
"""

from __future__ import annotations

import logging
import ssl
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from urllib.parse import quote

import feedparser

# See rss.py: prefer certifi CA bundle; fall back to unverified context
# to avoid macOS CERTIFICATE_VERIFY_FAILED breaking runs.
try:  # pragma: no cover
    import certifi  # type: ignore

    ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())
except Exception:  # pragma: no cover
    ssl._create_default_https_context = ssl._create_unverified_context

from src.fetchers import register
from src.models import RawItem

if TYPE_CHECKING:
    from src.models import SourceSpec

log = logging.getLogger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"


def fetch_arxiv(spec: "SourceSpec", window_days: int) -> list[RawItem]:
    query = spec.query
    if not query:
        log.warning("arxiv source missing 'query'")
        return []

    url = f"{ARXIV_API}?search_query={quote(query)}&sortBy=submittedDate&sortOrder=descending&max_results=80"
    feed = feedparser.parse(url)

    if feed.bozo and not feed.entries:
        log.warning("arXiv API error for query '%s': %s", query, feed.bozo_exception)
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).strftime("%Y-%m-%d")
    source_label = spec.label or f"arXiv:{query}"
    items: list[RawItem] = []

    for entry in feed.entries:
        link = entry.get("link", "")
        if not link:
            continue

        pub_date = None
        published = entry.get("published", "")
        if published:
            try:
                pub_date = datetime.fromisoformat(published.replace("Z", "+00:00")).strftime("%Y-%m-%d")
            except ValueError:
                pass

        if pub_date and pub_date < cutoff:
            continue

        summary = entry.get("summary", "").strip().replace("\n", " ")

        items.append(RawItem(
            url=link,
            title=entry.get("title", "").strip().replace("\n", " "),
            source=source_label,
            publish_date=pub_date,
            excerpt=summary[:500] if summary else None,
        ))

    log.info("arXiv '%s': fetched %d items", query, len(items))
    return items


register("arxiv", fetch_arxiv)
