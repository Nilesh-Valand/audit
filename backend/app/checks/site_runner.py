"""SITE-scoped check runner — once per crawl, outside the page-crawl loop.

Fetches robots.txt, sitemap.xml, and llms.txt once at the crawl root, caches the
parsed results in memory, evaluates every registry check with scope == SITE,
and writes exactly one site_issues row per check.
"""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlparse

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.checks.registry import Scope, checks_for_scope, severity_default_for
from app.crawler.normalize import normalize_url
from app.crawler.site_checks import (
    Soft404ProbeResult,
    ai_agents_disallowed,
    probe_soft_404,
    validate_robots_syntax,
)
from app.db.database import SessionLocal
from app.models import CrawlPage, PageTechnicalDetails, SiteIssue

logger = logging.getLogger(__name__)

SITEMAP_URL_LIMIT = 5_000


# ---------------------------------------------------------------------------
# In-memory asset cache (fetched once, passed into check functions)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RobotsCache:
    url: str
    found: bool
    valid: bool | None
    raw: str | None
    ai_disallowed: list[str]


@dataclass(slots=True)
class SitemapCache:
    root_url: str
    found: bool
    malformed: bool
    """True when the root sitemap XML could not be parsed."""
    child_broken: list[tuple[str, str]] = field(default_factory=list)
    """(child_url, message) for broken / missing child sitemaps."""
    page_urls: set[str] = field(default_factory=set)
    """Normalized page URLs discovered from urlset entries."""
    structure_messages: list[str] = field(default_factory=list)
    """Human-readable notes for root-level not-found / malformed."""


@dataclass(slots=True)
class LlmsCache:
    url: str
    present: bool
    raw: str | None = None


@dataclass(slots=True)
class SiteAssetCache:
    """Parsed site-root assets shared by all SITE checks."""

    origin: str
    robots: RobotsCache
    sitemap: SitemapCache
    llms: LlmsCache
    soft_404: Soft404ProbeResult | None = None


@dataclass(slots=True)
class SiteCrawlSnapshot:
    """Post-crawl signals needed by a subset of SITE checks."""

    page_urls: set[str]
    redirect_chains: list[tuple[str, list[str]]]
    """(final_page_url, redirect chain URLs including final)."""


@dataclass(slots=True)
class CheckOutcome:
    status: str  # "pass" | "fail"
    details: str


@dataclass(slots=True)
class SiteCheckWrite:
    check_name: str
    status: str
    details: str
    severity: str


SiteCheckFn = Callable[[SiteAssetCache, SiteCrawlSnapshot | None], CheckOutcome]


# ---------------------------------------------------------------------------
# Fetch once
# ---------------------------------------------------------------------------


def _origin_from_url(start_url: str) -> str:
    parsed = urlparse(start_url)
    origin = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port and parsed.port not in {80, 443}:
        origin = f"{origin}:{parsed.port}"
    return origin


async def fetch_site_assets(
    client: httpx.AsyncClient,
    *,
    start_url: str,
) -> SiteAssetCache:
    """Fetch robots.txt, sitemap.xml, and llms.txt once; return an in-memory cache."""
    origin = _origin_from_url(start_url)
    sample_url = f"{origin}/"

    robots = await _fetch_robots(client, origin=origin, sample_url=sample_url)
    llms = await _fetch_llms(client, origin=origin)
    sitemap = await _fetch_sitemap(client, origin=origin)
    soft_404 = await probe_soft_404(client, origin=origin)

    return SiteAssetCache(
        origin=origin,
        robots=robots,
        sitemap=sitemap,
        llms=llms,
        soft_404=soft_404,
    )


async def _fetch_robots(
    client: httpx.AsyncClient, *, origin: str, sample_url: str
) -> RobotsCache:
    url = f"{origin}/robots.txt"
    try:
        response = await client.get(url)
        if response.status_code < 400:
            raw = response.text
            return RobotsCache(
                url=url,
                found=True,
                valid=validate_robots_syntax(raw),
                raw=raw,
                ai_disallowed=ai_agents_disallowed(raw, sample_url),
            )
    except httpx.HTTPError:
        pass
    return RobotsCache(url=url, found=False, valid=None, raw=None, ai_disallowed=[])


async def _fetch_llms(client: httpx.AsyncClient, *, origin: str) -> LlmsCache:
    url = f"{origin}/llms.txt"
    try:
        response = await client.get(url)
        if response.status_code < 400 and response.content:
            return LlmsCache(url=url, present=True, raw=response.text)
    except httpx.HTTPError:
        pass
    return LlmsCache(url=url, present=False, raw=None)


async def _fetch_sitemap(client: httpx.AsyncClient, *, origin: str) -> SitemapCache:
    root_url = f"{origin}/sitemap.xml"
    cache = SitemapCache(root_url=root_url, found=False, malformed=False)
    await _walk_sitemap(client, root_url, cache, is_child=False)
    return cache


async def _walk_sitemap(
    client: httpx.AsyncClient,
    sitemap_url: str,
    cache: SitemapCache,
    *,
    is_child: bool,
    seen: set[str] | None = None,
) -> None:
    if len(cache.page_urls) >= SITEMAP_URL_LIMIT:
        return

    seen = seen if seen is not None else set()
    normalized = normalize_url(sitemap_url)
    if normalized in seen:
        return
    seen.add(normalized)

    try:
        response = await client.get(normalized)
    except httpx.HTTPError:
        _record_sitemap_fetch_error(
            cache,
            normalized,
            is_child=is_child,
            message=(
                "Child sitemap could not be fetched."
                if is_child
                else "Sitemap could not be fetched."
            ),
        )
        return

    if response.status_code >= 400:
        _record_sitemap_fetch_error(
            cache,
            normalized,
            is_child=is_child,
            message=(
                f"Child sitemap returned HTTP {response.status_code}."
                if is_child
                else f"Sitemap returned HTTP {response.status_code}."
            ),
        )
        return

    if not is_child:
        cache.found = True

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError:
        if is_child:
            cache.child_broken.append((normalized, "Child sitemap contains invalid XML."))
        else:
            cache.malformed = True
            cache.structure_messages.append("Sitemap XML could not be parsed.")
        return

    tag = root.tag.split("}", 1)[-1].lower()
    if tag == "sitemapindex":
        for node in root.findall(".//{*}sitemap/{*}loc"):
            if len(cache.page_urls) >= SITEMAP_URL_LIMIT:
                break
            if node.text and node.text.strip():
                await _walk_sitemap(
                    client,
                    node.text.strip(),
                    cache,
                    is_child=True,
                    seen=seen,
                )
        return

    if tag != "urlset":
        message = (
            "Child sitemap root element is not urlset/sitemapindex."
            if is_child
            else "Sitemap root element is not urlset/sitemapindex."
        )
        if is_child:
            cache.child_broken.append((normalized, message))
        else:
            cache.malformed = True
            cache.structure_messages.append(message)
        return

    for loc in root.findall(".//{*}url/{*}loc"):
        if len(cache.page_urls) >= SITEMAP_URL_LIMIT:
            break
        if loc.text and loc.text.strip():
            cache.page_urls.add(normalize_url(loc.text.strip()))


def _record_sitemap_fetch_error(
    cache: SitemapCache,
    url: str,
    *,
    is_child: bool,
    message: str,
) -> None:
    if is_child:
        cache.child_broken.append((url, message))
    else:
        cache.found = False
        cache.structure_messages.append(message)


# ---------------------------------------------------------------------------
# Individual SITE check functions (receive the shared cache)
# ---------------------------------------------------------------------------


def _pass(details: str) -> CheckOutcome:
    return CheckOutcome(status="pass", details=details)


def _fail(details: str) -> CheckOutcome:
    return CheckOutcome(status="fail", details=details)


def check_robots_txt_missing(
    cache: SiteAssetCache, _: SiteCrawlSnapshot | None
) -> CheckOutcome:
    if cache.robots.found:
        return _pass("robots.txt is present at the site root.")
    return _fail(
        "No robots.txt was found at the site root. This may be intentional, "
        "but crawlers then fall back to default allow behavior."
    )


def check_robots_txt_syntax_error(
    cache: SiteAssetCache, _: SiteCrawlSnapshot | None
) -> CheckOutcome:
    if not cache.robots.found:
        return _pass("robots.txt is missing; syntax check not applicable.")
    if cache.robots.valid is False:
        return _fail("robots.txt was found but appears to have syntax problems.")
    return _pass("robots.txt syntax looks valid.")


def check_sitemap_not_found(
    cache: SiteAssetCache, _: SiteCrawlSnapshot | None
) -> CheckOutcome:
    if cache.sitemap.found:
        return _pass("sitemap.xml was found at the site root.")
    detail = cache.sitemap.structure_messages[0] if cache.sitemap.structure_messages else (
        "/sitemap.xml returned 404 or was otherwise unavailable."
    )
    return _fail(detail)


def check_sitemap_malformed(
    cache: SiteAssetCache, _: SiteCrawlSnapshot | None
) -> CheckOutcome:
    if not cache.sitemap.found:
        return _pass("sitemap.xml is missing; malformed check not applicable.")
    if cache.sitemap.malformed:
        detail = (
            cache.sitemap.structure_messages[0]
            if cache.sitemap.structure_messages
            else "Sitemap XML could not be parsed."
        )
        return _fail(detail)
    return _pass("Root sitemap XML parsed successfully.")


def check_sitemap_child_broken(
    cache: SiteAssetCache, _: SiteCrawlSnapshot | None
) -> CheckOutcome:
    if not cache.sitemap.child_broken:
        return _pass("No broken child sitemaps detected.")
    samples = cache.sitemap.child_broken[:3]
    parts = [f"{url}: {msg}" for url, msg in samples]
    extra = len(cache.sitemap.child_broken) - len(samples)
    if extra > 0:
        parts.append(f"(+{extra} more)")
    return _fail("Broken child sitemap(s): " + "; ".join(parts))


def check_llms_txt_missing(
    cache: SiteAssetCache, _: SiteCrawlSnapshot | None
) -> CheckOutcome:
    if cache.llms.present:
        return _pass("llms.txt is present at the site root.")
    return _fail(
        "No llms.txt was found at the site root. This is an emerging convention "
        "for AI assistants (not a hard requirement)."
    )


def check_ai_crawler_blocked(
    cache: SiteAssetCache, _: SiteCrawlSnapshot | None
) -> CheckOutcome:
    blocked = cache.robots.ai_disallowed
    if not blocked:
        return _pass("No known AI crawler user-agents are disallowed in robots.txt.")
    agents = ", ".join(blocked)
    return _fail(
        f"AI crawler user-agent(s) are disallowed in robots.txt: {agents}. "
        "This may be an intentional policy choice."
    )


def check_generic_404_page(
    cache: SiteAssetCache, _: SiteCrawlSnapshot | None
) -> CheckOutcome:
    soft = cache.soft_404
    if soft is None:
        return _pass("Soft-404 probe was not run.")
    if soft.is_soft:
        return _fail(soft.detail or "Unknown URLs do not return a proper custom 404 page.")
    return _pass(soft.detail or "Proper custom 404 behavior detected.")


def check_sitemap_orphan(
    cache: SiteAssetCache, crawl: SiteCrawlSnapshot | None
) -> CheckOutcome:
    if not cache.sitemap.found or not cache.sitemap.page_urls:
        return _pass("No sitemap URLs available to compare against the crawl.")
    if crawl is None or not crawl.page_urls:
        return _pass("Crawl snapshot not available; sitemap coverage check deferred.")
    not_crawled = sorted(cache.sitemap.page_urls - crawl.page_urls)
    if not not_crawled:
        return _pass("All discovered sitemap URLs were covered by this crawl.")
    sample = ", ".join(not_crawled[:5])
    extra = len(not_crawled) - min(5, len(not_crawled))
    sample_note = f" Examples: {sample}" + (f" (+{extra} more)." if extra else ".")
    return _fail(
        f"{len(not_crawled)} sitemap URL(s) were not crawled in this run "
        f"(crawled {len(crawl.page_urls)} page(s); sitemap compared "
        f"{len(cache.sitemap.page_urls)} URL(s)).{sample_note} "
        "Increase max pages if you need broader sitemap coverage."
    )


def check_crawled_not_in_sitemap(
    cache: SiteAssetCache, crawl: SiteCrawlSnapshot | None
) -> CheckOutcome:
    if crawl is None or not crawl.page_urls:
        return _pass("Crawl snapshot not available; crawled-vs-sitemap check deferred.")
    if not cache.sitemap.found or not cache.sitemap.page_urls:
        return _pass("No sitemap URLs available to compare against crawled pages.")
    missing = sorted(crawl.page_urls - cache.sitemap.page_urls)
    if not missing:
        return _pass("All crawled pages appear in the sitemap.")
    sample = ", ".join(missing[:5])
    extra = len(missing) - min(5, len(missing))
    sample_note = f" Examples: {sample}" + (f" (+{extra} more)." if extra else ".")
    return _fail(
        f"{len(missing)} crawled URL(s) do not appear in the sitemap.{sample_note}"
    )


def check_redirect_loop(
    cache: SiteAssetCache, crawl: SiteCrawlSnapshot | None
) -> CheckOutcome:
    del cache  # redirect loops are detected from crawl redirect chains
    if crawl is None or not crawl.redirect_chains:
        return _pass("No redirect chains available to inspect for loops.")
    looped_urls: list[str] = []
    for final_url, chain in crawl.redirect_chains:
        if _chain_has_loop(chain):
            looped_urls.append(final_url)
    if not looped_urls:
        return _pass("No redirect loops detected in crawled redirect chains.")
    sample = ", ".join(looped_urls[:5])
    extra = len(looped_urls) - min(5, len(looped_urls))
    note = f" Affected URLs: {sample}" + (f" (+{extra} more)." if extra else ".")
    return _fail(
        "Redirect chain contains a loop (a URL redirects back to a previously seen URL)."
        + note
    )


def _chain_has_loop(chain_urls: list[str]) -> bool:
    if len(chain_urls) < 2:
        return False
    seen: set[str] = set()
    for url in chain_urls:
        key = normalize_url(url)
        if key in seen:
            return True
        seen.add(key)
    return False


SITE_CHECK_HANDLERS: dict[str, SiteCheckFn] = {
    "robots_txt_missing": check_robots_txt_missing,
    "robots_txt_syntax_error": check_robots_txt_syntax_error,
    "sitemap_not_found": check_sitemap_not_found,
    "sitemap_malformed": check_sitemap_malformed,
    "sitemap_child_broken": check_sitemap_child_broken,
    "llms_txt_missing": check_llms_txt_missing,
    "ai_crawler_blocked": check_ai_crawler_blocked,
    "generic_404_page": check_generic_404_page,
    "sitemap_orphan": check_sitemap_orphan,
    "crawled_not_in_sitemap": check_crawled_not_in_sitemap,
    "redirect_loop": check_redirect_loop,
}


# ---------------------------------------------------------------------------
# Evaluate + persist
# ---------------------------------------------------------------------------


def evaluate_site_checks(
    cache: SiteAssetCache,
    crawl: SiteCrawlSnapshot | None = None,
) -> list[SiteCheckWrite]:
    """Run every SITE-scoped registry check exactly once."""
    writes: list[SiteCheckWrite] = []
    for entry in checks_for_scope(Scope.SITE):
        handler = SITE_CHECK_HANDLERS.get(entry.name)
        if handler is None:
            logger.warning("No site_runner handler for SITE check '%s'; skipping.", entry.name)
            continue
        outcome = handler(cache, crawl)
        writes.append(
            SiteCheckWrite(
                check_name=entry.name,
                status=outcome.status,
                details=outcome.details,
                severity=severity_default_for(entry.name) or entry.severity_default,
            )
        )
    return writes


def persist_site_issues(
    crawl_id: int,
    writes: list[SiteCheckWrite],
    *,
    session_factory: Callable[[], Session] | None = None,
) -> int:
    """Replace SITE-scoped site_issues for this crawl (one row per check).

    Does not touch CROSS_PAGE rows written by cross_page_runner.
    """
    site_check_names = {entry.name for entry in checks_for_scope(Scope.SITE)}
    factory = session_factory or SessionLocal
    with factory() as db:
        db.execute(
            delete(SiteIssue).where(
                SiteIssue.crawl_id == crawl_id,
                SiteIssue.check_name.in_(site_check_names),
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


def load_crawl_snapshot(
    crawl_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> SiteCrawlSnapshot:
    """Load crawled page URLs + redirect chains for post-crawl SITE checks."""
    factory = session_factory or SessionLocal
    with factory() as db:
        pages = db.scalars(
            select(CrawlPage)
            .where(CrawlPage.crawl_id == crawl_id)
            .options(joinedload(CrawlPage.technical_details))
        ).unique().all()

        page_urls: set[str] = set()
        chains: list[tuple[str, list[str]]] = []
        for page in pages:
            key = normalize_url(page.url)
            page_urls.add(key)
            chain = _redirect_chain_for_page(page.technical_details, page.url)
            if chain:
                chains.append((page.url, chain))
        return SiteCrawlSnapshot(page_urls=page_urls, redirect_chains=chains)


def _redirect_chain_for_page(
    technical: PageTechnicalDetails | None, final_url: str
) -> list[str]:
    urls: list[str] = []
    if technical and isinstance(technical.redirect_chain_json, list):
        for hop in technical.redirect_chain_json:
            if isinstance(hop, dict) and hop.get("url"):
                urls.append(str(hop["url"]))
    urls.append(final_url)
    return urls


async def run_site_checks(
    crawl_id: int,
    *,
    start_url: str,
    client: httpx.AsyncClient | None = None,
    cache: SiteAssetCache | None = None,
    crawl_snapshot: SiteCrawlSnapshot | None = None,
    load_snapshot_from_db: bool = True,
    session_factory: Callable[[], Session] | None = None,
) -> tuple[SiteAssetCache, list[SiteCheckWrite]]:
    """Fetch (or reuse) site assets, evaluate SITE checks, persist site_issues.

    Must be called outside the per-page crawl loop. Pass an existing ``cache``
    when assets were already fetched at crawl start.
    """
    factory = session_factory or SessionLocal
    owns_client = client is None
    http = client or httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(20.0, connect=10.0))
    try:
        asset_cache = cache or await fetch_site_assets(http, start_url=start_url)
    finally:
        if owns_client:
            await http.aclose()

    snapshot = crawl_snapshot
    if snapshot is None and load_snapshot_from_db:
        snapshot = await asyncio.to_thread(
            load_crawl_snapshot, crawl_id, session_factory=factory
        )

    writes = await asyncio.to_thread(evaluate_site_checks, asset_cache, snapshot)
    await asyncio.to_thread(
        persist_site_issues, crawl_id, writes, session_factory=factory
    )
    return asset_cache, writes
