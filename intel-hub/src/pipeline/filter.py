"""Filtering: date gate, marketing exclusion, detail-signal detection."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import TYPE_CHECKING

from src.models import ProcessedItem

if TYPE_CHECKING:
    from src.models import FilterSpec, RawItem

log = logging.getLogger(__name__)

# Signals that indicate substantive content (numbers, benchmarks, code, APIs)
_SIGNAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("has_numbers",    re.compile(r"\d+(\.\d+)?[%xX×]|\$\d|€\d|¥\d|\d+\s*(ms|fps|TFLOPS|GB|MB|TB)", re.I)),
    ("has_benchmark",  re.compile(r"(benchmark|SoTA|state.of.the.art|accuracy|F1|BLEU|perplexity)", re.I)),
    ("has_code",       re.compile(r"(github\.com|\.py\b|\.js\b|pip install|npm |API endpoint|SDK)", re.I)),
    ("has_data",       re.compile(r"(dataset|corpus|training data|fine-tun|parameter|token)", re.I)),
    ("has_comparison", re.compile(r"(vs\.?|compared to|outperform|improve|faster|slower|better)", re.I)),
]

_ACTION_VERBS = re.compile(
    r"(introduc|announc|releas|launch|propos|present|open.?sourc|achiev|"
    r"discover|demonstrat|develop|improv|outperform|surpass|"
    r"report|show|reveal|find|build|creat|ship|deploy|partner|rais|acquir|secur)",
    re.I,
)

_FILLER_STARTS = re.compile(
    r"^(In this (paper|article|blog|post)|We (present|propose|introduce|describe)|"
    r"This (paper|article|blog|post)|Abstract[:\s]|TL;?DR[:\s])",
    re.I,
)


def _detect_signals(text: str) -> list[str]:
    signals = []
    for name, pattern in _SIGNAL_PATTERNS:
        if pattern.search(text):
            signals.append(name)
    return signals


def _matches_exclusion(item: "RawItem", patterns: list[str]) -> bool:
    text = f"{item.title} {item.excerpt or ''}".lower()
    for pat in patterns:
        if pat.lower() in text:
            return True
    return False


def _matches_inclusion(item: "RawItem", patterns: list[str]) -> bool:
    text = f"{item.title} {item.excerpt or ''}".lower()
    return any(pat.lower() in text for pat in patterns)


_SENTENCE_END = re.compile(r"[.!?。！？；]\s+|[.!?。！？；]$")


def _make_takeaway(title: str, excerpt: str, max_len: int = 60) -> str:
    """Build a takeaway that captures "what happened" rather than just truncating.

    Strategy:
      1. If the title itself is a concise action statement, use it.
      2. Search for the first sentence containing an action verb.
      3. Fall back to the first sentence of the excerpt.
    """
    if not title and not excerpt:
        return ""

    if len(title) <= max_len and _ACTION_VERBS.search(title):
        return title

    text = _strip_html(excerpt).strip()
    if not text:
        return _truncate(title, max_len)

    text = _FILLER_STARTS.sub("", text).strip()
    text = text.lstrip(",;: ")

    sentences = _split_sentences(text)

    for sent in sentences[:3]:
        if _ACTION_VERBS.search(sent):
            return _truncate(sent, max_len)

    if sentences:
        return _truncate(sentences[0], max_len)

    return _truncate(text, max_len)


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    parts = _SENTENCE_END.split(text)
    return [s.strip() for s in parts if s.strip() and len(s.strip()) > 10]


def _truncate(text: str, max_len: int) -> str:
    text = text.strip()
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    cut = text[:max_len - 1].rstrip()
    last_space = cut.rfind(" ")
    if last_space > max_len * 0.6:
        cut = cut[:last_space]
    return cut + "…"


def _truncate_excerpt(text: str, max_len: int = 120) -> str:
    text = text.strip()
    if not text:
        return ""
    text = _strip_html(text).strip()
    if len(text) <= max_len:
        return text
    cut = text[:max_len - 1].rstrip()
    last_space = cut.rfind(" ")
    if last_space > max_len * 0.6:
        cut = cut[:last_space]
    return cut + "…"


def _strip_html(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return re.sub(r"<[^>]+>", "", text)


def filter_items(
    items: list["RawItem"],
    spec: "FilterSpec",
) -> tuple[list[ProcessedItem], dict[str, int], dict[str, dict[str, int]]]:
    """Apply date gate + exclusion + signal filters.

    Returns (processed_items, stats_dict).
    """
    stats = {"input": len(items), "no_date": 0, "not_included": 0, "excluded": 0, "low_signal": 0, "passed": 0}
    result: list[ProcessedItem] = []
    per_source: dict[str, dict[str, int]] = defaultdict(lambda: {
        "input": 0,
        "no_date": 0,
        "not_included": 0,
        "excluded": 0,
        "low_signal": 0,
        "passed": 0,
    })

    for item in items:
        src = item.source
        per_source[src]["input"] += 1

        if spec.require_publish_date and not item.publish_date:
            stats["no_date"] += 1
            per_source[src]["no_date"] += 1
            continue

        if spec.include_patterns and not _matches_inclusion(item, spec.include_patterns):
            stats["not_included"] += 1
            per_source[src]["not_included"] += 1
            continue

        if spec.exclude_patterns and _matches_exclusion(item, spec.exclude_patterns):
            stats["excluded"] += 1
            per_source[src]["excluded"] += 1
            continue

        text = f"{item.title} {item.excerpt or ''}"
        signals = _detect_signals(text)

        if spec.min_detail_signals > 0 and len(signals) < spec.min_detail_signals:
            stats["low_signal"] += 1
            per_source[src]["low_signal"] += 1
            continue

        raw_excerpt = item.excerpt or ""
        result.append(ProcessedItem(
            url=item.url,
            title=item.title,
            source=item.source,
            publish_date=item.publish_date or "",
            excerpt=_truncate_excerpt(raw_excerpt, 120),
            takeaway=_make_takeaway(item.title, raw_excerpt, 60),
            signals=signals,
            url_hash=item.url_hash,
        ))
        stats["passed"] += 1
        per_source[src]["passed"] += 1

    log.info("Filter: %d in -> %d passed (no_date=%d, not_included=%d, excluded=%d, low_signal=%d)",
             stats["input"], stats["passed"], stats["no_date"], stats["not_included"], stats["excluded"], stats["low_signal"])
    return result, stats, dict(per_source)
