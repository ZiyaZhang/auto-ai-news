"""Bundle assembler: produces the upload_bundle/ directory for NotebookLM import.

Generates:
  - sources.md   (URL list + one-sentence excerpt per item)
  - items/*.md   (optional: one file per item)
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models import BundleSpec, ProcessedItem


def write_bundle(
    items: list["ProcessedItem"],
    spec: "BundleSpec",
    out_dir: str,
) -> str:
    """Write the upload_bundle/ and return its path."""
    bundle_dir = os.path.join(out_dir, "upload_bundle")
    os.makedirs(bundle_dir, exist_ok=True)

    if spec.include_sources_md:
        _write_sources_md(items, bundle_dir)

    if spec.one_md_per_item:
        _write_per_item(items, bundle_dir)

    return bundle_dir


def _write_sources_md(items: list["ProcessedItem"], bundle_dir: str) -> None:
    lines = ["# Sources\n"]
    for i, item in enumerate(items, 1):
        excerpt = item.excerpt[:80] if item.excerpt else ""
        lines.append(f"{i}. [{item.title}]({item.url})")
        lines.append(f"   - Date: {item.publish_date} | Source: {item.source}")
        if excerpt:
            lines.append(f"   - {excerpt}")
        lines.append("")

    path = os.path.join(bundle_dir, "sources.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_per_item(items: list["ProcessedItem"], bundle_dir: str) -> None:
    items_dir = os.path.join(bundle_dir, "items")
    os.makedirs(items_dir, exist_ok=True)
    for i, item in enumerate(items, 1):
        safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in item.title)[:60]
        filename = f"{i:03d}_{safe_title}.md"
        content = (
            f"# {item.title}\n\n"
            f"- URL: {item.url}\n"
            f"- Date: {item.publish_date}\n"
            f"- Source: {item.source}\n"
            f"- Score: {item.score}\n"
            f"- Signals: {', '.join(item.signals) if item.signals else 'none'}\n\n"
            f"{item.excerpt}\n"
        )
        path = os.path.join(items_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


def write_items_json(items: list["ProcessedItem"], out_dir: str) -> str:
    """Write items.json with all processed items."""
    path = os.path.join(out_dir, "items.json")
    os.makedirs(out_dir, exist_ok=True)
    data = [item.to_dict() for item in items]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path
