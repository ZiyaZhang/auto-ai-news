"""HTML listing page fetcher.

Fetches an HTML page that contains a list of article links, extracts each
link, then attempts date extraction from:
  1. Sibling/parent text near the <a> on the listing page
  2. URL path patterns
  3. Article page HTML (only if above methods fail)
"""

from __future__ import annotations

import logging
import re
import ssl
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup, Tag

from src.extract.date_extract import extract_date_from_html, extract_date_from_url, _try_parse, _VISIBLE_DATE_PATTERNS
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


def _get(url: str, timeout: int = 12) -> str:
    req = Request(url, headers=_HEADERS)
    with urlopen(req, timeout=timeout, context=_CTX) as r:
        return r.read().decode("utf-8", errors="replace")


def _date_from_context(a_tag: Tag) -> str | None:
    """Try to find a date in the surrounding context of an <a> tag on a listing page."""
    for ancestor in [a_tag.parent, a_tag.parent.parent if a_tag.parent else None]:
        if not ancestor or not isinstance(ancestor, Tag):
            continue
        time_tag = ancestor.find("time")
        if time_tag:
            dt = time_tag.get("datetime")
            if dt:
                result = _try_parse(dt)
                if result:
                    return result
            result = _try_parse(time_tag.get_text(strip=True))
            if result:
                return result

        text = ancestor.get_text(separator=" ", strip=True)[:200]
        for pattern, _ in _VISIBLE_DATE_PATTERNS:
            m = pattern.search(text)
            if m:
                result = _try_parse(m.group(0))
                if result:
                    return result
    return None


_NAV_PATTERNS = re.compile(
    r"^(home|about|contact|login|sign.?up|register|products?|solutions?|pricing|"
    r"careers?|jobs?|team|press|privacy|terms|legal|cookie|faq|help|support|"
    r"search|subscribe|newsletter|download|docs?|documentation|api|platform|"
    r"partners?|customers?|resources?)$",
    re.I,
)

_ARTICLE_PATH_HINTS = re.compile(
    r"/(blog|news|post|article|research|paper|update|release|announcement|"
    r"insight|report|press-release|changelog|20\d{2})/",
    re.I,
)


def _is_likely_article(href: str, text: str, base_url: str) -> bool:
    """Heuristic to distinguish article links from navigation links."""
    if _NAV_PATTERNS.match(text.strip()):
        return False
    parsed = urlparse(href)
    if parsed.path in ("/", "") or parsed.path.count("/") <= 1:
        if not _ARTICLE_PATH_HINTS.search(parsed.path):
            return False
    if href.rstrip("/") == base_url.rstrip("/"):
        return False
    if "#" in href and parsed.path == urlparse(base_url).path:
        return False
    return True


def _extract_links(html: str, base_url: str) -> list[tuple[str, str, str | None]]:
    """Return (url, title, context_date) triples from <a> tags."""
    soup = BeautifulSoup(html, "html.parser")
    base_domain = urlparse(base_url).netloc.lower()

    for tag_name in ["nav", "footer", "header"]:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    seen = set()
    links: list[tuple[str, str, str | None]] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        link_domain = urlparse(href).netloc.lower()
        if not (link_domain == base_domain or base_domain.endswith("." + link_domain)
                or link_domain.endswith("." + base_domain)):
            continue
        if href in seen:
            continue
        text = a.get_text(strip=True)
        if not text or len(text) < 10:
            continue
        if not _is_likely_article(href, text, base_url):
            continue
        seen.add(href)
        ctx_date = _date_from_context(a)
        links.append((href, text, ctx_date))
    return links


def fetch_html_list(spec: "SourceSpec", window_days: int) -> list[RawItem]:
    if not spec.url:
        log.warning("html_list source missing 'url'")
        return []

    try:
        html = _get(spec.url)
    except Exception:
        log.exception("Failed to fetch listing page %s", spec.url)
        return []

    links = _extract_links(html, spec.url)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).strftime("%Y-%m-%d")
    source_label = spec.label or spec.url
    items: list[RawItem] = []
    deep_fetch_count = 0

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for href, title, ctx_date in links[:30]:
        pub_date = ctx_date or extract_date_from_url(href)

        if not pub_date and deep_fetch_count < 15:
            try:
                article_html = _get(href)
                pub_date = extract_date_from_html(article_html)
                deep_fetch_count += 1
                time.sleep(0.1)
            except Exception:
                log.debug("Could not fetch article page %s", href)

        if pub_date and pub_date < cutoff:
            continue

        if not pub_date:
            pub_date = today
            log.debug("No date for %s, using today as fallback", href)

        items.append(RawItem(
            url=href,
            title=title,
            source=source_label,
            publish_date=pub_date,
        ))

    log.info("html_list %s: fetched %d items (deep fetches: %d)", spec.url, len(items), deep_fetch_count)
    return items


register("html_list", fetch_html_list)
