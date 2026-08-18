from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urldefrag, urlparse

import httpx
import yaml
from bs4 import BeautifulSoup
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.checks import Scope, bind_registry, scope_for, severity_default_for
from app.config import settings
from app.rules.schema_validation import schema_blocks_have_type, validate_schema_blocks
from app.crawler.normalize import normalize_url
from app.db.database import SessionLocal
from app.models import (
    CrawlPage,
    CrawledPage,
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

SEVERITY_WEIGHTS = {
    "critical": 10,
    "high": 5,
    "medium": 2,
    "low": 1,
}

EXCESSIVE_URL_LENGTH = 115
LARGE_PAGE_WEIGHT_BYTES = 3 * 1024 * 1024
EXCESSIVE_RESOURCE_REQUESTS = 100
MAX_BLOCKING_STYLESHEETS = 2
OVERSIZED_IMAGE_BYTES = 200 * 1024
SLOW_TTFB_MS = 800
OUTDATED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}
KEYWORD_CANNIBALIZATION_THRESHOLD = 0.8
LONG_FORM_WORD_COUNT = 800
ANSWER_FIRST_MIN_WORDS = 20
_PAGINATION_QUERY_KEYS = {"page", "p", "paged", "offset", "start"}
_PAGINATION_PATH_RE = re.compile(r"/page/\d+/?$", re.IGNORECASE)

TRACKING_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "gclid",
    "fbclid",
    "msclkid",
    "sid",
    "sessionid",
    "session_id",
    "phpsessid",
    "_ga",
    "mc_cid",
    "mc_eid",
}


@dataclass(slots=True)
class RuleDefinition:
    id: str
    category: str
    description: str
    severity: str
    condition: str


@dataclass(slots=True)
class IssueRecord:
    crawl_run_id: int
    crawled_page_id: int | None
    target_url: str | None
    rule_id: str
    category: str
    severity: str
    message: str


@dataclass(slots=True)
class PageContext:
    page: CrawledPage
    normalized_url: str
    inbound_internal_links: int
    h1_count: int
    h2_count: int
    h3_count: int
    text_hash: str | None
    has_mixed_content: bool
    vitals: dict[str, PageVital]
    technical: PageTechnicalDetails | None = None


@dataclass(slots=True)
class CanonicalTargetProbe:
    """Cached lightweight HEAD/GET result for a canonical target URL."""

    url: str
    malformed: bool = False
    status_code: int | None = None
    is_redirect: bool = False
    error: str | None = None


class RuleEngine:
    def __init__(self, rules_path: str | Path | None = None) -> None:
        self.rules_path = Path(rules_path or Path(__file__).with_name("rules.yaml"))
        self.rules = self._load_rules()
        # Registry is the single source of truth for check scope + run_fn binding.
        self._registry = bind_registry(self)
        self._checks = {
            name: entry.run_fn for name, entry in self._registry.items() if entry.run_fn is not None
        }
        self._current_crawl_run: CrawlRun | None = None
        self._canonical_probe_cache: dict[str, CanonicalTargetProbe] = {}

    def run(self, crawl_run_id: int) -> dict[str, int]:
        with SessionLocal() as db:
            crawl_run = db.get(CrawlRun, crawl_run_id)
            if crawl_run is None:
                raise ValueError(f"Crawl run {crawl_run_id} not found.")
            if crawl_run.status not in {"completed", "enriching", "running"}:
                raise ValueError("Rule engine can only run after the crawl has finished fetching pages.")

            self._purge_duplicate_pages(db, crawl_run_id)
            page_contexts = self._load_page_contexts(db, crawl_run_id)

            # Scoped runners own issue persistence — only recompute scores here.
            db.execute(delete(CrawlRunScore).where(CrawlRunScore.crawl_id == crawl_run_id))

            self._current_crawl_run = crawl_run
            self._canonical_probe_cache.clear()
            issues: list[IssueRecord] = []
            try:
                for rule in self.rules:
                    check_scope = scope_for(rule.id) or scope_for(rule.condition)
                    # SITE / PAGE / CROSS_PAGE / HOMEPAGE are owned by check runners.
                    if check_scope in {
                        Scope.SITE,
                        Scope.PAGE,
                        Scope.CROSS_PAGE,
                        Scope.HOMEPAGE,
                    }:
                        continue
                    check = self._checks.get(rule.condition)
                    if check is None:
                        continue
                    issues.extend(check(rule, crawl_run_id, page_contexts, []))
            finally:
                self._current_crawl_run = None
                self._canonical_probe_cache.clear()

            # Include failing site_issues + page_issues in category scores.
            rules_by_id = {rule.id: rule for rule in self.rules}
            site_fails = db.scalars(
                select(SiteIssue).where(
                    SiteIssue.crawl_id == crawl_run_id,
                    SiteIssue.status == "fail",
                )
            ).all()
            for row in site_fails:
                rule = rules_by_id.get(row.check_name)
                issues.append(
                    IssueRecord(
                        crawl_run_id=crawl_run_id,
                        crawled_page_id=None,
                        target_url=None,
                        rule_id=row.check_name,
                        category=rule.category if rule else "technical",
                        severity=row.severity,
                        message=row.details,
                    )
                )

            page_fails = db.scalars(
                select(PageIssue).where(
                    PageIssue.crawl_id == crawl_run_id,
                    PageIssue.status == "fail",
                )
            ).all()
            page_id_by_url = {ctx.normalized_url: ctx.page.id for ctx in page_contexts}
            for row in page_fails:
                rule = rules_by_id.get(row.check_name)
                issues.append(
                    IssueRecord(
                        crawl_run_id=crawl_run_id,
                        crawled_page_id=page_id_by_url.get(normalize_url(row.url)),
                        target_url=row.url,
                        rule_id=row.check_name,
                        category=rule.category if rule else "technical",
                        severity=row.severity,
                        message=row.details,
                    )
                )

            scores = self._compute_scores(crawl_run_id, issues, len(page_contexts))
            for category, score in scores.items():
                db.add(
                    CrawlRunScore(
                        crawl_id=crawl_run_id,
                        category=category,
                        score=score,
                    )
                )

            db.commit()
            return {"issues_created": len(issues), "scores_created": len(scores)}

    def _load_rules(self) -> list[RuleDefinition]:
        payload = yaml.safe_load(self.rules_path.read_text(encoding="utf-8")) or []
        rules: list[RuleDefinition] = []
        for item in payload:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            rule_id = str(item["id"])
            # Registry severity_default wins when the check is registered.
            severity = severity_default_for(rule_id) or str(item.get("severity") or "medium")
            rules.append(
                RuleDefinition(
                    id=rule_id,
                    category=str(item.get("category") or "technical"),
                    description=str(item.get("description") or ""),
                    severity=severity,
                    condition=str(item.get("condition") or rule_id),
                )
            )
        return rules

    def _purge_duplicate_pages(self, db: Session, crawl_run_id: int) -> int:
        """Remove extra crawled_page rows that share the same canonical URL."""
        pages = db.scalars(
            select(CrawledPage)
            .where(CrawledPage.crawl_id == crawl_run_id)
            .order_by(CrawledPage.id.asc())
        ).all()

        keep_count = 0
        delete_ids: list[int] = []
        deleted_urls: list[str] = []
        seen: set[str] = set()
        for page in pages:
            key = self._normalize_url(page.url)
            if page.url != key:
                page.url = key
            if key in seen:
                delete_ids.append(page.id)
                deleted_urls.append(page.url)
                continue
            seen.add(key)
            keep_count += 1

        if delete_ids:
            db.execute(delete(PageLink).where(PageLink.crawl_page_id.in_(delete_ids)))
            db.execute(delete(PageVital).where(PageVital.crawl_page_id.in_(delete_ids)))
            db.execute(
                delete(PageTechnicalDetails).where(
                    PageTechnicalDetails.crawl_page_id.in_(delete_ids)
                )
            )
            if deleted_urls:
                db.execute(
                    delete(PageIssue).where(
                        PageIssue.crawl_id == crawl_run_id,
                        PageIssue.url.in_(deleted_urls),
                    )
                )
            db.execute(delete(CrawledPage).where(CrawledPage.id.in_(delete_ids)))

        crawl_run = db.get(CrawlRun, crawl_run_id)
        if crawl_run is not None:
            crawl_run.total_urls = keep_count
        db.flush()
        return len(delete_ids)

    def _load_page_contexts(self, db: Session, crawl_run_id: int) -> list[PageContext]:
        pages = db.scalars(
            select(CrawledPage)
            .where(CrawledPage.crawl_id == crawl_run_id)
            .options(
                joinedload(CrawledPage.page_vitals),
                joinedload(CrawledPage.technical_details),
            )
            .order_by(CrawledPage.id.asc())
        ).unique().all()

        # Defense in depth: still collapse by canonical URL if any duplicates remain.
        deduped_pages: list[CrawledPage] = []
        seen_urls: set[str] = set()
        for page in pages:
            key = self._normalize_url(page.url)
            if key in seen_urls:
                continue
            seen_urls.add(key)
            deduped_pages.append(page)

        normalized_to_page = {self._normalize_url(page.url): page for page in deduped_pages}
        inbound_links = defaultdict(int)
        links = db.scalars(
            select(PageLink).join(CrawledPage).where(CrawledPage.crawl_id == crawl_run_id)
        ).all()
        for link in links:
            if not link.is_internal:
                continue
            target = self._normalize_url(link.target_url)
            if target in normalized_to_page:
                inbound_links[target] += 1

        contexts: list[PageContext] = []
        for page in deduped_pages:
            normalized_url = self._normalize_url(page.url)
            h1_count, h2_count, h3_count, text_hash, mixed_content = self._snapshot_signals(
                page.raw_html_path, page.url
            )
            if h1_count == 0 and page.h1_list:
                h1_count = len(page.h1_list)
            vitals = {vital.strategy: vital for vital in page.page_vitals}
            contexts.append(
                PageContext(
                    page=page,
                    normalized_url=normalized_url,
                    inbound_internal_links=inbound_links.get(normalized_url, 0),
                    h1_count=h1_count,
                    h2_count=h2_count,
                    h3_count=h3_count,
                    text_hash=text_hash,
                    has_mixed_content=mixed_content,
                    vitals=vitals,
                    technical=page.technical_details,
                )
            )
        return contexts

    def _snapshot_signals(
        self, raw_html_path: str | None, page_url: str
    ) -> tuple[int, int, int, str | None, bool]:
        if not raw_html_path:
            return 0, 0, 0, None, False
        path = Path(raw_html_path)
        if not path.exists():
            return 0, 0, 0, None, False

        html = path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "lxml")
        h1_count = len(soup.find_all("h1"))
        h2_count = len(soup.find_all("h2"))
        h3_count = len(soup.find_all("h3"))
        text_hash = self._content_hash(soup)
        mixed_content = self._has_mixed_content(soup, page_url)
        return h1_count, h2_count, h3_count, text_hash, mixed_content

    def _compute_scores(
        self,
        crawl_run_id: int,
        issues: list[IssueRecord],
        total_pages: int,
    ) -> dict[str, float]:
        checked = max(total_pages, 1)
        weights_by_category = defaultdict(int)
        total_weight = 0
        for issue in issues:
            weight = SEVERITY_WEIGHTS.get(issue.severity, 1)
            weights_by_category[issue.category] += weight
            total_weight += weight

        categories = {rule.category for rule in self.rules}
        scores = {
            category: max(0.0, round(100 - (weights_by_category[category] / checked), 2))
            for category in categories
        }
        scores["overall"] = max(0.0, round(100 - (total_weight / checked), 2))
        return scores

    def _missing_title(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        return [
            self._page_issue(rule, crawl_run_id, page, "Page is missing a title tag.")
            for page in pages
            if not (page.page.title or "").strip()
        ]

    def _duplicate_title(self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]) -> list[IssueRecord]:
        return self._duplicate_text_issues(
            rule,
            crawl_run_id,
            pages,
            lambda page: page.page.title,
            "Title is duplicated across {count} pages.",
        )

    def _missing_meta_description(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        return [
            self._page_issue(rule, crawl_run_id, page, "Page is missing a meta description.")
            for page in pages
            if not (page.page.meta_description or "").strip()
        ]

    def _duplicate_meta_description(self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]) -> list[IssueRecord]:
        return self._duplicate_text_issues(
            rule,
            crawl_run_id,
            pages,
            lambda page: page.page.meta_description,
            "Meta description is duplicated across {count} pages.",
        )

    def _broken_link(self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]) -> list[IssueRecord]:
        return [
            self._page_issue(
                rule,
                crawl_run_id,
                page,
                f"Page returned status {page.page.status_code}.",
            )
            for page in pages
            if page.page.status_code is not None and page.page.status_code >= 400
        ]

    def _redirect_chain(self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]) -> list[IssueRecord]:
        return [
            self._page_issue(
                rule,
                crawl_run_id,
                page,
                f"Page required {page.page.redirect_hops} redirects before resolving.",
            )
            for page in pages
            if page.page.redirect_hops >= 3
        ]

    def _canonical_noindex_conflict(self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]) -> list[IssueRecord]:
        return [
            self._page_issue(
                rule,
                crawl_run_id,
                page,
                "Page sets a canonical URL while also including noindex.",
            )
            for page in pages
            if page.page.canonical_url and "noindex" in (page.page.meta_robots or "").lower()
        ]

    def _missing_canonical(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        return [
            self._page_issue(rule, crawl_run_id, page, "Page is missing a <link rel=\"canonical\"> tag.")
            for page in pages
            if self._is_likely_html_document(page) and not (page.page.canonical_url or "").strip()
        ]

    def _self_canonical_mismatch(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in pages:
            raw_canonical = (page.page.canonical_url or "").strip()
            if not raw_canonical or not self._is_likely_html_document(page):
                continue
            if self._is_malformed_url(raw_canonical):
                continue
            page_norm = page.normalized_url
            canon_norm = self._normalize_url(raw_canonical)
            if not canon_norm or page_norm == canon_norm:
                continue
            if self._is_pagination_canonical(page_norm, canon_norm):
                continue
            issues.append(
                self._page_issue(
                    rule,
                    crawl_run_id,
                    page,
                    f"Canonical points to {canon_norm} instead of this page's URL ({page_norm}).",
                )
            )
        return issues

    def _broken_canonical_url(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        pages_by_url = {page.normalized_url: page for page in pages}
        issues: list[IssueRecord] = []
        for page in pages:
            raw_canonical = (page.page.canonical_url or "").strip()
            if not raw_canonical or not self._is_likely_html_document(page):
                continue
            if self._is_malformed_url(raw_canonical):
                issues.append(
                    self._page_issue(
                        rule,
                        crawl_run_id,
                        page,
                        f"Canonical URL is malformed: {raw_canonical}",
                    )
                )
                continue

            canon_norm = self._normalize_url(raw_canonical)
            target = pages_by_url.get(canon_norm)
            if target is not None:
                status = target.page.status_code
                if status is not None and status >= 400:
                    issues.append(
                        self._page_issue(
                            rule,
                            crawl_run_id,
                            page,
                            f"Canonical target {canon_norm} returned status {status} in this crawl.",
                        )
                    )
                continue

            probe = self._probe_canonical_target(raw_canonical)
            if probe.malformed:
                issues.append(
                    self._page_issue(
                        rule,
                        crawl_run_id,
                        page,
                        f"Canonical URL is malformed: {raw_canonical}",
                    )
                )
                continue
            if probe.status_code is not None and probe.status_code >= 400 and not probe.is_redirect:
                issues.append(
                    self._page_issue(
                        rule,
                        crawl_run_id,
                        page,
                        f"Canonical target {canon_norm} returned status {probe.status_code}.",
                    )
                )
        return issues

    def _canonical_points_to_redirect(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        pages_by_url = {page.normalized_url: page for page in pages}
        issues: list[IssueRecord] = []
        for page in pages:
            raw_canonical = (page.page.canonical_url or "").strip()
            if not raw_canonical or not self._is_likely_html_document(page):
                continue
            if self._is_malformed_url(raw_canonical):
                continue

            canon_norm = self._normalize_url(raw_canonical)
            target = pages_by_url.get(canon_norm)
            if target is not None:
                if target.page.redirect_hops >= 1:
                    issues.append(
                        self._page_issue(
                            rule,
                            crawl_run_id,
                            page,
                            f"Canonical target {canon_norm} required {target.page.redirect_hops} redirect hop(s) during crawl.",
                        )
                    )
                continue

            probe = self._probe_canonical_target(raw_canonical)
            if probe.is_redirect and probe.status_code is not None:
                issues.append(
                    self._page_issue(
                        rule,
                        crawl_run_id,
                        page,
                        f"Canonical target {canon_norm} returned HTTP {probe.status_code} (redirect).",
                    )
                )
        return issues

    def _canonical_points_to_noindex(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        pages_by_url = {page.normalized_url: page for page in pages}
        issues: list[IssueRecord] = []
        for page in pages:
            raw_canonical = (page.page.canonical_url or "").strip()
            if not raw_canonical or not self._is_likely_html_document(page):
                continue
            if self._is_malformed_url(raw_canonical):
                continue

            canon_norm = self._normalize_url(raw_canonical)
            target = pages_by_url.get(canon_norm)
            if target is None:
                continue
            # Self-canonical + noindex is covered by canonical_noindex_conflict.
            if target.normalized_url == page.normalized_url:
                continue
            if "noindex" not in (target.page.meta_robots or "").lower():
                continue
            issues.append(
                self._page_issue(
                    rule,
                    crawl_run_id,
                    page,
                    f"Canonical target {canon_norm} includes meta robots noindex.",
                )
            )
        return issues

    def _is_likely_html_document(self, page: PageContext) -> bool:
        status = page.page.status_code
        if status is not None and status >= 400:
            return False
        return True

    def _is_malformed_url(self, url: str) -> bool:
        cleaned = (url or "").strip()
        if not cleaned:
            return True
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"}:
            return True
        if not parsed.netloc:
            return True
        return False

    def _is_pagination_canonical(self, page_url: str, canonical_url: str) -> bool:
        """True when page N+ intentionally canonicalizes to page 1 / hub."""
        page_parsed = urlparse(page_url)
        canon_parsed = urlparse(canonical_url)
        page_qs = parse_qs(page_parsed.query, keep_blank_values=False)
        canon_qs = parse_qs(canon_parsed.query, keep_blank_values=False)

        for key in _PAGINATION_QUERY_KEYS:
            if key not in page_qs:
                continue
            try:
                page_n = int(str(page_qs[key][0]))
            except (TypeError, ValueError):
                continue
            if page_n <= 1:
                continue
            if key not in canon_qs:
                return True
            try:
                canon_n = int(str(canon_qs[key][0]))
            except (TypeError, ValueError):
                continue
            if canon_n == 1:
                return True

        if _PAGINATION_PATH_RE.search(page_parsed.path or ""):
            canon_path = canon_parsed.path or ""
            if not _PAGINATION_PATH_RE.search(canon_path):
                return True
            if re.search(r"/page/1/?$", canon_path, re.IGNORECASE):
                return True
        return False

    def _probe_canonical_target(self, url: str) -> CanonicalTargetProbe:
        cache_key = self._normalize_url(url) or url.strip()
        cached = self._canonical_probe_cache.get(cache_key)
        if cached is not None:
            return cached

        if self._is_malformed_url(url):
            probe = CanonicalTargetProbe(url=url, malformed=True)
            self._canonical_probe_cache[cache_key] = probe
            return probe

        headers = {"User-Agent": settings.CRAWLER_USER_AGENT}
        timeout = httpx.Timeout(15.0, connect=8.0)
        try:
            with httpx.Client(
                headers=headers,
                timeout=timeout,
                follow_redirects=False,
            ) as client:
                response = self._head_or_get(client, url)
                status = response.status_code
                probe = CanonicalTargetProbe(
                    url=url,
                    status_code=status,
                    is_redirect=300 <= status < 400,
                )
        except Exception as exc:
            logger.debug("Canonical target probe failed for %s: %s", url, exc)
            probe = CanonicalTargetProbe(url=url, error=str(exc))

        self._canonical_probe_cache[cache_key] = probe
        return probe

    def _head_or_get(self, client: httpx.Client, url: str) -> httpx.Response:
        response = client.head(url)
        if response.status_code in {405, 501}:
            return client.get(url)
        return response

    def _orphan_page(self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]) -> list[IssueRecord]:
        return [
            self._page_issue(
                rule,
                crawl_run_id,
                page,
                "Page has no inbound internal links from other crawled pages.",
            )
            for page in pages
            if page.inbound_internal_links == 0
        ]

    def _missing_h1(self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]) -> list[IssueRecord]:
        return [
            self._page_issue(rule, crawl_run_id, page, "Page is missing an H1 heading.")
            for page in pages
            if page.h1_count == 0
        ]

    def _multiple_h1(self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]) -> list[IssueRecord]:
        return [
            self._page_issue(
                rule,
                crawl_run_id,
                page,
                f"Page contains {page.h1_count} H1 headings.",
            )
            for page in pages
            if page.h1_count > 1
        ]

    def _lcp_fail(self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]) -> list[IssueRecord]:
        return self._vital_issues(rule, crawl_run_id, pages, "lcp_ms", 2500, "LCP is {value:.0f}ms.")

    def _inp_fail(self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]) -> list[IssueRecord]:
        return self._vital_issues(rule, crawl_run_id, pages, "inp_ms", 200, "INP/TBT is {value:.0f}ms.")

    def _cls_fail(self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]) -> list[IssueRecord]:
        return self._vital_issues(rule, crawl_run_id, pages, "cls", 0.1, "CLS is {value:.2f}.")

    def _large_page_weight(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in pages:
            weight = page.technical.total_page_weight_bytes if page.technical else None
            if weight is None or weight <= LARGE_PAGE_WEIGHT_BYTES:
                continue
            mb = weight / (1024 * 1024)
            issues.append(
                self._page_issue(
                    rule,
                    crawl_run_id,
                    page,
                    f"Measured page weight is {mb:.2f}MB (threshold {LARGE_PAGE_WEIGHT_BYTES / (1024 * 1024):.0f}MB).",
                )
            )
        return issues

    def _excessive_requests(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in pages:
            count = page.technical.resource_request_count if page.technical else None
            if count is None or count <= EXCESSIVE_RESOURCE_REQUESTS:
                continue
            issues.append(
                self._page_issue(
                    rule,
                    crawl_run_id,
                    page,
                    f"Page references about {count} resources (threshold {EXCESSIVE_RESOURCE_REQUESTS}).",
                )
            )
        return issues

    def _render_blocking_resources(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in pages:
            tech = page.technical
            if tech is None:
                continue
            blocking_scripts = tech.render_blocking_scripts_in_head or 0
            stylesheets = tech.stylesheets_in_head or 0
            if blocking_scripts <= 0 and stylesheets <= MAX_BLOCKING_STYLESHEETS:
                continue
            parts: list[str] = []
            if blocking_scripts > 0:
                parts.append(
                    f"{blocking_scripts} render-blocking script(s) in <head> without async/defer"
                )
            if stylesheets > MAX_BLOCKING_STYLESHEETS:
                parts.append(
                    f"{stylesheets} stylesheet(s) in <head> (threshold {MAX_BLOCKING_STYLESHEETS})"
                )
            issues.append(
                self._page_issue(
                    rule,
                    crawl_run_id,
                    page,
                    "; ".join(parts) + ".",
                )
            )
        return issues

    def _oversized_images(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in pages:
            oversized = []
            for image in self._iter_images(page):
                size = image.get("size_bytes")
                if not isinstance(size, int) or size <= OVERSIZED_IMAGE_BYTES:
                    continue
                width = image.get("width")
                height = image.get("height")
                dims = (
                    f" at declared {width}x{height}"
                    if isinstance(width, int) and isinstance(height, int)
                    else ""
                )
                src = str(image.get("src") or "image")
                oversized.append(f"{src} ({size / 1024:.0f}KB{dims})")
            if not oversized:
                continue
            sample = "; ".join(oversized[:3])
            extra = f" (+{len(oversized) - 3} more)" if len(oversized) > 3 else ""
            issues.append(
                self._page_issue(
                    rule,
                    crawl_run_id,
                    page,
                    f"{len(oversized)} image(s) exceed {OVERSIZED_IMAGE_BYTES // 1024}KB"
                    f" (consider resizing/compression): {sample}{extra}.",
                )
            )
        return issues

    def _missing_image_dimensions(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in pages:
            missing = [
                str(image.get("src") or "image")
                for image in self._iter_images(page)
                if not image.get("has_width") or not image.get("has_height")
            ]
            if not missing:
                continue
            sample = ", ".join(missing[:3])
            extra = f" (+{len(missing) - 3} more)" if len(missing) > 3 else ""
            issues.append(
                self._page_issue(
                    rule,
                    crawl_run_id,
                    page,
                    f"{len(missing)} <img> tag(s) missing width and/or height attributes "
                    f"(can cause layout shift): {sample}{extra}.",
                )
            )
        return issues

    def _outdated_image_format(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in pages:
            outdated = [
                f"{image.get('src')} (.{image.get('file_extension')})"
                for image in self._iter_images(page)
                if str(image.get("file_extension") or "").lower() in OUTDATED_IMAGE_EXTENSIONS
            ]
            if not outdated:
                continue
            sample = ", ".join(outdated[:3])
            extra = f" (+{len(outdated) - 3} more)" if len(outdated) > 3 else ""
            issues.append(
                self._page_issue(
                    rule,
                    crawl_run_id,
                    page,
                    f"{len(outdated)} image(s) use jpg/png; consider WebP/AVIF where supported: "
                    f"{sample}{extra}.",
                )
            )
        return issues

    def _slow_ttfb(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in pages:
            response_ms = page.page.response_time_ms
            if response_ms is None or response_ms <= SLOW_TTFB_MS:
                continue
            issues.append(
                self._page_issue(
                    rule,
                    crawl_run_id,
                    page,
                    f"Response time was {response_ms:.0f}ms (threshold {SLOW_TTFB_MS}ms).",
                )
            )
        return issues

    def _iter_images(self, page: PageContext) -> list[dict[str, Any]]:
        tech = page.technical
        if tech is None or not isinstance(tech.images_json, list):
            return []
        return [image for image in tech.images_json if isinstance(image, dict)]

    def _thin_content(self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]) -> list[IssueRecord]:
        return [
            self._page_issue(
                rule,
                crawl_run_id,
                page,
                f"Page has only {page.page.word_count or 0} visible words.",
            )
            for page in pages
            if (page.page.word_count or 0) < 300
        ]

    def _duplicate_content(self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]) -> list[IssueRecord]:
        groups = defaultdict(list)
        for page in pages:
            if page.text_hash:
                groups[page.text_hash].append(page)
        issues: list[IssueRecord] = []
        for group in groups.values():
            unique_pages = self._unique_pages_by_url(group)
            if len(unique_pages) < 2:
                continue
            for page in unique_pages:
                issues.append(
                    self._page_issue(
                        rule,
                        crawl_run_id,
                        page,
                        f"Page content hash matches {len(unique_pages)} pages in this crawl.",
                    )
                )
        return issues

    def _missing_schema(self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in pages:
            if page.page.has_schema:
                continue
            haystack = " ".join(
                filter(None, [page.page.url, page.page.title, page.page.h1])
            ).lower()
            likely_schema_page = any(
                token in haystack
                for token in ("product", "service", "blog", "article", "faq", "recipe", "event", "job", "news")
            )
            if likely_schema_page:
                issues.append(
                    self._page_issue(
                        rule,
                        crawl_run_id,
                        page,
                        "Page looks like a rich-result candidate but no JSON-LD schema was found.",
                    )
                )
        return issues

    def _mixed_content(self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]) -> list[IssueRecord]:
        return [
            self._page_issue(
                rule,
                crawl_run_id,
                page,
                "HTTPS page loads one or more HTTP resources.",
            )
            for page in pages
            if page.page.url.startswith("https://") and page.has_mixed_content
        ]

    def _sitemap_orphan(self, rule: RuleDefinition, crawl_run_id: int, _: list[PageContext], findings: list[SitemapFinding]) -> list[IssueRecord]:
        return [
            IssueRecord(
                crawl_run_id=crawl_run_id,
                crawled_page_id=None,
                target_url=finding.url,
                rule_id=rule.id,
                category=rule.category,
                severity=rule.severity,
                message=finding.message
                or "Sitemap URLs were not covered by this crawl. Increase max pages for broader coverage.",
            )
            for finding in findings
            if finding.finding_type == "in_sitemap_not_crawled"
        ]

    def _crawled_not_in_sitemap(self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], findings: list[SitemapFinding]) -> list[IssueRecord]:
        by_url = {page.normalized_url: page for page in pages}
        issues: list[IssueRecord] = []
        for finding in findings:
            if finding.finding_type != "crawled_not_in_sitemap":
                continue
            page = by_url.get(self._normalize_url(finding.url))
            target = page.page.url if page is not None else finding.url
            issues.append(
                IssueRecord(
                    crawl_run_id=crawl_run_id,
                    crawled_page_id=None,
                    target_url=target,
                    rule_id=rule.id,
                    category=rule.category,
                    severity=rule.severity,
                    message="Crawled URL does not appear in the sitemap.",
                )
            )
        return issues

    def _uppercase_url(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in pages:
            tech = page.technical
            has_upper = tech.url_has_uppercase if tech is not None else self._url_has_uppercase(page.page.url)
            if has_upper:
                issues.append(
                    self._page_issue(
                        rule,
                        crawl_run_id,
                        page,
                        "URL contains uppercase characters, which can cause duplicate-content and crawl inconsistencies.",
                    )
                )
        return issues

    def _underscore_in_url(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in pages:
            tech = page.technical
            has_underscore = (
                tech.url_has_underscore if tech is not None else ("_" in urlparse(page.page.url).path)
            )
            if has_underscore:
                issues.append(
                    self._page_issue(
                        rule,
                        crawl_run_id,
                        page,
                        "URL path uses underscores; hyphens are preferred for readability and SEO.",
                    )
                )
        return issues

    def _excessive_url_length(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in pages:
            tech = page.technical
            length = tech.url_length if tech is not None else len(page.page.url)
            if length > EXCESSIVE_URL_LENGTH:
                issues.append(
                    self._page_issue(
                        rule,
                        crawl_run_id,
                        page,
                        f"URL is {length} characters long (threshold {EXCESSIVE_URL_LENGTH}).",
                    )
                )
        return issues

    def _unnecessary_url_parameters(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in pages:
            if not page.page.is_indexable:
                continue
            if page.page.status_code is not None and page.page.status_code >= 400:
                continue
            params = self._tracking_params_present(page.page.url)
            if not params:
                continue
            issues.append(
                self._page_issue(
                    rule,
                    crawl_run_id,
                    page,
                    "Indexable page URL includes tracking/session parameters: "
                    + ", ".join(sorted(params))
                    + ".",
                )
            )
        return issues

    def _redirect_loop(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in pages:
            chain_urls = self._redirect_chain_urls(page)
            if len(chain_urls) < 2:
                continue
            seen: set[str] = set()
            looped = False
            for url in chain_urls:
                normalized = self._normalize_url(url)
                if normalized in seen:
                    looped = True
                    break
                seen.add(normalized)
            if looped:
                issues.append(
                    IssueRecord(
                        crawl_run_id=crawl_run_id,
                        crawled_page_id=None,
                        target_url=page.page.url,
                        rule_id=rule.id,
                        category=rule.category,
                        severity=rule.severity,
                        message="Redirect chain contains a loop (a URL redirects back to a previously seen URL).",
                    )
                )
        return issues

    def _temp_redirect_should_be_permanent(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        pair_pages: dict[tuple[str, str], list[PageContext]] = defaultdict(list)
        page_pairs: dict[int, set[tuple[str, str]]] = defaultdict(set)

        for page in pages:
            for source, destination, status in self._redirect_hop_pairs(page):
                if status != 302:
                    continue
                pair = (self._normalize_url(source), self._normalize_url(destination))
                if pair[0] == pair[1]:
                    continue
                pair_pages[pair].append(page)
                page_pairs[page.page.id].add(pair)

        consistent_pairs = {pair for pair, group in pair_pages.items() if len({p.page.id for p in group}) >= 2}
        if not consistent_pairs:
            return []

        issues: list[IssueRecord] = []
        for page in pages:
            matching = page_pairs[page.page.id] & consistent_pairs
            if not matching:
                continue
            examples = ", ".join(f"{src} → {dst}" for src, dst in sorted(matching)[:3])
            issues.append(
                self._page_issue(
                    rule,
                    crawl_run_id,
                    page,
                    "Temporary (302) redirect pair(s) appear consistently across the crawl and "
                    f"likely should be permanent (301): {examples}.",
                )
            )
        return issues

    def _robots_txt_syntax_error(
        self, rule: RuleDefinition, crawl_run_id: int, _: list[PageContext], __: list[SitemapFinding]
    ) -> list[IssueRecord]:
        crawl_run = self._current_crawl_run
        if crawl_run is None or not crawl_run.robots_txt_found:
            return []
        if crawl_run.robots_txt_valid is not False:
            return []
        return [
            IssueRecord(
                crawl_run_id=crawl_run_id,
                crawled_page_id=None,
                target_url="/robots.txt",
                rule_id=rule.id,
                category=rule.category,
                severity=rule.severity,
                message="robots.txt was found but appears to have syntax problems.",
            )
        ]

    def _robots_txt_missing(
        self, rule: RuleDefinition, crawl_run_id: int, _: list[PageContext], __: list[SitemapFinding]
    ) -> list[IssueRecord]:
        crawl_run = self._current_crawl_run
        if crawl_run is None or crawl_run.robots_txt_found is not False:
            return []
        return [
            IssueRecord(
                crawl_run_id=crawl_run_id,
                crawled_page_id=None,
                target_url="/robots.txt",
                rule_id=rule.id,
                category=rule.category,
                severity=rule.severity,
                message=(
                    "No robots.txt was found at the site root. This may be intentional, "
                    "but crawlers then fall back to default allow behavior."
                ),
            )
        ]

    def _ai_crawler_blocked(
        self, rule: RuleDefinition, crawl_run_id: int, _: list[PageContext], __: list[SitemapFinding]
    ) -> list[IssueRecord]:
        crawl_run = self._current_crawl_run
        if crawl_run is None:
            return []
        blocked = crawl_run.robots_txt_ai_disallowed or []
        if not isinstance(blocked, list) or not blocked:
            return []
        agents = ", ".join(str(agent) for agent in blocked)
        return [
            IssueRecord(
                crawl_run_id=crawl_run_id,
                crawled_page_id=None,
                target_url="/robots.txt",
                rule_id=rule.id,
                category=rule.category,
                severity=rule.severity,
                message=(
                    f"AI crawler user-agent(s) are disallowed in robots.txt: {agents}. "
                    "This may be an intentional policy choice."
                ),
            )
        ]

    def _llms_txt_missing(
        self, rule: RuleDefinition, crawl_run_id: int, _: list[PageContext], __: list[SitemapFinding]
    ) -> list[IssueRecord]:
        crawl_run = self._current_crawl_run
        if crawl_run is None or crawl_run.llms_txt_present is not False:
            return []
        return [
            IssueRecord(
                crawl_run_id=crawl_run_id,
                crawled_page_id=None,
                target_url="/llms.txt",
                rule_id=rule.id,
                category=rule.category,
                severity=rule.severity,
                message=(
                    "No llms.txt was found at the site root. This is an emerging convention "
                    "for AI assistants (not a hard requirement)."
                ),
            )
        ]

    def _answer_first_heuristic(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in pages:
            if not page.page.is_indexable:
                continue
            if page.page.status_code is not None and page.page.status_code >= 400:
                continue
            result = self._first_answer_paragraph(page.page.raw_html_path)
            if result is None:
                continue
            word_count, reason = result
            if word_count >= ANSWER_FIRST_MIN_WORDS:
                continue
            issues.append(
                self._page_issue(
                    rule,
                    crawl_run_id,
                    page,
                    (
                        "Content may bury the answer: "
                        f"{reason} (first meaningful paragraph has {word_count} words; "
                        f"aim for {ANSWER_FIRST_MIN_WORDS}+ before the first H2)."
                    ),
                )
            )
        return issues

    def _first_answer_paragraph(self, raw_html_path: str | None) -> tuple[int, str] | None:
        """Return (word_count, reason) for the first post-H1 paragraph before H2, if evaluable."""
        if not raw_html_path:
            return None
        path = Path(raw_html_path)
        if not path.exists():
            return None

        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
        body = soup.body or soup
        h1 = body.find("h1")
        if h1 is None:
            return None

        for element in h1.find_all_next(["p", "h2", "h3", "h4", "h5", "h6"]):
            name = (element.name or "").lower()
            if name in {"h2", "h3", "h4", "h5", "h6"}:
                return 0, "no substantive paragraph found before the first subheading"
            text = " ".join(element.get_text(" ", strip=True).split())
            if self._looks_like_nav_crumb(element, text):
                continue
            words = text.split()
            return len(words), "opening paragraph is very short or thin"

        return 0, "no paragraph content found after the H1"

    def _looks_like_nav_crumb(self, element: Any, text: str) -> bool:
        if not text:
            return True
        classes = " ".join(element.get("class", []) if hasattr(element, "get") else []).lower()
        parent = element.parent
        parent_classes = ""
        parent_id = ""
        if parent is not None and hasattr(parent, "get"):
            parent_classes = " ".join(parent.get("class", []) or []).lower()
            parent_id = str(parent.get("id") or "").lower()
        haystack = f"{classes} {parent_classes} {parent_id}"
        if any(token in haystack for token in ("breadcrumb", "breadcrumbs", "crumb", "nav")):
            return True
        # Very link-heavy short lines often are crumbs.
        links = element.find_all("a") if hasattr(element, "find_all") else []
        if links and len(text.split()) <= 12 and len(links) >= max(1, len(text.split()) // 3):
            return True
        return False

    def _sitemap_not_found(
        self, rule: RuleDefinition, crawl_run_id: int, _: list[PageContext], findings: list[SitemapFinding]
    ) -> list[IssueRecord]:
        return self._sitemap_structure_issues(rule, crawl_run_id, findings, "sitemap_not_found")

    def _sitemap_malformed(
        self, rule: RuleDefinition, crawl_run_id: int, _: list[PageContext], findings: list[SitemapFinding]
    ) -> list[IssueRecord]:
        return self._sitemap_structure_issues(rule, crawl_run_id, findings, "sitemap_malformed")

    def _sitemap_child_broken(
        self, rule: RuleDefinition, crawl_run_id: int, _: list[PageContext], findings: list[SitemapFinding]
    ) -> list[IssueRecord]:
        return self._sitemap_structure_issues(rule, crawl_run_id, findings, "sitemap_child_broken")

    def _missing_og_tags(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in pages:
            tech = page.technical
            if tech is None:
                continue
            missing = []
            if not (tech.og_title or "").strip():
                missing.append("og:title")
            if not (tech.og_description or "").strip():
                missing.append("og:description")
            if not (tech.og_image or "").strip():
                missing.append("og:image")
            if not missing:
                continue
            issues.append(
                self._page_issue(
                    rule,
                    crawl_run_id,
                    page,
                    f"Missing Open Graph tag(s): {', '.join(missing)}.",
                )
            )
        return issues

    def _missing_twitter_card(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in pages:
            tech = page.technical
            if tech is None:
                continue
            if (tech.twitter_card or "").strip() and (tech.twitter_title or "").strip():
                continue
            missing = []
            if not (tech.twitter_card or "").strip():
                missing.append("twitter:card")
            if not (tech.twitter_title or "").strip():
                missing.append("twitter:title")
            issues.append(
                self._page_issue(
                    rule,
                    crawl_run_id,
                    page,
                    f"Missing Twitter card tag(s): {', '.join(missing)}.",
                )
            )
        return issues

    def _missing_html_lang(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        return [
            self._page_issue(
                rule,
                crawl_run_id,
                page,
                "The <html> tag is missing a lang attribute.",
            )
            for page in pages
            if page.technical is not None and not (page.technical.html_lang or "").strip()
        ]

    def _missing_favicon(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        return [
            self._page_issue(
                rule,
                crawl_run_id,
                page,
                "No favicon was detected on the homepage (link rel=icon or /favicon.ico).",
            )
            for page in self._homepage_contexts(pages)
            if page.technical is not None and not page.technical.favicon_present
        ]

    def _organization_schema(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in self._homepage_contexts(pages):
            tech = page.technical
            blocks = tech.schema_json if tech is not None else None
            if isinstance(blocks, list) and schema_blocks_have_type(blocks, "Organization"):
                continue
            issues.append(
                self._page_issue(
                    rule,
                    crawl_run_id,
                    page,
                    "Homepage is missing Organization JSON-LD schema.",
                )
            )
        return issues

    def _website_schema(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in self._homepage_contexts(pages):
            tech = page.technical
            blocks = tech.schema_json if tech is not None else None
            if isinstance(blocks, list) and schema_blocks_have_type(blocks, "WebSite"):
                continue
            issues.append(
                self._page_issue(
                    rule,
                    crawl_run_id,
                    page,
                    "Homepage is missing WebSite JSON-LD schema.",
                )
            )
        return issues

    def _generic_404_page(
        self, rule: RuleDefinition, crawl_run_id: int, _: list[PageContext], __: list[SitemapFinding]
    ) -> list[IssueRecord]:
        crawl_run = self._current_crawl_run
        if crawl_run is None or crawl_run.soft_404_is_soft is not True:
            return []
        return [
            IssueRecord(
                crawl_run_id=crawl_run_id,
                crawled_page_id=None,
                target_url=crawl_run.soft_404_probe_url,
                rule_id=rule.id,
                category=rule.category,
                severity=rule.severity,
                message=crawl_run.soft_404_detail
                or "Unknown URLs do not return a proper custom 404 page.",
            )
        ]

    def _schema_invalid(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        issues: list[IssueRecord] = []
        for page in pages:
            tech = page.technical
            if tech is None or not isinstance(tech.schema_json, list) or not tech.schema_json:
                continue
            problems = validate_schema_blocks(tech.schema_json)
            if not problems:
                continue
            issues.append(
                self._page_issue(
                    rule,
                    crawl_run_id,
                    page,
                    " ".join(problems[:3])
                    + (f" (+{len(problems) - 3} more)." if len(problems) > 3 else ""),
                )
            )
        return issues

    def _keyword_cannibalization(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        candidates = [
            page
            for page in pages
            if page.page.is_indexable
            and (page.page.status_code is None or page.page.status_code < 400)
            and ((page.page.title or "").strip() or (page.page.h1 or "").strip())
        ]
        flagged: dict[int, set[str]] = defaultdict(set)
        for index, left in enumerate(candidates):
            left_tokens = self._intent_tokens(left.page.title, left.page.h1)
            if len(left_tokens) < 2:
                continue
            for right in candidates[index + 1 :]:
                right_tokens = self._intent_tokens(right.page.title, right.page.h1)
                if len(right_tokens) < 2:
                    continue
                overlap = self._token_overlap(left_tokens, right_tokens)
                if overlap < KEYWORD_CANNIBALIZATION_THRESHOLD:
                    continue
                flagged[left.page.id].add(right.page.url)
                flagged[right.page.id].add(left.page.url)

        issues: list[IssueRecord] = []
        by_id = {page.page.id: page for page in candidates}
        for page_id, rivals in flagged.items():
            page = by_id[page_id]
            sample = ", ".join(sorted(rivals)[:3])
            extra = f" (+{len(rivals) - 3} more)" if len(rivals) > 3 else ""
            issues.append(
                self._page_issue(
                    rule,
                    crawl_run_id,
                    page,
                    "Title/H1 text is highly similar to other page(s) and may cannibalize "
                    f"the same search intent: {sample}{extra}.",
                )
            )
        return issues

    def _poor_content_structure(
        self, rule: RuleDefinition, crawl_run_id: int, pages: list[PageContext], _: list[SitemapFinding]
    ) -> list[IssueRecord]:
        return [
            self._page_issue(
                rule,
                crawl_run_id,
                page,
                f"Long-form page ({page.page.word_count} words) has no H2/H3 subheadings.",
            )
            for page in pages
            if (page.page.word_count or 0) > LONG_FORM_WORD_COUNT
            and page.h2_count == 0
            and page.h3_count == 0
        ]

    def _intent_tokens(self, title: str | None, h1: str | None) -> set[str]:
        text = f"{title or ''} {h1 or ''}".lower()
        tokens = {token for token in re.findall(r"[a-z0-9]{3,}", text)}
        stop = {
            "the",
            "and",
            "for",
            "with",
            "from",
            "your",
            "our",
            "this",
            "that",
            "page",
            "home",
            "best",
            "guide",
        }
        return {token for token in tokens if token not in stop}

    def _token_overlap(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        intersection = len(left & right)
        union = len(left | right)
        return intersection / union if union else 0.0

    def _sitemap_structure_issues(
        self,
        rule: RuleDefinition,
        crawl_run_id: int,
        findings: list[SitemapFinding],
        finding_type: str,
    ) -> list[IssueRecord]:
        return [
            IssueRecord(
                crawl_run_id=crawl_run_id,
                crawled_page_id=None,
                target_url=finding.url,
                rule_id=rule.id,
                category=rule.category,
                severity=rule.severity,
                message=finding.message or f"Sitemap issue: {finding_type}.",
            )
            for finding in findings
            if finding.finding_type == finding_type
        ]

    def _tracking_params_present(self, url: str) -> set[str]:
        query = parse_qs(urlparse(url).query, keep_blank_values=True)
        found: set[str] = set()
        for key in query:
            lowered = key.lower()
            if lowered in TRACKING_QUERY_PARAMS or lowered.startswith("utm_"):
                found.add(lowered)
        return found

    def _url_has_uppercase(self, url: str) -> bool:
        parsed = urlparse(url)
        path_and_query = f"{parsed.path or ''}{('?' + parsed.query) if parsed.query else ''}"
        return any(ch.isupper() for ch in path_and_query)

    def _redirect_chain_urls(self, page: PageContext) -> list[str]:
        urls: list[str] = []
        tech = page.technical
        if tech and isinstance(tech.redirect_chain_json, list):
            for hop in tech.redirect_chain_json:
                if isinstance(hop, dict) and hop.get("url"):
                    urls.append(str(hop["url"]))
        urls.append(page.page.url)
        return urls

    def _redirect_hop_pairs(self, page: PageContext) -> list[tuple[str, str, int | None]]:
        """Return (source_url, destination_url, status_code) for each redirect hop."""
        tech = page.technical
        hops: list[dict[str, Any]] = []
        if tech and isinstance(tech.redirect_chain_json, list):
            hops = [hop for hop in tech.redirect_chain_json if isinstance(hop, dict) and hop.get("url")]

        if not hops:
            return []

        pairs: list[tuple[str, str, int | None]] = []
        for index, hop in enumerate(hops):
            source = str(hop["url"])
            status = hop.get("status_code")
            status_code = int(status) if isinstance(status, int) else None
            if index + 1 < len(hops):
                destination = str(hops[index + 1]["url"])
            else:
                destination = page.page.url
            pairs.append((source, destination, status_code))
        return pairs

    def _duplicate_text_issues(
        self,
        rule: RuleDefinition,
        crawl_run_id: int,
        pages: list[PageContext],
        value_getter: Any,
        template: str,
    ) -> list[IssueRecord]:
        groups = defaultdict(list)
        for page in pages:
            value = (value_getter(page) or "").strip().lower()
            if value:
                groups[value].append(page)

        issues: list[IssueRecord] = []
        for group in groups.values():
            unique_pages = self._unique_pages_by_url(group)
            if len(unique_pages) < 2:
                continue
            for page in unique_pages:
                issues.append(
                    self._page_issue(
                        rule,
                        crawl_run_id,
                        page,
                        template.format(count=len(unique_pages)),
                    )
                )
        return issues

    def _unique_pages_by_url(self, pages: list[PageContext]) -> list[PageContext]:
        unique: list[PageContext] = []
        seen: set[str] = set()
        for page in pages:
            key = normalize_url(page.page.url)
            if key in seen:
                continue
            seen.add(key)
            unique.append(page)
        return unique

    def _vital_issues(
        self,
        rule: RuleDefinition,
        crawl_run_id: int,
        pages: list[PageContext],
        field_name: str,
        threshold: float,
        message_template: str,
    ) -> list[IssueRecord]:
        # Skipped automatically when ENABLE_PAGESPEED is off / no vitals exist.
        issues: list[IssueRecord] = []
        for page in pages:
            candidates = [getattr(vital, field_name) for vital in page.vitals.values()]
            values = [value for value in candidates if value is not None]
            if not values:
                continue
            worst = max(values)
            if worst > threshold:
                issues.append(
                    self._page_issue(
                        rule,
                        crawl_run_id,
                        page,
                        message_template.format(value=worst),
                    )
                )
        return issues

    def _homepage_contexts(self, pages: list[PageContext]) -> list[PageContext]:
        """Return pages that are the site homepage (HOMEPAGE-scoped checks only)."""
        crawl = self._current_crawl_run
        domain = ""
        if crawl is not None and crawl.domain:
            domain = crawl.domain.lower().removeprefix("www.")

        matches: list[PageContext] = []
        for page in pages:
            parsed = urlparse(page.page.url)
            host = (parsed.hostname or "").lower().removeprefix("www.")
            path = parsed.path or "/"
            if domain and host != domain:
                continue
            if path in {"", "/"} and not parsed.query:
                matches.append(page)

        if matches:
            return matches

        # Fallback: shortest path on the crawl domain (or overall if domain unknown).
        candidates = pages
        if domain:
            candidates = [
                page
                for page in pages
                if (urlparse(page.page.url).hostname or "").lower().removeprefix("www.") == domain
            ] or pages
        if not candidates:
            return []
        return [
            min(
                candidates,
                key=lambda page: (len(urlparse(page.page.url).path or "/"), len(page.page.url)),
            )
        ]

    def _page_issue(
        self,
        rule: RuleDefinition,
        crawl_run_id: int,
        page: PageContext,
        message: str,
    ) -> IssueRecord:
        return IssueRecord(
            crawl_run_id=crawl_run_id,
            crawled_page_id=page.page.id,
            target_url=normalize_url(page.page.url),
            rule_id=rule.id,
            category=rule.category,
            severity=rule.severity,
            message=message,
        )

    def _content_hash(self, soup: BeautifulSoup) -> str | None:
        for tag in soup(["script", "style", "noscript", "template", "svg"]):
            tag.extract()
        text = " ".join(soup.get_text(" ", strip=True).split())
        if len(text.split()) < 50:
            return None
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def _has_mixed_content(self, soup: BeautifulSoup, page_url: str) -> bool:
        if not page_url.startswith("https://"):
            return False
        for tag in soup.find_all(["img", "script", "iframe", "audio", "video", "source", "link"]):
            candidate = tag.get("src") or tag.get("href")
            if isinstance(candidate, str) and candidate.strip().lower().startswith("http://"):
                return True
        return False

    def _normalize_url(self, url: str) -> str:
        return normalize_url(url)
