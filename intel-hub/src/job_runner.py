#!/usr/bin/env python3
"""Intel-hub pipeline runner.

Usage:
    python3 -m src.job_runner <task_key> [--run-id ID] [--jobs-dir DIR] [--no-state]

Reads jobs/<task_key>.yml, runs the full pipeline, and writes output to
out/<task_key>/<run_id>/.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone

import yaml

# Ensure the intel-hub root is on sys.path so "src.*" imports work.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.fetchers import fetch_source
from src.io.bundle import write_bundle, write_items_json
from src.io.manifest import create_manifest, finalize_manifest, generate_run_id, write_manifest
from src.io.state_store import is_source_disabled, load_dedup, record_source_health, save_dedup
from src.models import JobSpec
from src.pipeline.dedup import dedup
from src.pipeline.filter import filter_items
from src.pipeline.rank import rank_items
from src.render.engine import render_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("job_runner")


def load_job_spec(task_key: str, jobs_dir: str) -> JobSpec:
    path = os.path.join(jobs_dir, f"{task_key}.yml")
    if not os.path.exists(path):
        path = os.path.join(jobs_dir, f"{task_key}.yaml")
    if not os.path.exists(path):
        log.error("Job spec not found: %s", path)
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    return JobSpec.from_dict(raw)


def run_pipeline(task_key: str, run_id: str | None = None, jobs_dir: str | None = None, use_state: bool = True) -> str:
    """Execute the full pipeline and return the output directory path."""
    jobs_dir = jobs_dir or os.path.join(_ROOT, "jobs")
    spec = load_job_spec(task_key, jobs_dir)
    run_id = run_id or generate_run_id()
    out_dir = os.path.join(_ROOT, "out", task_key, run_id)
    os.makedirs(out_dir, exist_ok=True)

    log.info("=== Pipeline start: %s / %s ===", task_key, run_id)

    source_dicts = [asdict(s) for s in spec.sources]
    manifest = create_manifest(task_key, run_id, spec.time_window_days, source_dicts)

    # Preserve per-source weights from jobs YAML as fallback ranking weights.
    for source_spec in spec.sources:
        label = source_spec.label or source_spec.url or source_spec.query or source_spec.type
        if label and label not in spec.ranking.source_weight_map:
            spec.ranking.source_weight_map[label] = source_spec.weight

    # ── Step 1: Fetch ──
    all_raw = []
    for source_spec in spec.sources:
        source_id = source_spec.label or source_spec.url or source_spec.query or source_spec.type
        if is_source_disabled(task_key, source_id):
            log.warning("Skipping disabled source: %s", source_id)
            continue
        log.info("Fetching: %s (%s)", source_id, source_spec.type)
        items = fetch_source(source_spec, spec.time_window_days)
        record_source_health(task_key, source_id, success=len(items) > 0, item_count=len(items))
        all_raw.extend(items)
    log.info("Total raw items: %d", len(all_raw))

    # ── Step 2: Dedup ──
    if use_state:
        seen_hashes_with_ts = load_dedup(task_key, ttl_days=spec.dedup_ttl_days)
    else:
        seen_hashes_with_ts = {}
    seen_hashes = set(seen_hashes_with_ts.keys())
    dedup_waterline_before = len(seen_hashes)

    deduped, new_hashes = dedup(all_raw, seen_hashes)
    log.info("After dedup: %d items", len(deduped))

    # ── Step 3: Filter ──
    processed, filter_stats, filter_by_source = filter_items(deduped, spec.filters)
    log.info("After filter: %d items", len(processed))

    # ── Step 4: Rank ──
    ranked = rank_items(processed, spec.ranking)

    # ── Step 5: Build run stats ──
    filtered_out_total = (
        filter_stats.get("no_date", 0)
        + filter_stats.get("not_included", 0)
        + filter_stats.get("excluded", 0)
        + filter_stats.get("low_signal", 0)
    )
    fetched_by_source = Counter(item.source for item in all_raw)
    deduped_by_source = Counter(item.source for item in deduped)
    final_by_source = Counter(item.source for item in ranked)

    all_source_labels = []
    for src in source_dicts:
        label = src.get("label") or src.get("url") or src.get("query") or str(src)
        all_source_labels.append(label)
    all_source_labels = sorted(
        set(all_source_labels)
        | set(fetched_by_source.keys())
        | set(deduped_by_source.keys())
        | set(final_by_source.keys())
    )

    per_source_stats = {}
    for src in all_source_labels:
        fetched = fetched_by_source.get(src, 0)
        dedup_kept = deduped_by_source.get(src, 0)
        dedup_dropped = max(0, fetched - dedup_kept)

        fstats = filter_by_source.get(src, {})
        filter_input = fstats.get("input", dedup_kept)
        filter_passed = fstats.get("passed", 0)
        filter_dropped = max(0, filter_input - filter_passed)

        per_source_stats[src] = {
            "fetched": fetched,
            "dedup_kept": dedup_kept,
            "dedup_dropped": dedup_dropped,
            "filter_input": filter_input,
            "filter_dropped": filter_dropped,
            "filter_reasons": {
                "no_date": fstats.get("no_date", 0),
                "not_included": fstats.get("not_included", 0),
                "excluded": fstats.get("excluded", 0),
                "low_signal": fstats.get("low_signal", 0),
            },
            "final": final_by_source.get(src, 0),
        }

    stats = {
        "fetched": len(all_raw),
        "deduped": len(all_raw) - len(deduped),
        "filtered_out": filtered_out_total,
        "final": len(ranked),
        "dedup_ttl_days": spec.dedup_ttl_days,
        "dedup_waterline_before": dedup_waterline_before,
        "dedup_waterline_after": dedup_waterline_before + len(new_hashes),
        "filter_breakdown": {
            "no_date": filter_stats.get("no_date", 0),
            "not_included": filter_stats.get("not_included", 0),
            "excluded": filter_stats.get("excluded", 0),
            "low_signal": filter_stats.get("low_signal", 0),
        },
        "per_source": per_source_stats,
    }

    # ── Step 6: Render report ──
    render_report(
        items=ranked,
        kind=spec.report.kind,
        task_key=task_key,
        run_id=run_id,
        window_days=spec.time_window_days,
        configured_sources=source_dicts,
        run_stats=stats,
        language=spec.report.language,
        out_dir=out_dir,
    )

    # ── Step 7: Write bundle + items.json ──
    write_bundle(ranked, spec.bundle, out_dir)
    write_items_json(ranked, out_dir)

    # ── Step 8: Manifest ──
    manifest = finalize_manifest(manifest, stats)
    write_manifest(manifest, out_dir)

    # ── Step 9: Persist state ──
    if use_state:
        now = datetime.now(timezone.utc).isoformat()
        for h in new_hashes:
            seen_hashes_with_ts[h] = now
        save_dedup(task_key, seen_hashes_with_ts)

    log.info("=== Pipeline complete: %s ===", out_dir)
    log.info("Stats: %s", json.dumps(stats))
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Intel-hub pipeline runner")
    parser.add_argument("task_key", help="Task key matching a YAML file in jobs/")
    parser.add_argument("--run-id", default=None, help="Override run ID (default: timestamp)")
    parser.add_argument("--jobs-dir", default=None, help="Override jobs directory")
    parser.add_argument("--no-state", action="store_true", help="Disable dedup state persistence")
    args = parser.parse_args()

    out_dir = run_pipeline(
        task_key=args.task_key,
        run_id=args.run_id,
        jobs_dir=args.jobs_dir,
        use_state=not args.no_state,
    )
    print(f"\nOutput: {out_dir}")


if __name__ == "__main__":
    main()
