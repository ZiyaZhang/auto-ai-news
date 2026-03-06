"""Jinja2-based report renderer.

Loads templates from intel-hub/templates/ and renders reports from processed
items + metadata.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from jinja2 import Environment, FileSystemLoader

from src.io.state_store import load_health
from src.models import ProcessedItem, VERSION

log = logging.getLogger(__name__)

_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates")

_TEMPLATE_MAP = {
    "weekly_intel": "weekly_intel.md.j2",
    "investment_memo": "investment_memo.md.j2",
    "company_dossier": "investment_memo.md.j2",  # reuse investment memo for now
}


def _build_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _detect_themes(items: list[ProcessedItem], max_themes: int = 6) -> list[dict[str, Any]]:
    """Simple keyword-based theme clustering."""
    theme_keywords: dict[str, list[str]] = {
        "大模型与推理": ["llm", "gpt", "claude", "gemini", "reasoning", "chain-of-thought", "inference", "context window", "token", "deepseek"],
        "多模态与生成": ["multimodal", "vision", "image", "video", "diffusion", "text-to", "speech", "audio", "sora"],
        "Agent 与工具": ["agent", "tool use", "function call", "mcp", "autogen", "langchain", "workflow", "orchestrat"],
        "基准与评测": ["benchmark", "leaderboard", "arena", "eval", "mmlu", "humaneval", "score", "sota", "mlperf"],
        "安全与对齐": ["safety", "alignment", "rlhf", "red team", "guardrail", "jailbreak", "responsible", "regulation", "nist", "aisi"],
        "基础设施与芯片": ["gpu", "tpu", "chip", "nvidia", "h100", "b200", "inference server", "training cluster", "hardware"],
        "开源与社区": ["open source", "open weight", "hugging face", "github", "license", "community", "release"],
        "融资与商业": ["funding", "acquisition", "valuation", "series", "revenue", "partnership", "enterprise", "pricing"],
    }

    theme_items: dict[str, list[ProcessedItem]] = defaultdict(list)
    for item in items:
        text = f"{item.title} {item.excerpt}".lower()
        for theme_name, keywords in theme_keywords.items():
            if any(kw in text for kw in keywords):
                theme_items[theme_name].append(item)
                break

    themes = []
    for name, titems in sorted(theme_items.items(), key=lambda x: -len(x[1])):
        if len(titems) < 1:
            continue
        themes.append({
            "name": name,
            "summary": f"本周期共 {len(titems)} 条与「{name}」相关的更新。",
            "refs": titems[:5],
        })
        if len(themes) >= max_themes:
            break

    return themes


def _detect_silent_sources(
    run_stats: dict[str, Any],
    configured_sources: list[dict],
) -> list[dict[str, str | int]]:
    """Find configured sources with zero final items and classify the reason."""
    per_source = run_stats.get("per_source", {}) if isinstance(run_stats, dict) else {}
    silent = []
    for src in configured_sources:
        label = src.get("label") or src.get("url") or src.get("query") or str(src)
        stats = per_source.get(label, {})
        if stats.get("final", 0) > 0:
            continue

        fetched = int(stats.get("fetched", 0))
        dedup_dropped = int(stats.get("dedup_dropped", 0))
        filter_dropped = int(stats.get("filter_dropped", 0))

        if fetched == 0:
            reason = "抓取为空/失败"
        elif dedup_dropped >= fetched and filter_dropped == 0:
            reason = "全部被去重"
        elif filter_dropped > 0:
            reason = "全部被过滤"
        else:
            reason = "无新增入选"

        silent.append({
            "name": label,
            "reason": reason,
            "fetched": fetched,
            "dedup_dropped": dedup_dropped,
            "filter_dropped": filter_dropped,
        })
    return silent


def _source_health_alerts(task_key: str, threshold: int = 3) -> list[dict[str, Any]]:
    health = load_health(task_key)
    alerts = []
    for source_id, entry in health.items():
        failures = int(entry.get("consecutive_failures", 0))
        disabled = bool(entry.get("disabled", False))
        if failures < threshold and not disabled:
            continue
        alerts.append({
            "name": source_id,
            "failures": failures,
            "disabled": disabled,
            "last_failure": entry.get("last_failure"),
        })
    alerts.sort(key=lambda x: (x["disabled"], x["failures"]), reverse=True)
    return alerts


def render_report(
    items: list[ProcessedItem],
    kind: str,
    task_key: str,
    run_id: str,
    window_days: int,
    configured_sources: list[dict],
    run_stats: dict[str, Any] | None = None,
    language: str = "zh",
    out_dir: str | None = None,
) -> str:
    """Render a report and optionally write to out_dir/report.md. Returns the text."""
    env = _build_env()
    template_name = _TEMPLATE_MAP.get(kind, "weekly_intel.md.j2")
    template = env.get_template(template_name)

    now = datetime.now(timezone.utc)
    top_n = min(5, len(items))
    run_stats = run_stats or {}
    active_source_count = len(set(item.source for item in items))

    context: dict[str, Any] = {
        "title": task_key.replace("_", " ").title(),
        "task_key": task_key,
        "run_id": run_id,
        "window_start": (now - timedelta(days=window_days)).strftime("%Y-%m-%d"),
        "window_end": now.strftime("%Y-%m-%d"),
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "configured_source_count": len(configured_sources),
        "active_source_count": active_source_count,
        "item_count": len(items),
        "top_n": top_n,
        "top_items": items[:top_n],
        "items": items,
        "themes": _detect_themes(items),
        "silent_sources": _detect_silent_sources(run_stats, configured_sources),
        "source_health_alerts": _source_health_alerts(task_key),
        "version": VERSION,
    }

    text = template.render(**context)

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "report.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        log.info("Report written to %s", path)

    return text
