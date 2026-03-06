"""Optional content / excerpt extraction from raw HTML.

Uses a simple heuristic: find the densest text block, stripping nav/footer/aside.
Falls back to og:description or meta description.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag


_NOISE_TAGS = {"nav", "footer", "aside", "header", "script", "style", "noscript", "iframe"}


def extract_text(html: str, max_chars: int = 2000) -> str:
    """Extract the main readable text from an HTML page."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()

    article = soup.find("article") or soup.find("main") or soup.find("div", class_=re.compile(r"(content|article|post)", re.I))
    root: Tag = article if isinstance(article, Tag) else soup.body or soup

    paragraphs = root.find_all("p")
    text_parts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
    text = "\n\n".join(text_parts)

    if not text:
        text = root.get_text(separator="\n", strip=True)

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:max_chars]


def extract_excerpt(html: str, max_chars: int = 300) -> str | None:
    """Extract a short excerpt suitable for display."""
    soup = BeautifulSoup(html, "html.parser")

    og = soup.find("meta", property="og:description")
    if og and og.get("content"):
        return og["content"].strip()[:max_chars]

    desc = soup.find("meta", attrs={"name": "description"})
    if desc and desc.get("content"):
        return desc["content"].strip()[:max_chars]

    text = extract_text(html, max_chars=max_chars + 100)
    if text:
        return text[:max_chars]
    return None
