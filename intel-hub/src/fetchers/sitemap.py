"""Sitemap fetcher — parses XML sitemaps to discover article URLs.

Useful for JS-rendered sites (Next.js, Nuxt, etc.) where html_list cannot
extract links because the content is loaded client-side, but the sitemap.xml
is always static XML with <loc> and often <lastmod> dates.
"""

from __future__ import annotations

import logging
import re
import ssl
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from src.extract.date_extract import extract_date_from_url, _try_parse
from src.fetchers import register
from src.models import RawItem

if TYPE_CHECKING:
    from src.models import SourceSpec

log = logging.getLogger(__name__)

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _get(url: str, timeout: int = 15) -> str:
    req = Request(url, headers=_HEADERS)
    with urlopen(req, timeout=timeout, context=_CTX) as r:
        return r.read().decode("utf-8", errors="replace")


def _title_from_slug(url: str) -> str:
    """Derive a readable title from the URL slug."""
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"[-_]", " ", slug)
    return slug.strip().title()


def fetch_sitemap(spec: "SourceSpec", window_days: int) -> list[RawItem]:
    if not spec.url:
        log.warning("sitemap source missing 'url'")
        return []

    try:
        xml = _get(spec.url)
    except Exception:
        log.exception("Failed to fetch sitemap %s", spec.url)
        return []

    soup = BeautifulSoup(xml, "html.parser")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).strftime("%Y-%m-%d")
    source_label = spec.label or spec.url
    items: list[RawItem] = []

    path_filter = spec.query or ""

    for url_tag in soup.find_all("url"):
        loc = url_tag.find("loc")
        if not loc or not loc.text:
            continue
        href = loc.text.strip()

        if path_filter and path_filter not in href:
            continue

        lastmod_tag = url_tag.find("lastmod")
        pub_date = None
        if lastmod_tag and lastmod_tag.text:
            pub_date = _try_parse(lastmod_tag.text.strip())

        if not pub_date:
            pub_date = extract_date_from_url(href)

        if not pub_date:
            continue

        if pub_date < cutoff:
            continue

        title = _title_from_slug(href)
        items.append(RawItem(
            url=href,
            title=title,
            source=source_label,
            publish_date=pub_date,
        ))

    log.info("sitemap %s: fetched %d items (path_filter=%r)", spec.url, len(items), path_filter)
    return items


register("sitemap", fetch_sitemap)
