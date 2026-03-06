"""Deduplication using URL-hash water level from persistent state."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models import RawItem

log = logging.getLogger(__name__)


def dedup(items: list["RawItem"], seen_hashes: set[str]) -> tuple[list["RawItem"], set[str]]:
    """Remove items whose URL hash is already in *seen_hashes*.

    Returns (new_items, new_hashes_to_add).
    """
    kept: list["RawItem"] = []
    new_hashes: set[str] = set()

    for item in items:
        h = item.url_hash
        if h in seen_hashes:
            continue
        if h in new_hashes:
            continue
        new_hashes.add(h)
        kept.append(item)

    dropped = len(items) - len(kept)
    if dropped:
        log.info("Dedup: dropped %d duplicates, kept %d", dropped, len(kept))
    return kept, new_hashes
