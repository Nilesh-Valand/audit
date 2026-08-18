"""Backward-compatible re-exports. Prefer app.crawler.normalize. """

from app.crawler.normalize import (  # noqa: F401
    TRACKING_QUERY_PARAMS,
    canonicalize_crawl_url,
    normalize_url,
    prefer_www_from_seed,
)
