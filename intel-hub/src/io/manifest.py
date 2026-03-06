"""Manifest writer: records metadata about each pipeline run."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from src.models import RunManifest


def generate_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def create_manifest(
    task_key: str,
    run_id: str,
    window_days: int,
    sources: list[dict],
) -> RunManifest:
    return RunManifest(
        task_key=task_key,
        run_id=run_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        window_days=window_days,
        sources=sources,
    )


def finalize_manifest(manifest: RunManifest, stats: dict) -> RunManifest:
    manifest.completed_at = datetime.now(timezone.utc).isoformat()
    manifest.stats = stats
    return manifest


def write_manifest(manifest: RunManifest, out_dir: str) -> str:
    path = os.path.join(out_dir, "manifest.json")
    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(manifest.to_json())
    return path
