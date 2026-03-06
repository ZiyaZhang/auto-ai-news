"""Two-tier persistent state: dedup water + source health tracking.

Layout:
    state/<task_key>/dedup.json    -- set of seen URL hashes
    state/<task_key>/health.json   -- per-source health records
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)

_STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "state")


def _state_dir(task_key: str) -> str:
    d = os.path.join(_STATE_DIR, task_key)
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Dedup water
# ---------------------------------------------------------------------------

def load_dedup(task_key: str, ttl_days: int | None = None) -> dict[str, str]:
    path = os.path.join(_state_dir(task_key), "dedup.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # v2 format: {"seen": {"hash": "ISO_DATETIME", ...}}
        seen_map = data.get("seen")
        if isinstance(seen_map, dict):
            normalized = {str(h): str(ts) for h, ts in seen_map.items()}
        else:
            # v1 format fallback: {"seen_hashes": [...]}
            legacy = data.get("seen_hashes", [])
            fallback_ts = data.get("updated_at") or datetime.now(timezone.utc).isoformat()
            normalized = {str(h): fallback_ts for h in legacy}

        if ttl_days is None or ttl_days <= 0:
            return normalized

        cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
        kept: dict[str, str] = {}
        for h, ts in normalized.items():
            try:
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except ValueError:
                dt = datetime.now(timezone.utc)
            if dt >= cutoff:
                kept[h] = dt.isoformat()
        return kept
    except Exception:
        log.exception("Failed to load dedup state for %s", task_key)
        return {}


def save_dedup(task_key: str, seen: dict[str, str]) -> None:
    path = os.path.join(_state_dir(task_key), "dedup.json")
    data = {
        "seen": dict(sorted(seen.items())),
        "seen_hashes": sorted(seen.keys()),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(seen),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("Saved dedup state: %d hashes for %s", len(seen), task_key)


# ---------------------------------------------------------------------------
# Source health tracking
# ---------------------------------------------------------------------------

def load_health(task_key: str) -> dict[str, Any]:
    path = os.path.join(_state_dir(task_key), "health.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        log.exception("Failed to load health state for %s", task_key)
        return {}


def record_source_health(
    task_key: str,
    source_id: str,
    success: bool,
    item_count: int = 0,
) -> None:
    """Record a source fetch outcome. Auto-disables after 5 consecutive failures."""
    health = load_health(task_key)
    now = datetime.now(timezone.utc).isoformat()

    entry = health.get(source_id, {
        "consecutive_failures": 0,
        "last_success": None,
        "last_failure": None,
        "disabled": False,
        "total_items_fetched": 0,
    })

    if success:
        entry["consecutive_failures"] = 0
        entry["last_success"] = now
        entry["disabled"] = False
        entry["total_items_fetched"] = entry.get("total_items_fetched", 0) + item_count
    else:
        entry["consecutive_failures"] = entry.get("consecutive_failures", 0) + 1
        entry["last_failure"] = now
        if entry["consecutive_failures"] >= 5:
            entry["disabled"] = True
            log.warning("Source %s disabled after 5 consecutive failures", source_id)

    health[source_id] = entry
    _save_health(task_key, health)


def is_source_disabled(task_key: str, source_id: str) -> bool:
    """Return whether a source is currently marked as disabled."""
    health = load_health(task_key)
    entry = health.get(source_id, {})
    return bool(entry.get("disabled", False))


def _save_health(task_key: str, health: dict[str, Any]) -> None:
    path = os.path.join(_state_dir(task_key), "health.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(health, f, ensure_ascii=False, indent=2)
