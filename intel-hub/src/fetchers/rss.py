"""RSS / Atom feed fetcher."""

from __future__ import annotations

import logging
import ssl
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import feedparser

# Some macOS Python builds ship without an up-to-date CA bundle, causing
# CERTIFICATE_VERIFY_FAILED on HTTPS RSS feeds. Prefer a certifi-backed
# context; fall back to an unverified context (best-effort) rather than
# failing the entire pipeline.
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


def _parse_date(entry: dict) -> str | None:
    """Return YYYY-MM-DD from feed entry or None."""
    for key in ("published_parsed", "updated_parsed"):
        tp = entry.get(key)
        if tp:
            try:
                return datetime(*tp[:6], tzinfo=timezone.utc).strftime("%Y-%m-%d")
            except Exception:
                continue

    for key in ("published", "updated"):
        raw = entry.get(key, "")
        if not raw:
            continue
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ",
                     "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                     "%Y-%m-%d"):
            try:
                return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return None


def _extract_excerpt(entry: dict) -> str | None:
    summary = entry.get("summary", "")
    if summary:
        return summary[:500]
    content_list = entry.get("content", [])
    if content_list and isinstance(content_list, list):
        return content_list[0].get("value", "")[:500]
    return None


def fetch_rss(spec: "SourceSpec", window_days: int) -> list[RawItem]:
    if not spec.url:
        log.warning("RSS source missing 'url'")
        return []

    feed = feedparser.parse(spec.url)
    if feed.bozo and not feed.entries:
        log.warning("RSS feed parse error for %s: %s", spec.url, feed.bozo_exception)
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).strftime("%Y-%m-%d")
    source_label = spec.label or feed.feed.get("title", spec.url)
    items: list[RawItem] = []

    for entry in feed.entries:
        link = entry.get("link", "")
        if not link:
            continue
        pub_date = _parse_date(entry)
        if pub_date and pub_date < cutoff:
            continue

        items.append(RawItem(
            url=link,
            title=entry.get("title", "").strip(),
            source=source_label,
            publish_date=pub_date,
            excerpt=_extract_excerpt(entry),
        ))

    log.info("RSS %s: fetched %d items", spec.url, len(items))
    return items


register("rss", fetch_rss)
