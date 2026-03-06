"""Core data models for the intel-hub pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode


_TRACKING_PARAMS = re.compile(
    r"^(utm_|fbclid|gclid|mc_|yclid|_ga|ref|source|campaign|medium|"
    r"ncid|ocid|mkt_tok|s_cid|hss_channel)",
    re.I,
)


def normalize_url(url: str) -> str:
    """Strip tracking params, fragments, and trailing slashes for stable dedup."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=False)
    clean = {k: v for k, v in params.items() if not _TRACKING_PARAMS.match(k)}
    qs = urlencode(clean, doseq=True) if clean else ""
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", qs, ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Raw item: output of a fetcher, before any processing
# ---------------------------------------------------------------------------

@dataclass
class RawItem:
    url: str
    title: str
    source: str
    publish_date: str | None  # YYYY-MM-DD or None (hard-drop if None)
    excerpt: str | None = None
    raw_html: str | None = None
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def url_hash(self) -> str:
        return url_hash(self.url)


# ---------------------------------------------------------------------------
# Processed item: survived date-gate, dedup, filtering, and scoring
# ---------------------------------------------------------------------------

@dataclass
class ProcessedItem:
    url: str
    title: str
    source: str
    publish_date: str  # YYYY-MM-DD guaranteed
    excerpt: str       # <=120 chars — summary
    takeaway: str = "" # <=60 chars — "what happened" insight
    signals: list[str] = field(default_factory=list)
    score: float = 0.0
    url_hash: str = ""

    def __post_init__(self):
        if not self.url_hash:
            self.url_hash = url_hash(self.url)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Run manifest: metadata about a single pipeline execution
# ---------------------------------------------------------------------------

VERSION = "0.1.0"


@dataclass
class RunManifest:
    task_key: str
    run_id: str
    started_at: str
    completed_at: str = ""
    window_days: int = 7
    sources: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    version: str = VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, **kw) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, **kw)


# ---------------------------------------------------------------------------
# Job spec: typed representation of a jobs/<task_key>.yml file
# ---------------------------------------------------------------------------

@dataclass
class SourceSpec:
    type: str  # rss | html_list | arxiv | manual_urls | sitemap
    url: str | None = None
    urls: list[str] | None = None
    query: str | None = None
    weight: float = 1.0
    label: str | None = None


@dataclass
class FilterSpec:
    require_publish_date: bool = True
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    min_detail_signals: int = 0


@dataclass
class RankingSpec:
    source_weight_map: dict[str, float] = field(default_factory=dict)
    multi_source_bonus: float = 0.3
    detail_signal_bonus: float = 0.2


@dataclass
class ReportSpec:
    kind: str = "weekly_intel"  # weekly_intel | investment_memo | company_dossier
    language: str = "zh"
    sections: list[str] | None = None


@dataclass
class BundleSpec:
    include_sources_md: bool = True
    include_pdf: bool = False
    one_md_per_item: bool = False


@dataclass
class OutputChannelSpec:
    type: str  # local | notion | notebooklm
    importance: str | None = None


@dataclass
class JobSpec:
    task_key: str
    time_window_days: int = 7
    dedup_ttl_days: int = 45
    sources: list[SourceSpec] = field(default_factory=list)
    filters: FilterSpec = field(default_factory=FilterSpec)
    ranking: RankingSpec = field(default_factory=RankingSpec)
    report: ReportSpec = field(default_factory=ReportSpec)
    bundle: BundleSpec = field(default_factory=BundleSpec)
    output_channels: list[OutputChannelSpec] = field(default_factory=lambda: [
        OutputChannelSpec(type="local"),
    ])

    @staticmethod
    def from_dict(d: dict[str, Any]) -> JobSpec:
        """Parse a raw dict (from YAML) into a typed JobSpec."""
        sources = [SourceSpec(**s) for s in d.get("sources", [])]
        filters = FilterSpec(**d.get("filters", {}))
        ranking = RankingSpec(**d.get("ranking", {}))
        report = ReportSpec(**d.get("report", {}))
        bundle = BundleSpec(**d.get("bundle", {}))
        channels = [OutputChannelSpec(**c) for c in d.get("output_channels", [{"type": "local"}])]

        return JobSpec(
            task_key=d["task_key"],
            time_window_days=d.get("time_window_days", 7),
            dedup_ttl_days=d.get("dedup_ttl_days", 45),
            sources=sources,
            filters=filters,
            ranking=ranking,
            report=report,
            bundle=bundle,
            output_channels=channels,
        )
