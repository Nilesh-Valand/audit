"""CROSS_PAGE-scoped check runner — once per crawl after crawl_pages is populated.

Operates on the full page set (group-by title/meta/content, internal link graph,
canonical target lookups against other crawled pages). Writes one site_issues
row per *issue found* (e.g. one duplicate-title group → one row listing the
offending URLs). Never writes one row per URL for group findings.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.checks.registry import Scope, checks_for_scope, severity_default_for
from app.config import settings
from app.crawler.normalize import normalize_url
from app.db.database import SessionLocal
from app.models import CrawlPage, SiteIssue

logger = logging.getLogger(__name__)

KEYWORD_CANNIBALIZATION_THRESHOLD = 0.8
_PAGINATION_QUERY_KEYS = {"page", "p", "paged", "offset", "start"}
_PAGINATION_PATH_RE = re.compile(r"/page/\d+/?$", re.IGNORECASE)
_URL_SAMPLE_LIMIT = 8


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CheckOutcome:
    """One failing (or informational) finding produced by a CROSS_PAGE check."""

    status: str  # "pass" | "fail"
    details: str
    severity: str | None = None


@dataclass(slots=True)
class CrossPageIssueWrite:
    check_name: str
    status: str
    details: str
    severity: str


@dataclass(slots=True)
class CanonicalProbe:
    url: str
    malformed: bool = False
    status_code: int | None = None
    is_redirect: bool = False
    error: str | None = None


@dataclass(slots=True)
class CrossPageSnapshot:
    """In-memory view of one crawl_pages row for cross-page analysis."""

    id: int
    url: str
    status_code: int | None
    title: str | None
    meta_description: str | None
    canonical: str | None
    meta_robots: str | None
    h1: str | None
    word_count: int | None
    redirect_hops: int
    is_indexable: bool
    raw_html_path: str | None
    outgoing_internal: list[str] = field(default_factory=list)
    text_hash: str | None = None
    inbound_internal: int = 0


@dataclass(slots=True)
class CrossPageContext:
    """Full-crawl signals shared by every CROSS_PAGE check."""

    pages: list[CrossPageSnapshot]
    by_normalized_url: dict[str, CrossPageSnapshot]
    sitemap_urls: set[str] = field(default_factory=set)
    """Optional normalized sitemap URL set (for crawl↔sitemap comparisons)."""
    _probe_cache: dict[str, CanonicalProbe] = field(default_factory=dict)


CrossPageCheckFn = Callable[[CrossPageContext], list[CheckOutcome]]


# ---------------------------------------------------------------------------
# Load from crawl_pages (no re-crawl of HTML pages)
# ---------------------------------------------------------------------------


def load_cross_page_context(
    crawl_id: int,
    *,
    sitemap_urls: set[str] | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> CrossPageContext:
    """Load every crawl_pages row + internal links for this crawl."""
    factory = session_factory or SessionLocal
    with factory() as db:
        pages = (
            db.scalars(
                select(CrawlPage)
                .where(CrawlPage.crawl_id == crawl_id)
                .options(joinedload(CrawlPage.links))
                .order_by(CrawlPage.id.asc())
            )
            .unique()
            .all()
        )

        snapshots: list[CrossPageSnapshot] = []
        seen: set[str] = set()
        for page in pages:
            key = normalize_url(page.url)
            if key in seen:
                continue
            seen.add(key)
            outgoing = [
                link.target_url
                for link in page.links
                if link.is_internal and link.target_url
            ]
            snap = CrossPageSnapshot(
                id=page.id,
                url=page.url,
                status_code=page.status_code,
                title=page.title,
                meta_description=page.meta_description,
                canonical=page.canonical,
                meta_robots=page.meta_robots,
                h1=page.h1,
                word_count=page.word_count,
                redirect_hops=page.redirect_hops or 0,
                is_indexable=bool(page.is_indexable),
                raw_html_path=page.raw_html_path,
                outgoing_internal=outgoing,
                text_hash=_content_hash_from_path(page.raw_html_path),
            )
            snapshots.append(snap)

        by_url = {normalize_url(p.url): p for p in snapshots}
        inbound: dict[str, int] = defaultdict(int)
        for page in snapshots:
            source = normalize_url(page.url)
            for target in page.outgoing_internal:
                dest = normalize_url(target)
                if dest == source:
                    continue
                if dest in by_url:
                    inbound[dest] += 1
        for page in snapshots:
            page.inbound_internal = inbound.get(normalize_url(page.url), 0)

        return CrossPageContext(
            pages=snapshots,
            by_normalized_url=by_url,
            sitemap_urls=set(sitemap_urls or ()),
        )


def _content_hash_from_path(raw_html_path: str | None) -> str | None:
    if not raw_html_path:
        return None
    path = Path(raw_html_path)
    if not path.exists():
        return None
    try:
        html = path.read_text(encoding="utf-8")
    except OSError:
        return None
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.extract()
    text = " ".join(soup.get_text(" ", strip=True).split())
    if len(text.split()) < 50:
        return None
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fail(details: str, *, severity: str | None = None) -> CheckOutcome:
    return CheckOutcome(status="fail", details=details, severity=severity)


def _format_urls(urls: list[str], *, limit: int = _URL_SAMPLE_LIMIT) -> str:
    ordered = sorted(urls)
    sample = ordered[:limit]
    extra = len(ordered) - len(sample)
    text = ", ".join(sample)
    if extra > 0:
        text += f" (+{extra} more)"
    return text


def _is_likely_html_document(page: CrossPageSnapshot) -> bool:
    if page.status_code is not None and page.status_code >= 400:
        return False
    return True


def _is_malformed_url(url: str) -> bool:
    cleaned = (url or "").strip()
    if not cleaned:
        return True
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"}:
        return True
    if not parsed.netloc:
        return True
    return False


def _is_pagination_canonical(page_url: str, canonical_url: str) -> bool:
    page_parsed = urlparse(page_url)
    canon_parsed = urlparse(canonical_url)
    page_qs = parse_qs(page_parsed.query, keep_blank_values=False)
    canon_qs = parse_qs(canon_parsed.query, keep_blank_values=False)

    for key in _PAGINATION_QUERY_KEYS:
        if key not in page_qs:
            continue
        try:
            page_n = int(str(page_qs[key][0]))
        except (TypeError, ValueError):
            continue
        if page_n <= 1:
            continue
        if key not in canon_qs:
            return True
        try:
            canon_n = int(str(canon_qs[key][0]))
        except (TypeError, ValueError):
            continue
        if canon_n == 1:
            return True

    if _PAGINATION_PATH_RE.search(page_parsed.path or ""):
        canon_path = canon_parsed.path or ""
        if not _PAGINATION_PATH_RE.search(canon_path):
            return True
        if re.search(r"/page/1/?$", canon_path, re.IGNORECASE):
            return True
    return False


def _is_homepage(page: CrossPageSnapshot) -> bool:
    parsed = urlparse(page.url)
    path = parsed.path or "/"
    return path in {"", "/"} and not parsed.query


def _probe_canonical_target(ctx: CrossPageContext, url: str) -> CanonicalProbe:
    cache_key = normalize_url(url) or url.strip()
    cached = ctx._probe_cache.get(cache_key)
    if cached is not None:
        return cached

    if _is_malformed_url(url):
        probe = CanonicalProbe(url=url, malformed=True)
        ctx._probe_cache[cache_key] = probe
        return probe

    headers = {"User-Agent": settings.CRAWLER_USER_AGENT}
    timeout = httpx.Timeout(15.0, connect=8.0)
    try:
        with httpx.Client(
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
        ) as client:
            response = client.head(url)
            if response.status_code in {405, 501}:
                response = client.get(url)
            status = response.status_code
            probe = CanonicalProbe(
                url=url,
                status_code=status,
                is_redirect=300 <= status < 400,
            )
    except Exception as exc:  # noqa: BLE001 — probe isolation
        logger.debug("Canonical target probe failed for %s: %s", url, exc)
        probe = CanonicalProbe(url=url, error=str(exc))

    ctx._probe_cache[cache_key] = probe
    return probe


def _intent_tokens(title: str | None, h1: str | None) -> set[str]:
    text = f"{title or ''} {h1 or ''}".lower()
    tokens = {token for token in re.findall(r"[a-z0-9]{3,}", text)}
    stop = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "your",
        "our",
        "this",
        "that",
        "page",
        "home",
        "best",
        "guide",
    }
    return {token for token in tokens if token not in stop}


def _token_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    union = len(left | right)
    return intersection / union if union else 0.0


def _connected_components(edges: list[tuple[str, str]]) -> list[set[str]]:
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for a, b in edges:
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        union(a, b)

    groups: dict[str, set[str]] = defaultdict(set)
    for node in parent:
        groups[find(node)].add(node)
    return list(groups.values())


# ---------------------------------------------------------------------------
# Individual CROSS_PAGE check functions
# ---------------------------------------------------------------------------


def check_duplicate_title(ctx: CrossPageContext) -> list[CheckOutcome]:
    return _duplicate_text_issues(
        ctx.pages,
        lambda page: page.title,
        "Duplicate title ({count} pages): {urls}",
    )


def check_duplicate_meta_description(ctx: CrossPageContext) -> list[CheckOutcome]:
    return _duplicate_text_issues(
        ctx.pages,
        lambda page: page.meta_description,
        "Duplicate meta description ({count} pages): {urls}",
    )


def check_duplicate_content(ctx: CrossPageContext) -> list[CheckOutcome]:
    groups: dict[str, list[CrossPageSnapshot]] = defaultdict(list)
    for page in ctx.pages:
        if page.text_hash:
            groups[page.text_hash].append(page)

    outcomes: list[CheckOutcome] = []
    for group in groups.values():
        urls = sorted({p.url for p in group})
        if len(urls) < 2:
            continue
        outcomes.append(
            _fail(
                f"Duplicate content hash across {len(urls)} pages: {_format_urls(urls)}."
            )
        )
    return outcomes


def check_keyword_cannibalization(ctx: CrossPageContext) -> list[CheckOutcome]:
    candidates = [
        page
        for page in ctx.pages
        if page.is_indexable
        and (page.status_code is None or page.status_code < 400)
        and ((page.title or "").strip() or (page.h1 or "").strip())
    ]
    edges: list[tuple[str, str]] = []
    for index, left in enumerate(candidates):
        left_tokens = _intent_tokens(left.title, left.h1)
        if len(left_tokens) < 2:
            continue
        for right in candidates[index + 1 :]:
            right_tokens = _intent_tokens(right.title, right.h1)
            if len(right_tokens) < 2:
                continue
            if _token_overlap(left_tokens, right_tokens) < KEYWORD_CANNIBALIZATION_THRESHOLD:
                continue
            edges.append((left.url, right.url))

    outcomes: list[CheckOutcome] = []
    for cluster in _connected_components(edges):
        if len(cluster) < 2:
            continue
        urls = sorted(cluster)
        outcomes.append(
            _fail(
                "Keyword cannibalization risk — title/H1 text is highly similar across "
                f"{len(urls)} pages: {_format_urls(urls)}."
            )
        )
    return outcomes


def check_orphan_page(ctx: CrossPageContext) -> list[CheckOutcome]:
    orphans = [
        page.url
        for page in ctx.pages
        if page.inbound_internal == 0 and not _is_homepage(page)
    ]
    if not orphans:
        return []
    # One site-level finding listing every orphan URL (not one row per URL).
    return [
        _fail(
            f"{len(orphans)} orphan page(s) have no inbound internal links from other "
            f"crawled pages: {_format_urls(orphans)}."
        )
    ]


def check_missing_canonical(ctx: CrossPageContext) -> list[CheckOutcome]:
    missing = [
        page.url
        for page in ctx.pages
        if _is_likely_html_document(page) and not (page.canonical or "").strip()
    ]
    if not missing:
        return []
    return [
        _fail(
            f"{len(missing)} page(s) are missing a <link rel=\"canonical\"> tag: "
            f"{_format_urls(missing)}."
        )
    ]


def check_self_canonical_mismatch(ctx: CrossPageContext) -> list[CheckOutcome]:
    mismatches: list[str] = []
    for page in ctx.pages:
        raw = (page.canonical or "").strip()
        if not raw or not _is_likely_html_document(page):
            continue
        if _is_malformed_url(raw):
            continue
        page_norm = normalize_url(page.url)
        canon_norm = normalize_url(raw)
        if not canon_norm or page_norm == canon_norm:
            continue
        if _is_pagination_canonical(page_norm, canon_norm):
            continue
        mismatches.append(f"{page.url} → {canon_norm}")
    if not mismatches:
        return []
    return [
        _fail(
            f"{len(mismatches)} page(s) have a canonical that does not match their own "
            f"URL: {_format_urls(mismatches)}."
        )
    ]


def check_broken_canonical_url(ctx: CrossPageContext) -> list[CheckOutcome]:
    broken: list[str] = []
    for page in ctx.pages:
        raw = (page.canonical or "").strip()
        if not raw or not _is_likely_html_document(page):
            continue
        if _is_malformed_url(raw):
            broken.append(f"{page.url} (malformed: {raw})")
            continue

        canon_norm = normalize_url(raw)
        target = ctx.by_normalized_url.get(canon_norm)
        if target is not None:
            status = target.status_code
            if status is not None and status >= 400:
                broken.append(f"{page.url} → {canon_norm} ({status})")
            continue

        probe = _probe_canonical_target(ctx, raw)
        if probe.malformed:
            broken.append(f"{page.url} (malformed: {raw})")
            continue
        if (
            probe.status_code is not None
            and probe.status_code >= 400
            and not probe.is_redirect
        ):
            broken.append(f"{page.url} → {canon_norm} ({probe.status_code})")
    if not broken:
        return []
    return [
        _fail(
            f"{len(broken)} page(s) have a broken or malformed canonical target: "
            f"{_format_urls(broken)}."
        )
    ]


def check_canonical_points_to_redirect(ctx: CrossPageContext) -> list[CheckOutcome]:
    redirected: list[str] = []
    for page in ctx.pages:
        raw = (page.canonical or "").strip()
        if not raw or not _is_likely_html_document(page):
            continue
        if _is_malformed_url(raw):
            continue

        canon_norm = normalize_url(raw)
        target = ctx.by_normalized_url.get(canon_norm)
        if target is not None:
            if target.redirect_hops >= 1:
                redirected.append(
                    f"{page.url} → {canon_norm} ({target.redirect_hops} hop(s))"
                )
            continue

        probe = _probe_canonical_target(ctx, raw)
        if probe.is_redirect and probe.status_code is not None:
            redirected.append(
                f"{page.url} → {canon_norm} (HTTP {probe.status_code})"
            )
    if not redirected:
        return []
    return [
        _fail(
            f"{len(redirected)} page(s) canonicalize to a URL that redirects: "
            f"{_format_urls(redirected)}."
        )
    ]


def check_canonical_points_to_noindex(ctx: CrossPageContext) -> list[CheckOutcome]:
    bad: list[str] = []
    for page in ctx.pages:
        raw = (page.canonical or "").strip()
        if not raw or not _is_likely_html_document(page):
            continue
        if _is_malformed_url(raw):
            continue

        canon_norm = normalize_url(raw)
        target = ctx.by_normalized_url.get(canon_norm)
        if target is None:
            continue
        if normalize_url(target.url) == normalize_url(page.url):
            continue
        if "noindex" not in (target.meta_robots or "").lower():
            continue
        bad.append(f"{page.url} → {canon_norm}")
    if not bad:
        return []
    return [
        _fail(
            f"{len(bad)} page(s) canonicalize to a noindex target: "
            f"{_format_urls(bad)}."
        )
    ]


def _duplicate_text_issues(
    pages: list[CrossPageSnapshot],
    value_getter: Callable[[CrossPageSnapshot], str | None],
    template: str,
) -> list[CheckOutcome]:
    groups: dict[str, list[CrossPageSnapshot]] = defaultdict(list)
    for page in pages:
        value = (value_getter(page) or "").strip().lower()
        if value:
            groups[value].append(page)

    outcomes: list[CheckOutcome] = []
    for group in groups.values():
        urls = sorted({p.url for p in group})
        if len(urls) < 2:
            continue
        outcomes.append(
            _fail(
                template.format(count=len(urls), urls=_format_urls(urls)) + "."
            )
        )
    return outcomes


CROSS_PAGE_CHECK_HANDLERS: dict[str, CrossPageCheckFn] = {
    "duplicate_title": check_duplicate_title,
    "duplicate_meta_description": check_duplicate_meta_description,
    "duplicate_content": check_duplicate_content,
    "keyword_cannibalization": check_keyword_cannibalization,
    "orphan_page": check_orphan_page,
    "missing_canonical": check_missing_canonical,
    "self_canonical_mismatch": check_self_canonical_mismatch,
    "broken_canonical_url": check_broken_canonical_url,
    "canonical_points_to_redirect": check_canonical_points_to_redirect,
    "canonical_points_to_noindex": check_canonical_points_to_noindex,
}


# ---------------------------------------------------------------------------
# Evaluate + persist
# ---------------------------------------------------------------------------


def evaluate_cross_page_checks(ctx: CrossPageContext) -> list[CrossPageIssueWrite]:
    """Run every CROSS_PAGE-scoped registry check once over the full page set.

    Returns one write per *issue found* (fail only). Passing checks produce no rows.
    """
    writes: list[CrossPageIssueWrite] = []
    for entry in checks_for_scope(Scope.CROSS_PAGE):
        handler = CROSS_PAGE_CHECK_HANDLERS.get(entry.name)
        if handler is None:
            logger.warning(
                "No cross_page_runner handler for CROSS_PAGE check '%s'; skipping.",
                entry.name,
            )
            continue
        for outcome in handler(ctx):
            if outcome.status != "fail":
                continue
            writes.append(
                CrossPageIssueWrite(
                    check_name=entry.name,
                    status="fail",
                    details=outcome.details,
                    severity=outcome.severity
                    or severity_default_for(entry.name)
                    or entry.severity_default,
                )
            )
    return writes


def persist_cross_page_issues(
    crawl_id: int,
    writes: list[CrossPageIssueWrite],
    *,
    session_factory: Callable[[], Session] | None = None,
) -> int:
    """Replace CROSS_PAGE rows in site_issues for this crawl (one row per issue)."""
    cross_names = {entry.name for entry in checks_for_scope(Scope.CROSS_PAGE)}
    factory = session_factory or SessionLocal
    with factory() as db:
        db.execute(
            delete(SiteIssue).where(
                SiteIssue.crawl_id == crawl_id,
                SiteIssue.check_name.in_(cross_names),
            )
        )
        for row in writes:
            db.add(
                SiteIssue(
                    crawl_id=crawl_id,
                    check_name=row.check_name,
                    status=row.status,
                    details=row.details,
                    severity=row.severity,
                )
            )
        db.commit()
    return len(writes)


async def run_cross_page_checks(
    crawl_id: int,
    *,
    sitemap_urls: set[str] | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> list[CrossPageIssueWrite]:
    """Load crawl_pages, run CROSS_PAGE checks once, persist site_issues rows.

    Must run after the page crawl has finished and crawl_pages is fully populated.
    Does not re-crawl pages. Optional ``sitemap_urls`` enables crawl↔sitemap
    comparisons when a caller already has a SiteAssetCache.
    """
    factory = session_factory or SessionLocal
    ctx = await asyncio.to_thread(
        load_cross_page_context,
        crawl_id,
        sitemap_urls=sitemap_urls,
        session_factory=factory,
    )
    if not ctx.pages:
        await asyncio.to_thread(
            persist_cross_page_issues, crawl_id, [], session_factory=factory
        )
        return []

    writes = await asyncio.to_thread(evaluate_cross_page_checks, ctx)
    await asyncio.to_thread(
        persist_cross_page_issues, crawl_id, writes, session_factory=factory
    )
    return writes
