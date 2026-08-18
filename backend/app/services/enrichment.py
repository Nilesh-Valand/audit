from __future__ import annotations

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urldefrag, urlparse

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import SessionLocal
from app.models import CrawledPage, CrawlRun, PageVital, SitemapFinding

logger = logging.getLogger(__name__)
PAGESPEED_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
SITEMAP_URL_LIMIT = 5_000


@dataclass(slots=True)
class PageRecord:
    id: int
    url: str
    word_count: int | None
    status_code: int | None
    is_indexable: bool


@dataclass(slots=True)
class CrawlRunContext:
    crawl_run_id: int
    project_id: int
    pages: list[PageRecord]


@dataclass(slots=True)
class PageVitalRecord:
    crawled_page_id: int
    lcp_ms: float | None
    inp_ms: float | None
    cls: float | None
    performance_score: int | None
    strategy: str


@dataclass(slots=True)
class SitemapComparison:
    findings: list[tuple[str, str, str]]
    missing_page_ids: list[int]


class EnrichmentService:
    """Post-crawl enrichment: sitemap always; PageSpeed when ENABLE_PAGESPEED=true."""

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._pagespeed_lock = asyncio.Lock()
        self._next_pagespeed_at = 0.0

    async def enrich_crawl_run(
        self,
        crawl_run_id: int,
        *,
        enable_pagespeed: bool | None = None,
        skip_sitemap: bool = False,
    ) -> None:
        context = await asyncio.to_thread(self._load_run_context, crawl_run_id)
        if context is None or not context.pages:
            return

        run_pagespeed = settings.ENABLE_PAGESPEED if enable_pagespeed is None else enable_pagespeed

        headers = {"User-Agent": settings.CRAWLER_USER_AGENT}
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
            if run_pagespeed:
                try:
                    vitals = await self._collect_pagespeed_vitals(client, context.pages)
                    if vitals:
                        await asyncio.to_thread(self._save_page_vitals, vitals)
                except Exception:
                    logger.exception("PageSpeed enrichment failed for crawl run %s", crawl_run_id)

            if not skip_sitemap:
                try:
                    await self._run_sitemap_check(client, context)
                except Exception:
                    logger.exception("Sitemap enrichment failed for crawl run %s", crawl_run_id)

    async def _collect_pagespeed_vitals(
        self,
        client: httpx.AsyncClient,
        pages: list[PageRecord],
    ) -> list[PageVitalRecord]:
        sample = [
            page
            for page in pages
            if page.status_code and 200 <= page.status_code < 400 and page.is_indexable
        ][: settings.ENRICHMENT_PAGESPEED_SAMPLE_LIMIT]

        semaphore = asyncio.Semaphore(settings.ENRICHMENT_PAGESPEED_BATCH_SIZE)
        records: list[PageVitalRecord] = []

        async def fetch_one(page: PageRecord, strategy: str) -> None:
            async with semaphore:
                metrics = await self._fetch_pagespeed_metrics(client, page.url, strategy)
                if metrics is None:
                    return
                records.append(
                    PageVitalRecord(
                        crawled_page_id=page.id,
                        lcp_ms=metrics.get("lcp_ms"),  # type: ignore[arg-type]
                        inp_ms=metrics.get("inp_ms"),  # type: ignore[arg-type]
                        cls=metrics.get("cls"),  # type: ignore[arg-type]
                        performance_score=metrics.get("performance_score"),  # type: ignore[arg-type]
                        strategy=strategy,
                    )
                )

        await asyncio.gather(
            *(fetch_one(page, strategy) for page in sample for strategy in ("mobile", "desktop"))
        )
        return records

    async def _fetch_pagespeed_metrics(
        self,
        client: httpx.AsyncClient,
        url: str,
        strategy: str,
    ) -> dict[str, float | int | None] | None:
        params: dict[str, str] = {"url": url, "strategy": strategy, "category": "performance"}
        if settings.PAGESPEED_API_KEY:
            params["key"] = settings.PAGESPEED_API_KEY

        backoff = settings.ENRICHMENT_PAGESPEED_REQUEST_DELAY
        for attempt in range(settings.ENRICHMENT_PAGESPEED_MAX_RETRIES):
            await self._wait_for_pagespeed_slot()
            try:
                response = await client.get(PAGESPEED_ENDPOINT, params=params)
                if response.status_code == 429:
                    await asyncio.sleep(backoff * (attempt + 1))
                    continue
                if response.status_code >= 400:
                    return None
                return self._parse_pagespeed_payload(response.json())
            except httpx.HTTPError:
                if attempt == settings.ENRICHMENT_PAGESPEED_MAX_RETRIES - 1:
                    return None
                await asyncio.sleep(backoff * (attempt + 1))
        return None

    async def _wait_for_pagespeed_slot(self) -> None:
        async with self._pagespeed_lock:
            now = time.monotonic()
            wait_time = self._next_pagespeed_at - now
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self._next_pagespeed_at = time.monotonic() + settings.ENRICHMENT_PAGESPEED_REQUEST_DELAY

    def _parse_pagespeed_payload(self, payload: dict[str, Any]) -> dict[str, float | int | None]:
        lighthouse = payload.get("lighthouseResult", {})
        audits = lighthouse.get("audits", {})

        lcp = self._numeric_value(audits.get("largest-contentful-paint"))
        inp = self._numeric_value(audits.get("interaction-to-next-paint"))
        if inp is None:
            inp = self._numeric_value(audits.get("total-blocking-time"))
        cls = self._numeric_value(audits.get("cumulative-layout-shift"))

        performance = lighthouse.get("categories", {}).get("performance", {}).get("score")
        performance_score = None
        if isinstance(performance, (int, float)):
            performance_score = int(round(performance * 100))

        return {
            "lcp_ms": lcp,
            "inp_ms": inp,
            "cls": cls,
            "performance_score": performance_score,
        }

    def _numeric_value(self, audit: dict[str, Any] | None) -> float | None:
        if not isinstance(audit, dict):
            return None
        value = audit.get("numericValue")
        if isinstance(value, (int, float)):
            return float(value)
        return None

    def _save_page_vitals(self, records: list[PageVitalRecord]) -> None:
        page_ids = list({record.crawled_page_id for record in records})
        with self._session_factory() as db:
            db.execute(delete(PageVital).where(PageVital.crawl_page_id.in_(page_ids)))
            for record in records:
                db.add(
                    PageVital(
                        crawl_page_id=record.crawled_page_id,
                        lcp_ms=record.lcp_ms,
                        inp_ms=record.inp_ms,
                        cls=record.cls,
                        performance_score=record.performance_score,
                        strategy=record.strategy,
                    )
                )
            db.commit()

    async def _run_sitemap_check(
        self,
        client: httpx.AsyncClient,
        context: CrawlRunContext,
    ) -> None:
        base_url = self._site_root_from_url(context.pages[0].url)
        root_sitemap = f"{base_url}/sitemap.xml"
        sitemap_urls, structure_findings = await self._fetch_sitemap_urls(client, root_sitemap)

        comparison_findings: list[tuple[str, str, str]] = []
        if sitemap_urls:
            comparison = self._compare_sitemap_to_crawl(context.pages, sitemap_urls)
            comparison_findings = comparison.findings

        await asyncio.to_thread(
            self._save_sitemap_comparison,
            context.crawl_run_id,
            SitemapComparison(
                findings=[*structure_findings, *comparison_findings],
                missing_page_ids=[],
            ),
        )

    async def _fetch_sitemap_urls(
        self,
        client: httpx.AsyncClient,
        sitemap_url: str,
        seen: set[str] | None = None,
        collected: set[str] | None = None,
        findings: list[tuple[str, str, str]] | None = None,
        *,
        is_child: bool = False,
    ) -> tuple[set[str], list[tuple[str, str, str]]]:
        seen = seen or set()
        collected = collected if collected is not None else set()
        findings = findings if findings is not None else []
        if len(collected) >= SITEMAP_URL_LIMIT:
            return collected, findings

        normalized_sitemap_url = self._normalize_url(sitemap_url)
        if normalized_sitemap_url in seen:
            return collected, findings
        seen.add(normalized_sitemap_url)

        try:
            response = await client.get(normalized_sitemap_url)
        except httpx.HTTPError:
            findings.append(
                (
                    normalized_sitemap_url,
                    "sitemap_child_broken" if is_child else "sitemap_not_found",
                    (
                        "Child sitemap could not be fetched."
                        if is_child
                        else "Sitemap could not be fetched."
                    ),
                )
            )
            return collected, findings

        if response.status_code >= 400:
            findings.append(
                (
                    normalized_sitemap_url,
                    "sitemap_child_broken" if is_child else "sitemap_not_found",
                    (
                        f"Child sitemap returned HTTP {response.status_code}."
                        if is_child
                        else f"Sitemap returned HTTP {response.status_code}."
                    ),
                )
            )
            return collected, findings

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError:
            findings.append(
                (
                    normalized_sitemap_url,
                    "sitemap_child_broken" if is_child else "sitemap_malformed",
                    (
                        "Child sitemap contains invalid XML."
                        if is_child
                        else "Sitemap contains invalid XML."
                    ),
                )
            )
            return collected, findings

        tag = self._strip_xml_namespace(root.tag)
        if tag == "sitemapindex":
            for sitemap_node in root.findall(".//{*}sitemap/{*}loc"):
                if len(collected) >= SITEMAP_URL_LIMIT:
                    break
                if sitemap_node.text:
                    await self._fetch_sitemap_urls(
                        client,
                        sitemap_node.text.strip(),
                        seen,
                        collected,
                        findings,
                        is_child=True,
                    )
            return collected, findings

        if tag != "urlset":
            findings.append(
                (
                    normalized_sitemap_url,
                    "sitemap_child_broken" if is_child else "sitemap_malformed",
                    (
                        "Child sitemap root element is not urlset/sitemapindex."
                        if is_child
                        else "Sitemap root element is not urlset/sitemapindex."
                    ),
                )
            )
            return collected, findings

        for node in root.findall(".//{*}url/{*}loc"):
            if len(collected) >= SITEMAP_URL_LIMIT:
                break
            if node.text:
                collected.add(self._normalize_url(node.text.strip()))
        return collected, findings

    def _compare_sitemap_to_crawl(
        self,
        pages: list[PageRecord],
        sitemap_urls: set[str],
    ) -> SitemapComparison:
        crawled_pages = {
            self._normalize_url(page.url): page
            for page in pages
            if page.url
        }

        findings: list[tuple[str, str, str]] = []
        missing_page_ids: list[int] = []
        not_crawled = sorted(sitemap_urls - set(crawled_pages))

        if not_crawled:
            sample = ", ".join(not_crawled[:5])
            extra = len(not_crawled) - min(5, len(not_crawled))
            sample_note = f" Examples: {sample}" + (f" (+{extra} more)." if extra > 0 else ".")
            findings.append(
                (
                    not_crawled[0],
                    "in_sitemap_not_crawled",
                    (
                        f"{len(not_crawled)} sitemap URL(s) were not crawled in this run "
                        f"(crawled {len(crawled_pages)} page(s); sitemap compared {len(sitemap_urls)} URL(s))."
                        f"{sample_note} Increase max pages if you need broader sitemap coverage."
                    ),
                )
            )

        for crawled_url, page in crawled_pages.items():
            if crawled_url in sitemap_urls:
                continue
            findings.append(
                (
                    crawled_url,
                    "crawled_not_in_sitemap",
                    "URL was crawled successfully but does not appear in the discovered sitemap.",
                )
            )
            missing_page_ids.append(page.id)

        return SitemapComparison(findings=findings, missing_page_ids=missing_page_ids)

    def _save_sitemap_comparison(self, crawl_run_id: int, comparison: SitemapComparison) -> None:
        with self._session_factory() as db:
            db.execute(delete(SitemapFinding).where(SitemapFinding.crawl_id == crawl_run_id))
            for url, finding_type, message in comparison.findings:
                db.add(
                    SitemapFinding(
                        crawl_id=crawl_run_id,
                        url=url,
                        finding_type=finding_type,
                        message=message,
                    )
                )
            db.commit()

    def _load_run_context(self, crawl_run_id: int) -> CrawlRunContext | None:
        with self._session_factory() as db:
            crawl_run = db.get(CrawlRun, crawl_run_id)
            if crawl_run is None:
                return None
            pages = db.scalars(
                select(CrawledPage).where(CrawledPage.crawl_id == crawl_run_id)
            ).all()
            return CrawlRunContext(
                crawl_run_id=crawl_run.id,
                project_id=crawl_run.project_id,
                pages=[
                    PageRecord(
                        id=page.id,
                        url=page.url,
                        word_count=page.word_count,
                        status_code=page.status_code,
                        is_indexable=page.is_indexable,
                    )
                    for page in pages
                ],
            )

    def _site_root_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _normalize_url(self, url: str) -> str:
        from app.crawler.normalize import normalize_url

        return normalize_url(url)

    def _strip_xml_namespace(self, tag: str) -> str:
        return tag.split("}", 1)[-1]
