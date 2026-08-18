"""Full-audit orchestrator — ordered, idempotent phases for a single crawl_id.

Phase order:
  1. crawl        — crawl the site, populate crawl_pages
  2. site         — site_runner (SITE checks)
  3. page         — page_runner (PAGE checks, once per URL)
  4. cross_page   — cross_page_runner
  5. homepage     — homepage_runner
  6. finish       — mark crawl finished_at / completed

Each step is independently re-runnable via ``rerun_step(crawl_id, step)``
so debugging can re-execute e.g. only ``\"cross_page\"`` without re-crawling.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.checks.cross_page_runner import run_cross_page_checks
from app.checks.homepage_runner import run_homepage_checks
from app.checks.page_runner import run_page_checks
from app.checks.site_runner import SiteAssetCache, fetch_site_assets, run_site_checks
from app.crawler.crawler import CrawlerService
from app.crawler.storage import CrawlStorage
from app.db.database import SessionLocal
from app.models import (
    CrawlPage,
    CrawlRun,
    CrawlRunScore,
    PageIssue,
    PageLink,
    PageTechnicalDetails,
    PageVital,
    SiteIssue,
    SitemapFinding,
)

logger = logging.getLogger(__name__)

AuditStep = Literal["crawl", "site", "page", "cross_page", "homepage", "finish"]

AUDIT_STEPS: tuple[AuditStep, ...] = (
    "crawl",
    "site",
    "page",
    "cross_page",
    "homepage",
    "finish",
)

# Human / alias names accepted by rerun_step (canonical key → aliases).
_STEP_ALIASES: dict[str, AuditStep] = {
    "crawl": "crawl",
    "site": "site",
    "site_runner": "site",
    "page": "page",
    "page_runner": "page",
    "cross_page": "cross_page",
    "cross_page_runner": "cross_page",
    "cross-page": "cross_page",
    "homepage": "homepage",
    "homepage_runner": "homepage",
    "finish": "finish",
    "complete": "finish",
    "completed": "finish",
}


@dataclass(slots=True)
class AuditRunContext:
    """Shared state across phases of one full (or partial) audit run."""

    crawl_id: int
    start_url: str
    max_pages: int = 200
    max_depth: int = 10
    enable_pagespeed: bool | None = None
    storage: CrawlStorage = field(default_factory=CrawlStorage)
    progress_callback: Callable[[], None] | None = None
    session_factory: Callable[[], Session] = SessionLocal
    site_cache: SiteAssetCache | None = None
    results: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StepResult:
    step: AuditStep
    ok: bool
    detail: str = ""
    payload: Any = None


def normalize_step(step: str) -> AuditStep:
    key = (step or "").strip().lower().replace(" ", "_")
    canonical = _STEP_ALIASES.get(key)
    if canonical is None:
        allowed = ", ".join(AUDIT_STEPS)
        raise ValueError(f"Unknown audit step {step!r}. Expected one of: {allowed}.")
    return canonical


def resolve_start_url(
    crawl_id: int,
    *,
    start_url: str | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> str:
    """Resolve an absolute site-root URL for SITE / HOMEPAGE re-runs."""
    if start_url and start_url.strip():
        return start_url.strip()

    factory = session_factory or SessionLocal
    with factory() as db:
        first_page = db.scalars(
            select(CrawlPage)
            .where(CrawlPage.crawl_id == crawl_id)
            .order_by(CrawlPage.id.asc())
            .limit(1)
        ).first()
        if first_page and first_page.url:
            parsed = urlparse(first_page.url)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}/"

        crawl = db.get(CrawlRun, crawl_id)
        if crawl is None:
            raise ValueError(f"Crawl {crawl_id} not found.")
        raw = (crawl.domain or "").strip()
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw if raw.endswith("/") else f"{raw}/"
        if raw:
            return f"https://{raw.rstrip('/')}/"

    raise ValueError(
        f"Cannot resolve start_url for crawl {crawl_id}; pass start_url explicitly."
    )


def _require_crawl(
    crawl_id: int,
    *,
    session_factory: Callable[[], Session],
) -> CrawlRun:
    with session_factory() as db:
        crawl = db.get(CrawlRun, crawl_id)
        if crawl is None:
            raise ValueError(f"Crawl {crawl_id} not found.")
        db.expunge(crawl)
        return crawl


def _clear_page_data(
    crawl_id: int,
    *,
    session_factory: Callable[[], Session],
) -> None:
    """Drop pages + derived rows so a crawl re-run starts clean (crawl row kept)."""
    with session_factory() as db:
        page_ids = list(
            db.scalars(select(CrawlPage.id).where(CrawlPage.crawl_id == crawl_id)).all()
        )
        if page_ids:
            db.execute(delete(PageLink).where(PageLink.crawl_page_id.in_(page_ids)))
            db.execute(delete(PageVital).where(PageVital.crawl_page_id.in_(page_ids)))
            db.execute(
                delete(PageTechnicalDetails).where(
                    PageTechnicalDetails.crawl_page_id.in_(page_ids)
                )
            )
        db.execute(delete(SiteIssue).where(SiteIssue.crawl_id == crawl_id))
        db.execute(delete(PageIssue).where(PageIssue.crawl_id == crawl_id))
        db.execute(delete(SitemapFinding).where(SitemapFinding.crawl_id == crawl_id))
        db.execute(delete(CrawlRunScore).where(CrawlRunScore.crawl_id == crawl_id))
        db.execute(delete(CrawlPage).where(CrawlPage.crawl_id == crawl_id))
        crawl = db.get(CrawlRun, crawl_id)
        if crawl is not None:
            crawl.total_urls = 0
            crawl.robots_txt_found = None
            crawl.robots_txt_valid = None
            crawl.robots_txt_ai_disallowed = None
            crawl.robots_txt_raw = None
            crawl.llms_txt_present = None
            crawl.soft_404_probe_url = None
            crawl.soft_404_status_code = None
            crawl.soft_404_word_count = None
            crawl.soft_404_is_soft = None
            crawl.soft_404_detail = None
        db.commit()


async def _step_crawl(ctx: AuditRunContext) -> StepResult:
    await asyncio.to_thread(_require_crawl, ctx.crawl_id, session_factory=ctx.session_factory)
    await asyncio.to_thread(ctx.storage.set_run_started, ctx.crawl_id)
    # Large deletes must not block the API event loop (keeps /health + dashboard responsive).
    await asyncio.to_thread(_clear_page_data, ctx.crawl_id, session_factory=ctx.session_factory)

    service = CrawlerService(
        start_url=ctx.start_url,
        max_pages=ctx.max_pages,
        max_depth=ctx.max_depth,
        storage=ctx.storage,
        progress_callback=ctx.progress_callback,
    )
    await service.crawl(ctx.crawl_id)

    with ctx.session_factory() as db:
        page_count = (
            db.scalar(
                select(func.count())
                .select_from(CrawlPage)
                .where(CrawlPage.crawl_id == ctx.crawl_id)
            )
            or 0
        )
    # Mark post-crawl enrichment so progress polls show checks are still running.
    await asyncio.to_thread(
        ctx.storage.set_run_phase,
        ctx.crawl_id,
        phase="site_checks",
        current=0,
        total=None,
        status="enriching",
    )
    detail = f"crawl_pages populated ({page_count} page(s))"
    ctx.results["crawl"] = {"pages": page_count}
    return StepResult(step="crawl", ok=True, detail=detail)


async def _step_site(ctx: AuditRunContext) -> StepResult:
    await asyncio.to_thread(
        ctx.storage.set_run_phase,
        ctx.crawl_id,
        phase="site_checks",
        current=0,
        total=None,
        status="enriching",
    )
    start_url = resolve_start_url(
        ctx.crawl_id,
        start_url=ctx.start_url,
        session_factory=ctx.session_factory,
    )
    ctx.start_url = start_url

    site_cache, writes = await run_site_checks(
        ctx.crawl_id,
        start_url=start_url,
        session_factory=ctx.session_factory,
    )
    ctx.site_cache = site_cache

    # Mirror probe results onto the crawl row (idempotent overwrite).
    ctx.storage.save_site_checks(
        ctx.crawl_id,
        robots_txt_found=site_cache.robots.found,
        robots_txt_valid=site_cache.robots.valid,
        robots_txt_ai_disallowed=site_cache.robots.ai_disallowed,
        robots_txt_raw=site_cache.robots.raw,
        llms_txt_present=site_cache.llms.present,
        soft_404=site_cache.soft_404,
    )

    detail = f"{len(writes)} SITE check row(s) written"
    ctx.results["site"] = {"writes": len(writes)}
    return StepResult(step="site", ok=True, detail=detail, payload=writes)


async def _step_page(ctx: AuditRunContext) -> StepResult:
    await asyncio.to_thread(
        ctx.storage.set_run_phase,
        ctx.crawl_id,
        phase="page_checks",
        current=0,
        total=None,
        status="enriching",
    )

    def _phase_progress(phase: str, current: int, total: int | None) -> None:
        ctx.storage.set_run_phase(
            ctx.crawl_id,
            phase=phase,
            current=current,
            total=total,
            status="enriching",
        )

    writes = await run_page_checks(
        ctx.crawl_id,
        enable_pagespeed=ctx.enable_pagespeed,
        session_factory=ctx.session_factory,
        phase_progress=_phase_progress,
    )
    detail = f"{len(writes)} PAGE check row(s) written"
    ctx.results["page"] = {"writes": len(writes)}
    return StepResult(step="page", ok=True, detail=detail, payload=writes)


async def _step_cross_page(ctx: AuditRunContext) -> StepResult:
    await asyncio.to_thread(
        ctx.storage.set_run_phase,
        ctx.crawl_id,
        phase="cross_page_checks",
        current=0,
        total=None,
        status="enriching",
    )
    sitemap_urls: set[str] | None = None
    if ctx.site_cache is not None:
        sitemap_urls = ctx.site_cache.sitemap.page_urls
    else:
        # Independent re-run: fetch sitemap URLs only — do not rewrite SITE issues.
        try:
            start_url = resolve_start_url(
                ctx.crawl_id,
                start_url=ctx.start_url,
                session_factory=ctx.session_factory,
            )
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(20.0, connect=10.0),
            ) as client:
                site_cache = await fetch_site_assets(client, start_url=start_url)
            ctx.site_cache = site_cache
            sitemap_urls = site_cache.sitemap.page_urls
        except Exception as exc:  # noqa: BLE001 — cross_page can proceed without sitemap
            logger.warning(
                "Could not fetch site assets before cross_page for crawl %s: %s",
                ctx.crawl_id,
                exc,
            )

    writes = await run_cross_page_checks(
        ctx.crawl_id,
        sitemap_urls=sitemap_urls,
        session_factory=ctx.session_factory,
    )
    detail = f"{len(writes)} CROSS_PAGE issue row(s) written"
    ctx.results["cross_page"] = {"writes": len(writes)}
    return StepResult(step="cross_page", ok=True, detail=detail, payload=writes)


async def _step_homepage(ctx: AuditRunContext) -> StepResult:
    await asyncio.to_thread(
        ctx.storage.set_run_phase,
        ctx.crawl_id,
        phase="homepage_checks",
        current=0,
        total=None,
        status="enriching",
    )
    start_url = resolve_start_url(
        ctx.crawl_id,
        start_url=ctx.start_url,
        session_factory=ctx.session_factory,
    )
    writes = await run_homepage_checks(
        ctx.crawl_id,
        start_url=start_url,
        session_factory=ctx.session_factory,
    )
    detail = f"{len(writes)} HOMEPAGE check row(s) written"
    ctx.results["homepage"] = {"writes": len(writes)}
    return StepResult(step="homepage", ok=True, detail=detail, payload=writes)


async def _step_finish(ctx: AuditRunContext) -> StepResult:
    await asyncio.to_thread(
        ctx.storage.set_run_phase,
        ctx.crawl_id,
        phase="scoring",
        current=0,
        total=None,
        status="enriching",
    )
    # Scores from persisted site_issues + page_issues (runners own issue writes).
    try:
        from app.rules.engine import RuleEngine

        score_result = await asyncio.to_thread(RuleEngine().run, ctx.crawl_id)
        ctx.results["scores"] = score_result
    except Exception as exc:
        logger.exception("Score computation failed for crawl %s: %s", ctx.crawl_id, exc)
        ctx.storage.set_run_failed(ctx.crawl_id, error_message=str(exc))
        return StepResult(step="finish", ok=False, detail=str(exc))

    ctx.storage.set_run_completed(ctx.crawl_id)
    detail = "crawl marked completed (finished_at set)"
    ctx.results["finish"] = detail
    return StepResult(step="finish", ok=True, detail=detail)


_STEP_HANDLERS: dict[AuditStep, Callable[[AuditRunContext], Any]] = {
    "crawl": _step_crawl,
    "site": _step_site,
    "page": _step_page,
    "cross_page": _step_cross_page,
    "homepage": _step_homepage,
    "finish": _step_finish,
}


async def run_step(ctx: AuditRunContext, step: str) -> StepResult:
    """Run a single named step (idempotent)."""
    canonical = normalize_step(step)
    handler = _STEP_HANDLERS[canonical]
    logger.info("Audit step %s starting for crawl %s", canonical, ctx.crawl_id)
    try:
        result = await handler(ctx)
    except Exception as exc:
        logger.exception("Audit step %s failed for crawl %s", canonical, ctx.crawl_id)
        if canonical != "finish":
            ctx.storage.set_run_failed(ctx.crawl_id, error_message=str(exc))
        raise
    logger.info(
        "Audit step %s finished for crawl %s: %s",
        canonical,
        ctx.crawl_id,
        result.detail,
    )
    return result


async def rerun_step(
    crawl_id: int,
    step: str,
    *,
    start_url: str | None = None,
    max_pages: int = 200,
    max_depth: int = 10,
    enable_pagespeed: bool | None = None,
    storage: CrawlStorage | None = None,
    progress_callback: Callable[[], None] | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> StepResult:
    """Re-run one audit phase independently (debugging / partial refresh).

    Example::

        await rerun_step(crawl_id, \"cross_page\")
    """
    factory = session_factory or SessionLocal
    _require_crawl(crawl_id, session_factory=factory)
    resolved = resolve_start_url(
        crawl_id, start_url=start_url, session_factory=factory
    )
    ctx = AuditRunContext(
        crawl_id=crawl_id,
        start_url=resolved,
        max_pages=max_pages,
        max_depth=max_depth,
        enable_pagespeed=enable_pagespeed,
        storage=storage or CrawlStorage(),
        progress_callback=progress_callback,
        session_factory=factory,
    )
    return await run_step(ctx, step)


async def run_audit(
    crawl_id: int,
    *,
    start_url: str,
    max_pages: int = 200,
    max_depth: int = 10,
    enable_pagespeed: bool | None = None,
    storage: CrawlStorage | None = None,
    progress_callback: Callable[[], None] | None = None,
    session_factory: Callable[[], Session] | None = None,
    steps: Sequence[str] | None = None,
) -> AuditRunContext:
    """Run the full audit pipeline (or a contiguous subset of steps) in order."""
    factory = session_factory or SessionLocal
    _require_crawl(crawl_id, session_factory=factory)

    ctx = AuditRunContext(
        crawl_id=crawl_id,
        start_url=start_url,
        max_pages=max_pages,
        max_depth=max_depth,
        enable_pagespeed=enable_pagespeed,
        storage=storage or CrawlStorage(),
        progress_callback=progress_callback,
        session_factory=factory,
    )

    ordered: list[AuditStep] = (
        [normalize_step(s) for s in steps] if steps is not None else list(AUDIT_STEPS)
    )
    for step in ordered:
        result = await run_step(ctx, step)
        if not result.ok:
            break
    return ctx
