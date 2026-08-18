"""HOMEPAGE-scoped check runner — once per crawl, against the crawl root only.

Identifies the homepage as the crawl root URL (the crawl start_url), runs every
registry check with scope == HOMEPAGE against that single crawl_pages row, and
writes one site_issues row per check. Details always include the homepage URL
for reference. Never evaluates these checks on any other page.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.checks.registry import Scope, checks_for_scope, severity_default_for
from app.crawler.normalize import normalize_url
from app.db.database import SessionLocal
from app.models import CrawlPage, PageTechnicalDetails, SiteIssue
from app.rules.schema_validation import schema_blocks_have_type

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CheckOutcome:
    status: str  # "pass" | "fail"
    details: str


@dataclass(slots=True)
class HomepageCheckWrite:
    check_name: str
    status: str
    details: str
    severity: str


@dataclass(slots=True)
class HomepageSnapshot:
    """In-memory view of the single crawl-root page."""

    id: int
    url: str
    status_code: int | None
    technical: PageTechnicalDetails | None


HomepageCheckFn = Callable[[HomepageSnapshot], CheckOutcome]


# ---------------------------------------------------------------------------
# Resolve crawl root → single homepage page
# ---------------------------------------------------------------------------


def resolve_homepage_page(
    pages: list[CrawlPage],
    *,
    start_url: str,
) -> CrawlPage | None:
    """Pick the single crawl_pages row that is the crawl root (homepage).

    Preference order:
    1. Exact normalized match to ``start_url``
    2. Match against ``raw_url`` (pre-redirect seed)
    3. Same-origin site root path ``/``
    4. Lowest-id page on the start_url host (first crawled / seed)
    """
    if not pages:
        return None

    root_key = normalize_url(start_url)
    root_parsed = urlparse(root_key)
    root_host = (root_parsed.hostname or "").lower().removeprefix("www.")

    by_url: dict[str, CrawlPage] = {}
    by_raw: dict[str, CrawlPage] = {}
    for page in pages:
        by_url[normalize_url(page.url)] = page
        if page.raw_url:
            by_raw[normalize_url(page.raw_url)] = page

    if root_key in by_url:
        return by_url[root_key]
    if root_key in by_raw:
        return by_raw[root_key]

    # Same-origin bare root (e.g. start was https://ex.com/path → still prefer /).
    origin_root = None
    if root_parsed.scheme and root_parsed.netloc:
        origin_root = normalize_url(f"{root_parsed.scheme}://{root_parsed.netloc}/")
        if origin_root in by_url:
            return by_url[origin_root]

    same_host = [
        page
        for page in pages
        if (urlparse(page.url).hostname or "").lower().removeprefix("www.") == root_host
    ] or list(pages)

    # Prefer path "/" on that host.
    for page in same_host:
        parsed = urlparse(page.url)
        if (parsed.path or "/") in {"", "/"} and not parsed.query:
            return page

    # First crawled page on the host (seed is stored with lowest id).
    return min(same_host, key=lambda page: page.id)


def load_homepage_snapshot(
    crawl_id: int,
    *,
    start_url: str,
    session_factory: Callable[[], Session] | None = None,
) -> HomepageSnapshot | None:
    """Load the single homepage crawl_pages row (+ technical_details)."""
    factory = session_factory or SessionLocal
    with factory() as db:
        pages = (
            db.scalars(
                select(CrawlPage)
                .where(CrawlPage.crawl_id == crawl_id)
                .options(joinedload(CrawlPage.technical_details))
                .order_by(CrawlPage.id.asc())
            )
            .unique()
            .all()
        )
        page = resolve_homepage_page(pages, start_url=start_url)
        if page is None:
            return None
        return HomepageSnapshot(
            id=page.id,
            url=page.url,
            status_code=page.status_code,
            technical=page.technical_details,
        )


# ---------------------------------------------------------------------------
# Individual HOMEPAGE check functions
# ---------------------------------------------------------------------------


def _pass(details: str) -> CheckOutcome:
    return CheckOutcome(status="pass", details=details)


def _fail(details: str) -> CheckOutcome:
    return CheckOutcome(status="fail", details=details)


def _tag(homepage_url: str, message: str) -> str:
    """Append homepage URL so site_issues rows stay attributable."""
    return f"{message} [homepage: {homepage_url}]"


def check_missing_favicon(page: HomepageSnapshot) -> CheckOutcome:
    tech = page.technical
    if tech is None:
        return _pass(
            _tag(page.url, "No favicon signal captured for the homepage; treated as not failing.")
        )
    if tech.favicon_present:
        return _pass(_tag(page.url, "Homepage has a favicon."))
    return _fail(
        _tag(
            page.url,
            "No favicon was detected on the homepage (link rel=icon or /favicon.ico).",
        )
    )


def check_organization_schema(page: HomepageSnapshot) -> CheckOutcome:
    blocks = _schema_blocks(page)
    if schema_blocks_have_type(blocks, "Organization"):
        return _pass(_tag(page.url, "Homepage includes Organization JSON-LD schema."))
    return _fail(_tag(page.url, "Homepage is missing Organization JSON-LD schema."))


def check_website_schema(page: HomepageSnapshot) -> CheckOutcome:
    blocks = _schema_blocks(page)
    if schema_blocks_have_type(blocks, "WebSite"):
        return _pass(_tag(page.url, "Homepage includes WebSite JSON-LD schema."))
    return _fail(_tag(page.url, "Homepage is missing WebSite JSON-LD schema."))


def _schema_blocks(page: HomepageSnapshot) -> list[Any]:
    tech = page.technical
    if tech is None or not isinstance(tech.schema_json, list):
        return []
    return [block for block in tech.schema_json if isinstance(block, dict)]


HOMEPAGE_CHECK_HANDLERS: dict[str, HomepageCheckFn] = {
    "missing_favicon": check_missing_favicon,
    "organization_schema": check_organization_schema,
    "website_schema": check_website_schema,
}


# ---------------------------------------------------------------------------
# Evaluate + persist
# ---------------------------------------------------------------------------


def evaluate_homepage_checks(page: HomepageSnapshot) -> list[HomepageCheckWrite]:
    """Run every HOMEPAGE-scoped registry check against the crawl-root page only."""
    writes: list[HomepageCheckWrite] = []
    for entry in checks_for_scope(Scope.HOMEPAGE):
        handler = HOMEPAGE_CHECK_HANDLERS.get(entry.name)
        if handler is None:
            logger.warning(
                "No homepage_runner handler for HOMEPAGE check '%s'; skipping.",
                entry.name,
            )
            continue
        outcome = handler(page)
        writes.append(
            HomepageCheckWrite(
                check_name=entry.name,
                status=outcome.status,
                details=outcome.details,
                severity=severity_default_for(entry.name) or entry.severity_default,
            )
        )
    return writes


def persist_homepage_issues(
    crawl_id: int,
    writes: list[HomepageCheckWrite],
    *,
    session_factory: Callable[[], Session] | None = None,
) -> int:
    """Replace HOMEPAGE-scoped site_issues for this crawl (one row per check)."""
    homepage_names = {entry.name for entry in checks_for_scope(Scope.HOMEPAGE)}
    factory = session_factory or SessionLocal
    with factory() as db:
        db.execute(
            delete(SiteIssue).where(
                SiteIssue.crawl_id == crawl_id,
                SiteIssue.check_name.in_(homepage_names),
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


async def run_homepage_checks(
    crawl_id: int,
    *,
    start_url: str,
    session_factory: Callable[[], Session] | None = None,
) -> list[HomepageCheckWrite]:
    """Resolve crawl-root homepage, evaluate HOMEPAGE checks, persist site_issues.

    Must run after crawl_pages includes the root URL. Never runs these checks on
    non-homepage pages.
    """
    factory = session_factory or SessionLocal
    page = await asyncio.to_thread(
        load_homepage_snapshot,
        crawl_id,
        start_url=start_url,
        session_factory=factory,
    )
    if page is None:
        logger.warning(
            "No homepage page found for crawl %s (start_url=%s); skipping HOMEPAGE checks.",
            crawl_id,
            start_url,
        )
        await asyncio.to_thread(
            persist_homepage_issues, crawl_id, [], session_factory=factory
        )
        return []

    writes = await asyncio.to_thread(evaluate_homepage_checks, page)
    await asyncio.to_thread(
        persist_homepage_issues, crawl_id, writes, session_factory=factory
    )
    return writes
