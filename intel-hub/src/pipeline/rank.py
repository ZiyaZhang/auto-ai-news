"""Scoring and ranking of processed items.

Score = source_weight
      + min(detail_signal_bonus * len(signals), signal_cap)
      + multi_source_bonus  (if same URL seen from >1 source)
      + freshness_bonus     (today / yesterday get a bump)
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from src.models import ProcessedItem

if TYPE_CHECKING:
    from src.models import RankingSpec

log = logging.getLogger(__name__)

_SIGNAL_BONUS_CAP = 0.3


def _source_weight(item: ProcessedItem, weight_map: dict[str, float]) -> float:
    """Match item source/URL domain against the weight map."""
    domain = urlparse(item.url).netloc.lower()
    for pattern, w in weight_map.items():
        if pattern in domain or pattern.lower() == item.source.lower():
            return w
    return 1.0


def _freshness_bonus(item: ProcessedItem) -> float:
    """Reward items published in the last 48h."""
    if not item.publish_date:
        return 0.0
    try:
        pub = datetime.strptime(item.publish_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.0
    age_days = (datetime.now(timezone.utc) - pub).days
    if age_days <= 1:
        return 0.3
    if age_days <= 3:
        return 0.15
    return 0.0


def rank_items(
    items: list[ProcessedItem],
    spec: "RankingSpec",
) -> list[ProcessedItem]:
    """Score and sort items descending by score."""
    url_counts: Counter[str] = Counter()
    for it in items:
        url_counts[it.url_hash] += 1

    for item in items:
        score = _source_weight(item, spec.source_weight_map)
        signal_bonus = spec.detail_signal_bonus * len(item.signals)
        score += min(signal_bonus, _SIGNAL_BONUS_CAP)
        if url_counts[item.url_hash] > 1:
            score += spec.multi_source_bonus
        score += _freshness_bonus(item)
        item.score = round(score, 3)

    items.sort(key=lambda x: (x.score, x.publish_date), reverse=True)

    log.info("Rank: scored %d items, top score=%.2f", len(items),
             items[0].score if items else 0.0)
    return items
