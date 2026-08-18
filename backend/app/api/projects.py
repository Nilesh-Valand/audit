from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.db.database import SessionLocal
from app.models import CrawlRun, CrawlRunScore, Project
from app.services.crawl_runs import cancel_crawl_run
from app.services.deletions import delete_project

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=255)


class ProjectResponse(BaseModel):
    id: int
    domain: str
    created_at: datetime


class ProjectListItemResponse(BaseModel):
    id: int
    domain: str
    created_at: datetime
    latest_run_id: int | None = None
    latest_run_status: str | None = None
    latest_run_finished_at: datetime | None = None
    latest_run_started_at: datetime | None = None
    overall_score: float | None = None


class ProjectListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ProjectListItemResponse]


class ScoreHistoryItemResponse(BaseModel):
    crawl_run_id: int
    date: datetime | None
    overall_score: float | None
    category_scores: dict[str, float]


class ScoreHistoryResponse(BaseModel):
    items: list[ScoreHistoryItemResponse]


def _list_projects_sync(page: int, page_size: int) -> ProjectListResponse:
    with SessionLocal() as db:
        total = db.scalar(select(func.count()).select_from(Project)) or 0
        projects = db.scalars(
            select(Project)
            .order_by(Project.created_at.desc(), Project.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()

        items: list[ProjectListItemResponse] = []
        for project in projects:
            latest_run = db.scalars(
                select(CrawlRun)
                .where(CrawlRun.project_id == project.id)
                .order_by(CrawlRun.id.desc())
                .limit(1)
            ).first()
            overall_score: float | None = None
            if latest_run is not None and latest_run.status == "completed":
                overall_score = db.scalar(
                    select(CrawlRunScore.score).where(
                        CrawlRunScore.crawl_id == latest_run.id,
                        CrawlRunScore.category == "overall",
                    )
                )
            items.append(
                ProjectListItemResponse(
                    id=project.id,
                    domain=project.domain,
                    created_at=project.created_at,
                    latest_run_id=latest_run.id if latest_run else None,
                    latest_run_status=latest_run.status if latest_run else None,
                    latest_run_finished_at=latest_run.finished_at if latest_run else None,
                    latest_run_started_at=latest_run.started_at if latest_run else None,
                    overall_score=overall_score,
                )
            )

        return ProjectListResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=items,
        )


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
) -> ProjectListResponse:
    return await asyncio.to_thread(_list_projects_sync, page, page_size)


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(payload: CreateProjectRequest) -> ProjectResponse:
    domain = payload.domain.strip()
    with SessionLocal() as db:
        project = Project(domain=domain)
        db.add(project)
        db.commit()
        db.refresh(project)
        return ProjectResponse(id=project.id, domain=project.domain, created_at=project.created_at)


@router.get("/{project_id}/score-history", response_model=ScoreHistoryResponse)
async def get_project_score_history(project_id: int) -> ScoreHistoryResponse:
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found.",
            )

        crawl_runs = list(
            db.scalars(
                select(CrawlRun)
                .where(CrawlRun.project_id == project_id)
                .options(selectinload(CrawlRun.scores))
            ).all()
        )
        crawl_runs.sort(
            key=lambda run: (
                run.finished_at or run.started_at or datetime.min,
                run.id,
            )
        )

        items: list[ScoreHistoryItemResponse] = []
        for crawl_run in crawl_runs:
            if not crawl_run.scores:
                continue
            category_scores = {
                score.category: score.score
                for score in crawl_run.scores
                if score.category != "overall"
            }
            overall_score = next(
                (score.score for score in crawl_run.scores if score.category == "overall"),
                None,
            )
            items.append(
                ScoreHistoryItemResponse(
                    crawl_run_id=crawl_run.id,
                    date=crawl_run.finished_at or crawl_run.started_at,
                    overall_score=overall_score,
                    category_scores=category_scores,
                )
            )

        return ScoreHistoryResponse(items=items)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def remove_project(project_id: int) -> Response:
    with SessionLocal() as db:
        run_ids = list(
            db.scalars(select(CrawlRun.id).where(CrawlRun.project_id == project_id)).all()
        )
    for run_id in run_ids:
        cancel_crawl_run(run_id)

    with SessionLocal() as db:
        deleted = delete_project(db, project_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
