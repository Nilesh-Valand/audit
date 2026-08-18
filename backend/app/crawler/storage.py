from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models import CrawlPage, CrawlRun, PageLink, PageTechnicalDetails, Project
from app.crawler.extractor import ExtractedPage
from app.crawler.normalize import normalize_url
from app.paths import SNAPSHOT_ROOT

SessionFactory = Callable[[], Session]


@dataclass(slots=True)
class PendingPage:
    crawl_run_id: int
    page: ExtractedPage


class CrawlStorage:
    def __init__(
        self,
        *,
        session_factory: SessionFactory = SessionLocal,
        flush_size: int = 25,
        snapshot_root: Path | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._flush_size = flush_size
        self._snapshot_root = snapshot_root or SNAPSHOT_ROOT
        self._buffer: list[PendingPage] = []
        self._lock = asyncio.Lock()
        self._snapshot_root.mkdir(parents=True, exist_ok=True)

    async def add(self, crawl_run_id: int, page: ExtractedPage) -> None:
        async with self._lock:
            self._buffer.append(PendingPage(crawl_run_id=crawl_run_id, page=page))
            should_flush = len(self._buffer) >= self._flush_size

        if should_flush:
            await self.flush()

    async def flush(self) -> int:
        async with self._lock:
            if not self._buffer:
                return 0
            batch = self._buffer
            self._buffer = []

        return await asyncio.to_thread(self._write_batch, batch)

    def create_run(self, project_id: int, max_pages: int = 200) -> CrawlRun:
        with self._session_factory() as db:
            project = db.get(Project, project_id)
            if project is None:
                raise ValueError(f"Project {project_id} does not exist.")

            crawl_run = CrawlRun(
                project_id=project_id,
                domain=project.domain,
                status="pending",
                started_at=None,
                finished_at=None,
                total_urls=0,
                max_pages=max_pages,
                phase_total=max_pages,
            )
            db.add(crawl_run)
            db.commit()
            db.refresh(crawl_run)
            db.expunge(crawl_run)
            return crawl_run

    def get_run(self, crawl_run_id: int) -> CrawlRun | None:
        with self._session_factory() as db:
            crawl_run = db.get(CrawlRun, crawl_run_id)
            if crawl_run is not None:
                db.expunge(crawl_run)
            return crawl_run

    def get_project(self, project_id: int) -> Project | None:
        with self._session_factory() as db:
            project = db.get(Project, project_id)
            if project is not None:
                db.expunge(project)
            return project

    def set_run_started(self, crawl_run_id: int, max_pages: int | None = None) -> None:
        self._update_run_status(
            crawl_run_id,
            status="running",
            started_at=datetime.now(UTC),
            finished_at=None,
            phase="crawling",
            phase_current=0,
            phase_total=max_pages,
            error_message=None,
        )

    def set_run_completed(self, crawl_run_id: int) -> None:
        self._update_run_status(
            crawl_run_id,
            status="completed",
            finished_at=datetime.now(UTC),
            phase="completed",
            phase_current=None,
            phase_total=None,
            error_message=None,
        )

    def set_run_enriching(self, crawl_run_id: int) -> None:
        self._update_run_status(
            crawl_run_id,
            status="enriching",
        )

    def set_run_failed(
        self,
        crawl_run_id: int,
        *,
        error_message: str | None = None,
    ) -> None:
        self._update_run_status(
            crawl_run_id,
            status="failed",
            finished_at=datetime.now(UTC),
            phase="failed",
            error_message=(error_message or "")[:2000] or None,
        )

    def set_run_phase(
        self,
        crawl_run_id: int,
        *,
        phase: str,
        current: int | None = None,
        total: int | None = None,
        status: str | None = None,
        error_message: str | None | object = ...,
    ) -> None:
        """Update live phase progress without changing finished_at."""
        self._update_run_status(
            crawl_run_id,
            status=status if status is not None else ...,
            phase=phase,
            phase_current=current,
            phase_total=total,
            error_message=error_message,
        )

    def save_site_checks(
        self,
        crawl_run_id: int,
        *,
        robots_txt_found: bool,
        robots_txt_valid: bool | None,
        robots_txt_ai_disallowed: list[str],
        robots_txt_raw: str | None,
        llms_txt_present: bool,
        soft_404=None,
    ) -> None:
        with self._session_factory() as db:
            crawl_run = db.get(CrawlRun, crawl_run_id)
            if crawl_run is None:
                return
            crawl_run.robots_txt_found = robots_txt_found
            crawl_run.robots_txt_valid = robots_txt_valid
            crawl_run.robots_txt_ai_disallowed = list(robots_txt_ai_disallowed)
            crawl_run.robots_txt_raw = robots_txt_raw
            crawl_run.llms_txt_present = llms_txt_present
            if soft_404 is not None:
                crawl_run.soft_404_probe_url = soft_404.url
                crawl_run.soft_404_status_code = soft_404.status_code
                crawl_run.soft_404_word_count = soft_404.word_count
                crawl_run.soft_404_is_soft = soft_404.is_soft
                crawl_run.soft_404_detail = soft_404.detail
            db.commit()

    def _update_run_status(
        self,
        crawl_run_id: int,
        *,
        status: str | object = ...,
        started_at: datetime | None | object = ...,
        finished_at: datetime | None | object = ...,
        phase: str | None | object = ...,
        phase_current: int | None | object = ...,
        phase_total: int | None | object = ...,
        error_message: str | None | object = ...,
    ) -> None:
        with self._session_factory() as db:
            crawl_run = db.get(CrawlRun, crawl_run_id)
            if crawl_run is None:
                return
            if status is not ...:
                crawl_run.status = status  # type: ignore[assignment]
            if started_at is not ...:
                crawl_run.started_at = started_at  # type: ignore[assignment]
            if finished_at is not ...:
                crawl_run.finished_at = finished_at  # type: ignore[assignment]
            if phase is not ...:
                crawl_run.phase = phase  # type: ignore[assignment]
            if phase_current is not ...:
                crawl_run.phase_current = phase_current  # type: ignore[assignment]
            if phase_total is not ...:
                crawl_run.phase_total = phase_total  # type: ignore[assignment]
            if error_message is not ...:
                crawl_run.error_message = error_message  # type: ignore[assignment]
            db.commit()

    def _write_batch(self, batch: list[PendingPage]) -> int:
        if not batch:
            return 0

        written = 0
        with self._session_factory() as db:
            run_counts: dict[int, int] = {}
            for item in batch:
                page = item.page
                crawl_id = item.crawl_run_id
                canonical_url = normalize_url(page.url)
                raw_url = page.raw_url or page.url
                html_path = self._save_html_snapshot(crawl_id, canonical_url, page.html)

                insert_stmt = (
                    sqlite_insert(CrawlPage)
                    .values(
                        crawl_id=crawl_id,
                        url=canonical_url,
                        raw_url=raw_url if raw_url != canonical_url else None,
                        status_code=page.status_code,
                        title=page.title,
                        meta_description=page.meta_description,
                        canonical=page.canonical_url,
                        meta_robots=page.meta_robots,
                        h1=page.primary_h1,
                        h1_list=page.headings.get("h1") or [],
                        word_count=page.word_count,
                        response_time_ms=page.response_time_ms,
                        redirect_hops=page.redirect_hops,
                        is_indexable=page.is_indexable,
                        has_schema=page.has_schema,
                        js_rendered=page.js_rendered,
                        rendered_diff_significant=page.rendered_diff_significant,
                        raw_html_path=html_path,
                    )
                    .on_conflict_do_nothing(index_elements=["crawl_id", "url"])
                )
                result = db.execute(insert_stmt)
                if not result.rowcount:
                    continue

                page_row = db.scalar(
                    select(CrawlPage).where(
                        CrawlPage.crawl_id == crawl_id,
                        CrawlPage.url == canonical_url,
                    )
                )
                if page_row is None:
                    continue

                for link in page.links:
                    db.add(
                        PageLink(
                            crawl_page_id=page_row.id,
                            target_url=link.target_url,
                            is_internal=link.is_internal,
                            anchor_text=link.anchor_text,
                        )
                    )

                db.add(
                    PageTechnicalDetails(
                        crawl_page_id=page_row.id,
                        url_has_uppercase=page.url_has_uppercase,
                        url_has_underscore=page.url_has_underscore,
                        url_length=page.url_length,
                        url_has_query_params=page.url_has_query_params,
                        og_title=page.og_title,
                        og_description=page.og_description,
                        og_image=page.og_image,
                        twitter_card=page.twitter_card,
                        twitter_title=page.twitter_title,
                        html_lang=page.html_lang,
                        favicon_present=bool(page.favicon_present),
                        images_json=[
                            {
                                "src": image.src,
                                "alt": image.alt,
                                "has_width": image.has_width,
                                "has_height": image.has_height,
                                "file_extension": image.file_extension,
                                "width": image.width,
                                "height": image.height,
                                "size_bytes": image.size_bytes,
                            }
                            for image in page.images
                        ],
                        schema_json=[
                            {
                                "raw": block.raw,
                                "parsed": block.parsed,
                                "parse_error": block.parsed is None,
                            }
                            for block in page.schema_blocks
                        ],
                        total_page_weight_bytes=page.total_page_weight_bytes,
                        resource_request_count=page.resource_request_count,
                        render_blocking_scripts_in_head=page.render_blocking_scripts_in_head,
                        stylesheets_in_head=page.stylesheets_in_head,
                        redirect_chain_json=[
                            {"url": hop.url, "status_code": hop.status_code}
                            for hop in page.redirect_chain
                        ],
                    )
                )

                run_counts[crawl_id] = run_counts.get(crawl_id, 0) + 1
                written += 1

            if run_counts:
                runs = db.scalars(select(CrawlRun).where(CrawlRun.id.in_(list(run_counts)))).all()
                for run in runs:
                    run.total_urls += run_counts.get(run.id, 0)

            db.commit()

        return written

    def _save_html_snapshot(self, crawl_run_id: int, url: str, html: str | None) -> str | None:
        if html is None:
            return None

        run_dir = self._snapshot_root / str(crawl_run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        file_path = run_dir / f"{digest}.html"
        file_path.write_text(html, encoding="utf-8")
        return str(file_path)
