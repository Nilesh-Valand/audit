"""Assert SITE vs PAGE issue scoping for robots.txt and duplicate titles."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.checks.orchestrator import run_audit
from app.crawler.storage import CrawlStorage
from app.models import CrawlPage, PageIssue, Project, SiteIssue


async def test_robots_and_duplicate_title_site_scoping(
    session_factory: sessionmaker[Session],
    fixture_site_no_robots: str,
) -> None:
    """Missing robots.txt and a duplicate title group are site-scoped once each.

    Fixture site: 3 linked pages, no robots.txt, shared title on 2 pages.
    """
    storage = CrawlStorage(session_factory=session_factory, flush_size=10)

    with session_factory() as db:
        project = Project(domain=fixture_site_no_robots.rstrip("/"))
        db.add(project)
        db.commit()
        db.refresh(project)
        project_id = project.id

    crawl = storage.create_run(project_id)

    await run_audit(
        crawl.id,
        start_url=fixture_site_no_robots,
        max_pages=10,
        max_depth=3,
        enable_pagespeed=False,
        storage=storage,
        session_factory=session_factory,
        # Skip homepage/finish — assertions only need crawl → cross_page.
        steps=["crawl", "site", "page", "cross_page"],
    )

    with session_factory() as db:
        pages = list(
            db.scalars(
                select(CrawlPage).where(CrawlPage.crawl_id == crawl.id)
            ).all()
        )
        site_issues = list(
            db.scalars(
                select(SiteIssue).where(SiteIssue.crawl_id == crawl.id)
            ).all()
        )
        page_issues = list(
            db.scalars(
                select(PageIssue).where(PageIssue.crawl_id == crawl.id)
            ).all()
        )

    assert len(pages) == 3, f"Expected 3 crawled pages, got {len(pages)}: {[p.url for p in pages]}"

    robots_site = [
        issue
        for issue in site_issues
        if issue.check_name == "robots_txt_missing"
    ]
    assert len(robots_site) == 1
    assert robots_site[0].status == "fail"

    robots_page = [
        issue
        for issue in page_issues
        if "robots.txt" in issue.check_name.lower()
        or "robots.txt" in issue.details.lower()
    ]
    assert robots_page == [], (
        "page_issues must not mention robots.txt; "
        f"found {[ (i.url, i.check_name, i.details) for i in robots_page ]}"
    )

    duplicate_title_site = [
        issue
        for issue in site_issues
        if issue.check_name == "duplicate_title"
    ]
    assert len(duplicate_title_site) == 1, (
        "Phase 4 must write exactly one site_issues row per duplicate-title group, "
        f"got {len(duplicate_title_site)}: {[i.details for i in duplicate_title_site]}"
    )
    assert duplicate_title_site[0].status == "fail"
    assert "2 pages" in duplicate_title_site[0].details

    duplicate_title_page = [
        issue for issue in page_issues if issue.check_name == "duplicate_title"
    ]
    assert duplicate_title_page == []
