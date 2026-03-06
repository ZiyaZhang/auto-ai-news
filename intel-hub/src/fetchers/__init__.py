"""Fetcher plugin registry.

Every fetcher module auto-registers by importing this package and calling
``register()``.  The job runner only needs::

    from src.fetchers import fetch_source
    items = fetch_source(source_spec, window_days)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from src.models import RawItem, SourceSpec

log = logging.getLogger(__name__)

FetchFunc = Callable[["SourceSpec", int], list["RawItem"]]

_REGISTRY: dict[str, FetchFunc] = {}


def register(source_type: str, func: FetchFunc) -> None:
    _REGISTRY[source_type] = func


def fetch_source(spec: "SourceSpec", window_days: int) -> list["RawItem"]:
    func = _REGISTRY.get(spec.type)
    if func is None:
        log.warning("No fetcher registered for source type '%s'", spec.type)
        return []
    try:
        return func(spec, window_days)
    except Exception:
        log.exception("Fetcher '%s' failed for %s", spec.type, spec.url or spec.urls)
        return []


# Side-effect imports: each module registers itself on import.
from src.fetchers import rss as _rss       # noqa: F401,E402
from src.fetchers import html_list as _hl   # noqa: F401,E402
from src.fetchers import arxiv as _arx      # noqa: F401,E402
from src.fetchers import manual as _man     # noqa: F401,E402
from src.fetchers import sitemap as _sm    # noqa: F401,E402
