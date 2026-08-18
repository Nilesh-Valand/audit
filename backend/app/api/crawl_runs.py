from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from app.crawler.storage import CrawlStorage
from app.db.database import SessionLocal
from app.models import CrawledPage, CrawlRun, CrawlRunScore, PageIssue
from app.rules.engine import RuleEngine
from app.services.crawl_runs import cancel_crawl_run, get_progress, is_active, start_crawl_run
from app.services.deletions import delete_crawl_run
from app.services.issues import IssueView, count_issues_by_severity, load_issue_views
from app.services.report import ReportService, iter_file_chunks, remove_file

router = APIRouter(prefix="/crawl-runs", tags=["crawl-runs"])
storage = CrawlStorage()
rule_engine = RuleEngine()
report_service = ReportService()
_ACTIVE_ORPHAN_TASKS: set[asyncio.Task[None]] = set()
_ORPHAN_AUDIT_STARTED: set[int] = set()


class CreateCrawlRunRequest(BaseModel):
    project_id: int
    start_url: HttpUrl
    max_pages: int = Field(default=200, ge=1, le=5000)
    max_depth: int = Field(default=10, ge=0, le=20)
    enable_pagespeed: bool | None = None


class CrawlRunResponse(BaseModel):
    crawl_run_id: int
    status: str


class CrawlRunProgressResponse(BaseModel):
    id: int
    project_id: int
    status: str
    pages_crawled: int
    max_pages: int | None = None
    started_at: datetime | None
    finished_at: datetime | None
    active: bool
    phase: str | None = None
    phase_current: int | None = None
    phase_total: int | None = None
    phase_label: str | None = None
    error_message: str | None = None


_PHASE_LABELS: dict[str, str] = {
    "crawling": "Crawling pages",
    "site_checks": "Running site checks",
    "page_checks": "Running page checks",
    "pagespeed": "Running PageSpeed checks",
    "cross_page_checks": "Running cross-page checks",
    "homepage_checks": "Running homepage checks",
    "scoring": "Calculating scores",
    "completed": "Completed",
    "failed": "Failed",
}


def _phase_label(phase: str | None) -> str | None:
    if not phase:
        return None
    return _PHASE_LABELS.get(phase, phase.replace("_", " ").capitalize())


class CrawlRunListItemResponse(BaseModel):
    id: int
    project_id: int
    status: str
    total_pages: int
    started_at: datetime | None
    finished_at: datetime | None


class CrawlRunListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[CrawlRunListItemResponse]


class RunAuditResponse(BaseModel):
    crawl_run_id: int
    issues_created: int
    scores_created: int


class PageVitalsResponse(BaseModel):
    mobile_performance_score: int | None = None
    mobile_lcp_ms: float | None = None
    mobile_inp_ms: float | None = None
    mobile_cls: float | None = None
    desktop_performance_score: int | None = None
    desktop_lcp_ms: float | None = None
    desktop_inp_ms: float | None = None
    desktop_cls: float | None = None


class PageDetailsResponse(BaseModel):
    id: int
    url: str
    title: str | None
    meta_description: str | None
    canonical_url: str | None
    word_count: int | None
    status_code: int | None
    response_time_ms: float | None
    vitals: PageVitalsResponse | None = None


class AuditIssueResponse(BaseModel):
    id: str
    rule_id: str
    category: str
    severity: str
    target_url: str | None
    message: str
    page_details: PageDetailsResponse | None = None


class AuditIssueListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[AuditIssueResponse]


class ScoreItemResponse(BaseModel):
    category: str
    score: float


class ScoreListResponse(BaseModel):
    items: list[ScoreItemResponse]


class CrawlRunSummaryResponse(BaseModel):
    overall_score: float | None
    category_scores: dict[str, float]
    total_pages: int
    total_issues_by_severity: dict[str, int]


class CrawledPageListItemResponse(BaseModel):
    id: int
    url: str
    title: str | None
    status_code: int | None
    word_count: int | None
    response_time_ms: float | None
    issue_count: int


class CrawledPageListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[CrawledPageListItemResponse]


class ReportIssueResponse(BaseModel):
    url: str | None = None
    rule: str
    severity: str
    message: str
    scope: str | None = None
    category: str | None = None
    id: str | None = None


class ReportCategoryResponse(BaseModel):
    name: str
    score: float | None
    issues: list[ReportIssueResponse]


class ReportSiteIssueResponse(BaseModel):
    id: str
    rule: str
    severity: str
    category: str
    message: str
    scope: str


class ReportPageIssueItemResponse(BaseModel):
    id: str
    rule: str
    severity: str
    category: str
    message: str
    scope: str = "page"


class ReportPageIssueGroupResponse(BaseModel):
    url: str
    issue_count: int
    issues: list[ReportPageIssueItemResponse]


class ReportSummaryResponse(BaseModel):
    total_pages: int
    total_issues: int
    site_issue_count: int
    pages_with_issues: int
    page_issue_count: int
    summary_text: str
    issues_by_severity: dict[str, int]


class RecommendationResponse(BaseModel):
    rule: str
    severity: str
    category: str
    message: str
    pages_affected: int


class ReportResponse(BaseModel):
    project: dict[str, object | None]
    crawl_date: str | None
    overall_score: float | None
    category_scores: dict[str, float]
    summary: ReportSummaryResponse
    site_issues: list[ReportSiteIssueResponse]
    page_issues: list[ReportPageIssueGroupResponse]
    categories: list[ReportCategoryResponse]
    recommendations: list[RecommendationResponse]


class DiffIssueResponse(BaseModel):
    rule_id: str
    category: str
    severity: str
    target_url: str | None
    message: str


class CrawlRunDiffResponse(BaseModel):
    current_run_id: int
    compare_to_run_id: int
    new_issues: list[DiffIssueResponse]
    resolved_issues: list[DiffIssueResponse]
    persisting_issues: list[DiffIssueResponse]
    counts: dict[str, int]


def _require_crawl_run(crawl_run_id: int) -> CrawlRun:
    crawl_run = storage.get_run(crawl_run_id)
    if crawl_run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Crawl run {crawl_run_id} not found.",
        )
    return crawl_run


def _site_start_url_for_crawl(crawl_run_id: int, domain: str | None) -> str:
    """Resolve an absolute root URL for SITE asset fetches on re-audit."""
    with SessionLocal() as db:
        first_page = db.scalars(
            select(CrawledPage)
            .where(CrawledPage.crawl_id == crawl_run_id)
            .order_by(CrawledPage.id.asc())
            .limit(1)
        ).first()
        if first_page and first_page.url:
            from urllib.parse import urlparse

            parsed = urlparse(first_page.url)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}/"

    raw = (domain or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw if raw.endswith("/") else f"{raw}/"
    if raw:
        return f"https://{raw.rstrip('/')}/"
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Cannot resolve site root URL for site checks.",
    )


def _build_page_vitals(page: CrawledPage) -> PageVitalsResponse | None:
    if not getattr(page, "page_vitals", None):
        return None
    vitals = {vital.strategy: vital for vital in page.page_vitals}
    mobile = vitals.get("mobile")
    desktop = vitals.get("desktop")
    return PageVitalsResponse(
        mobile_performance_score=mobile.performance_score if mobile else None,
        mobile_lcp_ms=mobile.lcp_ms if mobile else None,
        mobile_inp_ms=mobile.inp_ms if mobile else None,
        mobile_cls=mobile.cls if mobile else None,
        desktop_performance_score=desktop.performance_score if desktop else None,
        desktop_lcp_ms=desktop.lcp_ms if desktop else None,
        desktop_inp_ms=desktop.inp_ms if desktop else None,
        desktop_cls=desktop.cls if desktop else None,
    )


@router.get("", response_model=CrawlRunListResponse)
async def list_crawl_runs(
    project_id: int | None = Query(default=None, ge=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
) -> CrawlRunListResponse:
    with SessionLocal() as db:
        filters = []
        if project_id is not None:
            filters.append(CrawlRun.project_id == project_id)

        total = db.scalar(select(func.count()).select_from(CrawlRun).where(*filters)) or 0
        crawl_runs = db.scalars(
            select(CrawlRun)
            .where(*filters)
            .order_by(CrawlRun.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()

        return CrawlRunListResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[
                CrawlRunListItemResponse(
                    id=crawl_run.id,
                    project_id=crawl_run.project_id,
                    status=crawl_run.status,
                    total_pages=crawl_run.total_urls,
                    started_at=crawl_run.started_at,
                    finished_at=crawl_run.finished_at,
                )
                for crawl_run in crawl_runs
            ],
        )


@router.post("", response_model=CrawlRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_crawl_run(payload: CreateCrawlRunRequest) -> CrawlRunResponse:
    project = storage.get_project(payload.project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {payload.project_id} not found.",
        )

    crawl_run = storage.create_run(payload.project_id, max_pages=payload.max_pages)
    start_crawl_run(
        crawl_run_id=crawl_run.id,
        start_url=str(payload.start_url),
        max_pages=payload.max_pages,
        max_depth=payload.max_depth,
        enable_pagespeed=payload.enable_pagespeed,
    )

    return CrawlRunResponse(crawl_run_id=crawl_run.id, status="pending")


@router.get("/{crawl_run_id}", response_model=CrawlRunProgressResponse)
async def get_crawl_run(crawl_run_id: int) -> CrawlRunProgressResponse:
    crawl_run = _require_crawl_run(crawl_run_id)
    active = is_active(crawl_run.id)

    # Heal runs left in running/enriching after a server reload killed the worker.
    # Keep this path fast — never run the full rules engine inline on poll requests.
    if crawl_run.status in {"running", "enriching"} and not active:
        with SessionLocal() as db:
            page_count = (
                db.scalar(
                    select(func.count())
                    .select_from(CrawledPage)
                    .where(CrawledPage.crawl_id == crawl_run_id)
                )
                or 0
            )
            score_count = (
                db.scalar(
                    select(func.count())
                    .select_from(CrawlRunScore)
                    .where(CrawlRunScore.crawl_id == crawl_run_id)
                )
                or 0
            )
        if page_count > 0 and score_count > 0:
            storage.set_run_completed(crawl_run_id)
            crawl_run = _require_crawl_run(crawl_run_id)
        elif page_count > 0:
            # Finish scoring in the background so progress polls stay responsive.
            storage.set_run_enriching(crawl_run_id)
            if crawl_run_id not in _ORPHAN_AUDIT_STARTED:
                _ORPHAN_AUDIT_STARTED.add(crawl_run_id)

                async def _finish_orphan_audit(run_id: int = crawl_run_id) -> None:
                    try:
                        await asyncio.to_thread(rule_engine.run, run_id)
                        storage.set_run_completed(run_id)
                    except Exception:
                        storage.set_run_failed(run_id)
                    finally:
                        _ORPHAN_AUDIT_STARTED.discard(run_id)

                task = asyncio.create_task(
                    _finish_orphan_audit(), name=f"orphan-audit-{crawl_run_id}"
                )
                _ACTIVE_ORPHAN_TASKS.add(task)
                task.add_done_callback(_ACTIVE_ORPHAN_TASKS.discard)
            crawl_run = _require_crawl_run(crawl_run_id)
        else:
            storage.set_run_failed(crawl_run_id)
            crawl_run = _require_crawl_run(crawl_run_id)

    max_p = getattr(crawl_run, "max_pages", None) or getattr(crawl_run, "phase_total", None)
    return CrawlRunProgressResponse(
        id=crawl_run.id,
        project_id=crawl_run.project_id,
        status=crawl_run.status,
        pages_crawled=max(crawl_run.total_urls, get_progress(crawl_run.id) or 0),
        max_pages=max_p,
        started_at=crawl_run.started_at,
        finished_at=crawl_run.finished_at,
        active=is_active(crawl_run.id) or any(
            not t.done() and t.get_name() == f"orphan-audit-{crawl_run.id}" for t in _ACTIVE_ORPHAN_TASKS
        ),
        phase=getattr(crawl_run, "phase", None),
        phase_current=getattr(crawl_run, "phase_current", None),
        phase_total=getattr(crawl_run, "phase_total", None) or max_p,
        phase_label=_phase_label(getattr(crawl_run, "phase", None)),
        error_message=getattr(crawl_run, "error_message", None),
    )


@router.delete("/{crawl_run_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def remove_crawl_run(crawl_run_id: int) -> Response:
    cancel_crawl_run(crawl_run_id)
    with SessionLocal() as db:
        deleted = delete_crawl_run(db, crawl_run_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Crawl run {crawl_run_id} not found.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{crawl_run_id}/summary", response_model=CrawlRunSummaryResponse)
async def get_crawl_run_summary(crawl_run_id: int) -> CrawlRunSummaryResponse:
    def _build() -> CrawlRunSummaryResponse:
        _require_crawl_run(crawl_run_id)
        with SessionLocal() as db:
            total_pages = db.scalar(
                select(func.count()).select_from(CrawledPage).where(CrawledPage.crawl_id == crawl_run_id)
            ) or 0

            scores = db.scalars(
                select(CrawlRunScore)
                .where(CrawlRunScore.crawl_id == crawl_run_id)
                .order_by(CrawlRunScore.category.asc())
            ).all()
            category_scores = {score.category: score.score for score in scores if score.category != "overall"}
            overall_score = next((score.score for score in scores if score.category == "overall"), None)

            severity_counts = count_issues_by_severity(db, crawl_run_id)

            return CrawlRunSummaryResponse(
                overall_score=overall_score,
                category_scores=category_scores,
                total_pages=total_pages,
                total_issues_by_severity=severity_counts,
            )

    return await asyncio.to_thread(_build)


@router.post("/{crawl_run_id}/run-audit", response_model=RunAuditResponse)
async def run_audit(crawl_run_id: int) -> RunAuditResponse:
    crawl_run = _require_crawl_run(crawl_run_id)
    if crawl_run.status not in {"completed", "failed", "enriching"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Audit can only run after the crawl has produced pages.",
        )
    with SessionLocal() as db:
        page_count = (
            db.scalar(
                select(func.count())
                .select_from(CrawledPage)
                .where(CrawledPage.crawl_id == crawl_run_id)
            )
            or 0
        )
    if page_count == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No crawled pages available to audit.",
        )

    start_url = _site_start_url_for_crawl(crawl_run_id, crawl_run.domain)
    try:
        from app.checks.orchestrator import run_audit as run_orchestrated_audit

        # Pages already exist — re-run check phases + finish (scores / finished_at).
        ctx = await run_orchestrated_audit(
            crawl_run_id,
            start_url=start_url,
            steps=("site", "page", "cross_page", "homepage", "finish"),
        )
        score_result = ctx.results.get("scores") or {}
        result = {
            "issues_created": int(score_result.get("issues_created", 0)),
            "scores_created": int(score_result.get("scores_created", 0)),
        }
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return RunAuditResponse(
        crawl_run_id=crawl_run_id,
        issues_created=result["issues_created"],
        scores_created=result["scores_created"],
    )


@router.get("/{crawl_run_id}/issues", response_model=AuditIssueListResponse)
async def get_crawl_run_issues(
    crawl_run_id: int,
    category: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> AuditIssueListResponse:
    _require_crawl_run(crawl_run_id)

    with SessionLocal() as db:
        rules_by_id = {rule.id: rule for rule in rule_engine.rules}
        views = load_issue_views(
            db,
            crawl_run_id,
            category=category,
            severity=severity,
            rules_by_id=rules_by_id,
        )
        views.sort(key=lambda item: item.id)
        total = len(views)
        page_views = views[(page - 1) * page_size : page * page_size]

        page_urls = {view.url for view in page_views if view.scope == "page" and view.url}
        pages_by_url: dict[str, CrawledPage] = {}
        if page_urls:
            page_rows = (
                db.scalars(
                    select(CrawledPage)
                    .where(
                        CrawledPage.crawl_id == crawl_run_id,
                        CrawledPage.url.in_(page_urls),
                    )
                    .options(joinedload(CrawledPage.page_vitals))
                )
                .unique()
                .all()
            )
            pages_by_url = {row.url: row for row in page_rows}

        items: list[AuditIssueResponse] = []
        for view in page_views:
            crawled_page = pages_by_url.get(view.url) if view.scope == "page" and view.url else None
            items.append(
                AuditIssueResponse(
                    id=view.id,
                    rule_id=view.check_name,
                    category=view.category,
                    severity=view.severity,
                    target_url=view.url,
                    message=view.details,
                    page_details=(
                        PageDetailsResponse(
                            id=crawled_page.id,
                            url=crawled_page.url,
                            title=crawled_page.title,
                            meta_description=crawled_page.meta_description,
                            canonical_url=crawled_page.canonical_url,
                            word_count=crawled_page.word_count,
                            status_code=crawled_page.status_code,
                            response_time_ms=crawled_page.response_time_ms,
                            vitals=_build_page_vitals(crawled_page),
                        )
                        if crawled_page
                        else None
                    ),
                )
            )

        return AuditIssueListResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=items,
        )


@router.get("/{crawl_run_id}/pages", response_model=CrawledPageListResponse)
async def get_crawl_run_pages(
    crawl_run_id: int,
    status_code: int | None = Query(default=None),
    issue_category: str | None = Query(default=None),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="url"),
    sort_order: str = Query(default="asc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> CrawledPageListResponse:
    _require_crawl_run(crawl_run_id)

    with SessionLocal() as db:
        filters = [CrawledPage.crawl_id == crawl_run_id]
        if status_code is not None:
            filters.append(CrawledPage.status_code == status_code)
        if search:
            filters.append(CrawledPage.url.ilike(f"%{search}%"))

        if issue_category:
            rules_by_id = {rule.id: rule for rule in rule_engine.rules}
            category_urls = {
                view.url
                for view in load_issue_views(
                    db,
                    crawl_run_id,
                    category=issue_category,
                    rules_by_id=rules_by_id,
                )
                if view.url
            }
            if not category_urls:
                return CrawledPageListResponse(total=0, page=page, page_size=page_size, items=[])
            filters.append(CrawledPage.url.in_(category_urls))

        query = select(CrawledPage).where(*filters)
        count_query = select(func.count()).select_from(CrawledPage).where(*filters)

        sort_map = {
            "url": CrawledPage.url,
            "status_code": CrawledPage.status_code,
            "word_count": CrawledPage.word_count,
            "response_time_ms": CrawledPage.response_time_ms,
            "id": CrawledPage.id,
        }
        sort_column = sort_map.get(sort_by, CrawledPage.url)
        query = query.order_by(sort_column.desc() if sort_order == "desc" else sort_column.asc())

        total = db.scalar(count_query) or 0
        pages = db.scalars(
            query.offset((page - 1) * page_size).limit(page_size)
        ).all()

        issue_counts = dict(
            db.execute(
                select(PageIssue.url, func.count())
                .where(PageIssue.crawl_id == crawl_run_id)
                .group_by(PageIssue.url)
            ).all()
        )

        return CrawledPageListResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[
                CrawledPageListItemResponse(
                    id=crawled_page.id,
                    url=crawled_page.url,
                    title=crawled_page.title,
                    status_code=crawled_page.status_code,
                    word_count=crawled_page.word_count,
                    response_time_ms=crawled_page.response_time_ms,
                    issue_count=int(issue_counts.get(crawled_page.url, 0)),
                )
                for crawled_page in pages
            ],
        )


@router.get("/{crawl_run_id}/scores", response_model=ScoreListResponse)
async def get_crawl_run_scores(crawl_run_id: int) -> ScoreListResponse:
    _require_crawl_run(crawl_run_id)
    with SessionLocal() as db:
        scores = db.scalars(
            select(CrawlRunScore)
            .where(CrawlRunScore.crawl_id == crawl_run_id)
            .order_by(CrawlRunScore.category.asc())
        ).all()

        return ScoreListResponse(
            items=[ScoreItemResponse(category=score.category, score=score.score) for score in scores]
        )


def _issue_match_key(issue: IssueView) -> tuple[str, str]:
    return (issue.url or "", issue.check_name)


def _to_diff_issue(issue: IssueView) -> DiffIssueResponse:
    return DiffIssueResponse(
        rule_id=issue.check_name,
        category=issue.category,
        severity=issue.severity,
        target_url=issue.url,
        message=issue.details,
    )


@router.get("/{crawl_run_id}/diff", response_model=CrawlRunDiffResponse)
async def get_crawl_run_diff(
    crawl_run_id: int,
    compare_to: int = Query(..., ge=1, description="Previous crawl run id to compare against"),
) -> CrawlRunDiffResponse:
    current = _require_crawl_run(crawl_run_id)
    previous = _require_crawl_run(compare_to)
    if current.project_id != previous.project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="compare_to must belong to the same project as the current crawl run.",
        )
    if crawl_run_id == compare_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="compare_to must be a different crawl run.",
        )

    with SessionLocal() as db:
        rules_by_id = {rule.id: rule for rule in rule_engine.rules}
        current_issues = load_issue_views(db, crawl_run_id, rules_by_id=rules_by_id)
        previous_issues = load_issue_views(db, compare_to, rules_by_id=rules_by_id)

        current_by_key: dict[tuple[str, str], IssueView] = {}
        for issue in current_issues:
            key = _issue_match_key(issue)
            current_by_key.setdefault(key, issue)

        previous_by_key: dict[tuple[str, str], IssueView] = {}
        for issue in previous_issues:
            key = _issue_match_key(issue)
            previous_by_key.setdefault(key, issue)

        current_keys = set(current_by_key)
        previous_keys = set(previous_by_key)

        new_issues = [_to_diff_issue(current_by_key[key]) for key in sorted(current_keys - previous_keys)]
        resolved_issues = [
            _to_diff_issue(previous_by_key[key]) for key in sorted(previous_keys - current_keys)
        ]
        persisting_issues = [
            _to_diff_issue(current_by_key[key]) for key in sorted(current_keys & previous_keys)
        ]

        return CrawlRunDiffResponse(
            current_run_id=crawl_run_id,
            compare_to_run_id=compare_to,
            new_issues=new_issues,
            resolved_issues=resolved_issues,
            persisting_issues=persisting_issues,
            counts={
                "new": len(new_issues),
                "resolved": len(resolved_issues),
                "persisting": len(persisting_issues),
            },
        )


@router.get("/{crawl_run_id}/report", response_model=ReportResponse)
async def get_crawl_run_report(crawl_run_id: int) -> ReportResponse:
    _require_crawl_run(crawl_run_id)
    try:
        report = await asyncio.to_thread(report_service.build_report, crawl_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ReportResponse(**report)


@router.get("/{crawl_run_id}/export/csv")
async def export_crawl_run_csv(crawl_run_id: int) -> StreamingResponse:
    _require_crawl_run(crawl_run_id)
    filename = f"crawl-run-{crawl_run_id}-issues.csv"
    return StreamingResponse(
        report_service.iter_csv_rows(crawl_run_id),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{crawl_run_id}/export/xlsx")
async def export_crawl_run_xlsx(crawl_run_id: int) -> StreamingResponse:
    _require_crawl_run(crawl_run_id)
    file_path, filename = await asyncio.to_thread(report_service.generate_xlsx_file, crawl_run_id)
    return StreamingResponse(
        iter_file_chunks(file_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        background=BackgroundTask(remove_file, file_path),
    )


@router.get("/{crawl_run_id}/export/pdf")
async def export_crawl_run_pdf(crawl_run_id: int) -> StreamingResponse:
    _require_crawl_run(crawl_run_id)
    try:
        file_path, filename = await asyncio.to_thread(report_service.generate_pdf_file, crawl_run_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PDF export failed: {exc}",
        ) from exc
    return StreamingResponse(
        iter_file_chunks(file_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        background=BackgroundTask(remove_file, file_path),
    )
