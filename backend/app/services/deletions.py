from __future__ import annotations

import shutil

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.models import (
    CrawledPage,
    CrawlRun,
    CrawlRunScore,
    PageIssue,
    PageLink,
    PageTechnicalDetails,
    PageVital,
    Project,
    SiteIssue,
    SitemapFinding,
)
from app.paths import SNAPSHOT_ROOT


def _purge_crawl_run_rows(db: Session, crawl_run_id: int) -> None:
    page_ids = list(
        db.scalars(select(CrawledPage.id).where(CrawledPage.crawl_id == crawl_run_id)).all()
    )

    if page_ids:
        db.execute(delete(PageLink).where(PageLink.crawl_page_id.in_(page_ids)))
        db.execute(delete(PageVital).where(PageVital.crawl_page_id.in_(page_ids)))
        db.execute(
            delete(PageTechnicalDetails).where(PageTechnicalDetails.crawl_page_id.in_(page_ids))
        )

    db.execute(delete(SiteIssue).where(SiteIssue.crawl_id == crawl_run_id))
    db.execute(delete(PageIssue).where(PageIssue.crawl_id == crawl_run_id))
    db.execute(delete(SitemapFinding).where(SitemapFinding.crawl_id == crawl_run_id))
    db.execute(delete(CrawlRunScore).where(CrawlRunScore.crawl_id == crawl_run_id))
    db.execute(delete(CrawledPage).where(CrawledPage.crawl_id == crawl_run_id))
    db.execute(delete(CrawlRun).where(CrawlRun.id == crawl_run_id))


def _remove_snapshot_dir(crawl_run_id: int) -> None:
    snapshot_dir = SNAPSHOT_ROOT / str(crawl_run_id)
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir, ignore_errors=True)


def delete_crawl_run(db: Session, crawl_run_id: int) -> bool:
    exists = db.scalar(select(CrawlRun.id).where(CrawlRun.id == crawl_run_id))
    if exists is None:
        return False

    _purge_crawl_run_rows(db, crawl_run_id)
    db.commit()
    _remove_snapshot_dir(crawl_run_id)
    return True


def delete_project(db: Session, project_id: int) -> bool:
    exists = db.scalar(select(Project.id).where(Project.id == project_id))
    if exists is None:
        return False

    run_ids = list(
        db.scalars(select(CrawlRun.id).where(CrawlRun.project_id == project_id)).all()
    )
    for run_id in run_ids:
        _purge_crawl_run_rows(db, run_id)

    # Legacy GSC tables may still exist from older migrations; clear them without ORM models.
    for table in ("gsc_snapshots", "gsc_credentials"):
        try:
            db.execute(text(f"DELETE FROM {table} WHERE project_id = :project_id"), {"project_id": project_id})
        except Exception:
            pass

    db.execute(delete(Project).where(Project.id == project_id))
    db.commit()

    for run_id in run_ids:
        _remove_snapshot_dir(run_id)

    return True
