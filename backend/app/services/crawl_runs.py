from __future__ import annotations

import asyncio
import logging

from app.checks.orchestrator import run_audit
from app.crawler.storage import CrawlStorage

logger = logging.getLogger(__name__)

_ACTIVE_TASKS: dict[int, asyncio.Task[None]] = {}
_ACTIVE_PROGRESS: dict[int, int] = {}
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


def is_active(crawl_run_id: int) -> bool:
    task = _ACTIVE_TASKS.get(crawl_run_id)
    return task is not None and not task.done()


def get_progress(crawl_run_id: int) -> int | None:
    return _ACTIVE_PROGRESS.get(crawl_run_id)


def start_crawl_run(
    *,
    crawl_run_id: int,
    start_url: str,
    max_pages: int,
    max_depth: int = 10,
    enable_pagespeed: bool | None = None,
) -> None:
    storage = CrawlStorage()

    async def runner() -> None:
        try:
            await run_audit(
                crawl_run_id,
                start_url=start_url,
                max_pages=max_pages,
                max_depth=max_depth,
                enable_pagespeed=enable_pagespeed,
                storage=storage,
                progress_callback=lambda: _ACTIVE_PROGRESS.__setitem__(
                    crawl_run_id,
                    _ACTIVE_PROGRESS.get(crawl_run_id, 0) + 1,
                ),
            )
        except asyncio.CancelledError:
            storage.set_run_failed(
                crawl_run_id,
                error_message=(
                    "Crawl was cancelled (server reload/shutdown). "
                    "Start uvicorn with --reload-dir app."
                ),
            )
            logger.warning(
                "Crawl run %s was cancelled (server reload/shutdown). Start uvicorn with "
                "`--reload-dir app` so crawl data under backend/data/ does not restart the process.",
                crawl_run_id,
            )
            raise
        except Exception as exc:
            logger.exception("Crawl run %s failed: %s", crawl_run_id, exc)
            storage.set_run_failed(crawl_run_id, error_message=str(exc))
            raise

    task = asyncio.create_task(runner(), name=f"crawl-run-{crawl_run_id}")
    _ACTIVE_TASKS[crawl_run_id] = task
    _ACTIVE_PROGRESS[crawl_run_id] = 0
    task.add_done_callback(
        lambda _: (_ACTIVE_TASKS.pop(crawl_run_id, None), _ACTIVE_PROGRESS.pop(crawl_run_id, None))
    )


def cancel_crawl_run(crawl_run_id: int) -> bool:
    task = _ACTIVE_TASKS.get(crawl_run_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True
