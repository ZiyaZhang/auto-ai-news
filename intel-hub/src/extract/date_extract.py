"""Publish-date extraction with ordered fallback chain.

Fallback order:
  1. HTML meta tags  (article:published_time, datePublished, pubdate, etc.)
  2. JSON-LD         (datePublished / dateCreated in <script type="application/ld+json">)
  3. <time> tag      (datetime attribute)
  4. Visible text    (scan for date-like strings near top of page)
  5. URL path regex  (/2026/02/28/ patterns)
  6. RSS hint        (caller passes feed-level date as fallback)
  7. DISCARD         (returns None — hard rule: no date = no item)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

_DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%b. %d, %Y",
]

_URL_DATE_RE = re.compile(
    r"/(\d{4})/(\d{1,2})/(\d{1,2})(?:/|$)"
    r"|"
    r"/(\d{4})-(\d{2})-(\d{2})(?:/|$)"
    r"|"
    r"/(\d{8})(?:/|$)"
)

_VISIBLE_DATE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}", re.I), "%b %d, %Y"),
    (re.compile(r"\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}", re.I), "%d %b %Y"),
    (re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"), "%Y-%m-%d"),
    (re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}", re.I), "%B %d, %Y"),
]


def _try_parse(raw: str) -> str | None:
    """Try multiple formats; return YYYY-MM-DD or None."""
    raw = raw.strip().rstrip(".")
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Also try with comma variants
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw.replace(",", ""), fmt.replace(",", "")).strftime("%Y-%m-%d")
        except ValueError:
            continue
    iso_match = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
    if iso_match:
        return iso_match.group(1)
    return None


# ── Strategy 1: HTML <meta> tags ──

_META_PROPERTIES = [
    "article:published_time",
    "article:published",
    "datePublished",
    "og:article:published_time",
    "pubdate",
    "date",
    "DC.date.issued",
]

_META_NAMES = [
    "pubdate",
    "publishdate",
    "date",
    "article_date_original",
    "sailthru.date",
    "dcterms.date",
]


def _from_meta(soup: BeautifulSoup) -> str | None:
    for prop in _META_PROPERTIES:
        tag = soup.find("meta", property=prop)
        if tag and tag.get("content"):
            result = _try_parse(tag["content"])
            if result:
                return result

    for name in _META_NAMES:
        tag = soup.find("meta", attrs={"name": re.compile(name, re.I)})
        if tag and tag.get("content"):
            result = _try_parse(tag["content"])
            if result:
                return result
    return None


# ── Strategy 2: JSON-LD ──

def _from_jsonld(soup: BeautifulSoup) -> str | None:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in ("datePublished", "dateCreated", "dateModified"):
                raw = item.get(key, "")
                if raw:
                    result = _try_parse(str(raw))
                    if result:
                        return result
            graph = item.get("@graph", [])
            if isinstance(graph, list):
                for node in graph:
                    if isinstance(node, dict):
                        for key in ("datePublished", "dateCreated"):
                            raw = node.get(key, "")
                            if raw:
                                result = _try_parse(str(raw))
                                if result:
                                    return result
    return None


# ── Strategy 3: <time> tag ──

def _from_time_tag(soup: BeautifulSoup) -> str | None:
    for time_tag in soup.find_all("time", datetime=True):
        result = _try_parse(time_tag["datetime"])
        if result:
            return result
    for time_tag in soup.find_all("time"):
        text = time_tag.get_text(strip=True)
        result = _try_parse(text)
        if result:
            return result
    return None


# ── Strategy 4: Visible text scan ──

def _from_visible_text(soup: BeautifulSoup) -> str | None:
    """Scan visible text in date-likely containers for date patterns."""
    date_containers = soup.find_all(
        ["span", "div", "p", "small", "li"],
        class_=re.compile(r"(date|time|publish|posted|created|updated|meta)", re.I),
    )
    date_containers += soup.find_all(attrs={"data-date": True})

    for el in date_containers:
        if hasattr(el, "get") and el.get("data-date"):
            result = _try_parse(el["data-date"])
            if result:
                return result
        text = el.get_text(strip=True) if hasattr(el, "get_text") else str(el)
        result = _try_parse(text)
        if result:
            return result

    body = soup.find("article") or soup.find("main") or soup.body or soup
    text_block = body.get_text(separator=" ", strip=True)[:2000]
    for pattern, _ in _VISIBLE_DATE_PATTERNS:
        m = pattern.search(text_block)
        if m:
            result = _try_parse(m.group(0))
            if result:
                return result

    return None


# ── Strategy 5: URL path regex ──

def extract_date_from_url(url: str) -> str | None:
    m = _URL_DATE_RE.search(url)
    if not m:
        return None

    if m.group(1):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    elif m.group(4):
        y, mo, d = int(m.group(4)), int(m.group(5)), int(m.group(6))
    elif m.group(7):
        s = m.group(7)
        y, mo, d = int(s[:4]), int(s[4:6]), int(s[6:8])
    else:
        return None

    if 1990 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
        return f"{y:04d}-{mo:02d}-{d:02d}"
    return None


# ── Public API ──

def extract_date_from_html(html: str) -> str | None:
    """Run the full fallback chain on raw HTML. Returns YYYY-MM-DD or None."""
    soup = BeautifulSoup(html, "html.parser")

    result = _from_meta(soup)
    if result:
        return result

    result = _from_jsonld(soup)
    if result:
        return result

    result = _from_time_tag(soup)
    if result:
        return result

    result = _from_visible_text(soup)
    if result:
        return result

    return None


def extract_date(
    html: str | None = None,
    url: str | None = None,
    rss_date: str | None = None,
) -> str | None:
    """Combined extractor using all available signals."""
    if html:
        result = extract_date_from_html(html)
        if result:
            return result

    if url:
        result = extract_date_from_url(url)
        if result:
            return result

    if rss_date:
        result = _try_parse(rss_date)
        if result:
            return result

    return None
