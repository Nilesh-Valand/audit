from __future__ import annotations

import asyncio
from pathlib import Path
from sqlalchemy import select, func
import pytest

from app.crawler.crawler import CrawlerService
from app.crawler.storage import CrawlStorage
from app.models import CrawlPage, Project

@pytest.mark.asyncio
async def test_crawler_sitemap_discovery_and_streaming(session_factory, fixture_site_no_robots):
    storage = CrawlStorage(session_factory=session_factory, flush_size=1)
    with session_factory() as db:
        project = Project(domain="127.0.0.1")
        db.add(project)
        db.commit()
        db.refresh(project)

        crawl_run = storage.create_run(project.id)
        crawl_id = crawl_run.id

    crawler = CrawlerService(
        start_url=fixture_site_no_robots,
        max_pages=50,
        max_depth=5,
        concurrency=5,
        request_delay=0.0,
        storage=storage,
        render_js_when_thin=False,
    )

    await crawler.crawl(crawl_id)

    with session_factory() as db:
        pages = db.scalars(
            select(CrawlPage).where(CrawlPage.crawl_id == crawl_id)
        ).all()
        assert len(pages) > 0
        urls = {p.url for p in pages}
        assert any(p.endswith("/") or p.endswith("/index.html") for p in urls)
