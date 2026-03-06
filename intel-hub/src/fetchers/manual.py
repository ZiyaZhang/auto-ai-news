"""Manual URL list fetcher.

Takes a flat list of URLs from the job spec and fetches each page to extract
title, date, and excerpt.
"""

from __future__ import annotations

import logging
import ssl
import time
from typing import TYPE_CHECKING
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from src.extract.date_extract import extract_date_from_html, extract_date_from_url
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


def _get(url: str, timeout: int = 20) -> str:
    req = Request(url, headers=_HEADERS)
    with urlopen(req, timeout=timeout, context=_CTX) as r:
        return r.read().decode("utf-8", errors="replace")


def _extract_title(soup: BeautifulSoup) -> str:
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return ""


def _extract_excerpt(soup: BeautifulSoup) -> str | None:
    og = soup.find("meta", property="og:description")
    if og and og.get("content"):
        return og["content"].strip()[:500]
    desc = soup.find("meta", attrs={"name": "description"})
    if desc and desc.get("content"):
        return desc["content"].strip()[:500]
    return None


def fetch_manual(spec: "SourceSpec", window_days: int) -> list[RawItem]:
    urls = spec.urls or []
    if spec.url:
        urls = [spec.url] + urls
    if not urls:
        log.warning("manual_urls source has no URLs")
        return []

    source_label = spec.label or "manual"
    items: list[RawItem] = []

    for url in urls:
        try:
            html = _get(url)
        except Exception:
            log.warning("Failed to fetch manual URL %s", url)
            items.append(RawItem(
                url=url,
                title=url,
                source=source_label,
                publish_date=extract_date_from_url(url),
            ))
            continue

        soup = BeautifulSoup(html, "html.parser")
        pub_date = extract_date_from_html(html) or extract_date_from_url(url)
        title = _extract_title(soup) or url

        items.append(RawItem(
            url=url,
            title=title,
            source=source_label,
            publish_date=pub_date,
            excerpt=_extract_excerpt(soup),
            raw_html=html[:100_000],
        ))
        time.sleep(0.3)

    log.info("manual: fetched %d items from %d URLs", len(items), len(urls))
    return items


register("manual_urls", fetch_manual)
