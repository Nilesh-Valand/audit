"""Helpers for reading site_issues + page_issues without merging into one table."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.checks import scope_for
from app.models import PageIssue, SiteIssue


@dataclass(slots=True)
class IssueView:
    """Normalized view used by API/report layers (never stored)."""

    id: str
    crawl_id: int
    check_name: str
    status: str
    details: str
    severity: str
    category: str
    url: str | None
    scope: str  # registry Scope value: site | page | cross_page | homepage

    @property
    def rule_id(self) -> str:
        return self.check_name

    @property
    def message(self) -> str:
        return self.details

    @property
    def target_url(self) -> str | None:
        return self.url


@lru_cache(maxsize=1)
def _rules_category_map() -> dict[str, str]:
    path = Path(__file__).resolve().parents[1] / "rules" / "rules.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return {
        str(item["id"]): str(item.get("category") or "technical")
        for item in payload
        if isinstance(item, dict) and item.get("id")
    }


def category_for_check(check_name: str, rules_by_id: dict[str, object] | None = None) -> str:
    if rules_by_id and check_name in rules_by_id:
        rule = rules_by_id[check_name]
        category = getattr(rule, "category", None)
        if isinstance(category, str) and category:
            return category
    return _rules_category_map().get(check_name, "technical")


def _view_scope(check_name: str, *, storage_fallback: str) -> str:
    registered = scope_for(check_name)
    return registered.value if registered is not None else storage_fallback


def load_issue_views(
    db: Session,
    crawl_id: int,
    *,
    category: str | None = None,
    severity: str | None = None,
    rules_by_id: dict[str, object] | None = None,
) -> list[IssueView]:
    site_rows = db.scalars(select(SiteIssue).where(SiteIssue.crawl_id == crawl_id)).all()
    page_rows = db.scalars(select(PageIssue).where(PageIssue.crawl_id == crawl_id)).all()

    views: list[IssueView] = []
    for row in site_rows:
        if row.status != "fail":
            continue
        cat = category_for_check(row.check_name, rules_by_id)
        if category and cat != category:
            continue
        if severity and row.severity != severity:
            continue
        views.append(
            IssueView(
                id=f"site-{row.id}",
                crawl_id=row.crawl_id,
                check_name=row.check_name,
                status=row.status,
                details=row.details,
                severity=row.severity,
                category=cat,
                url=None,
                scope=_view_scope(row.check_name, storage_fallback="site"),
            )
        )
    for row in page_rows:
        if row.status != "fail":
            continue
        cat = category_for_check(row.check_name, rules_by_id)
        if category and cat != category:
            continue
        if severity and row.severity != severity:
            continue
        views.append(
            IssueView(
                id=f"page-{row.id}",
                crawl_id=row.crawl_id,
                check_name=row.check_name,
                status=row.status,
                details=row.details,
                severity=row.severity,
                category=cat,
                url=row.url,
                scope=_view_scope(row.check_name, storage_fallback="page"),
            )
        )
    return views

def count_issues_by_severity(db: Session, crawl_id: int) -> dict[str, int]:
    counts = {key: 0 for key in ("critical", "high", "medium", "low")}
    for model in (SiteIssue, PageIssue):
        rows = db.execute(
            select(model.severity, func.count())
            .where(model.crawl_id == crawl_id, model.status == "fail")
            .group_by(model.severity)
        ).all()
        for severity, count in rows:
            key = (severity or "").lower()
            if key in counts:
                counts[key] += int(count or 0)
    return counts


def count_page_issues_for_url(db: Session, crawl_id: int, url: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(PageIssue)
            .where(
                PageIssue.crawl_id == crawl_id,
                PageIssue.url == url,
                PageIssue.status == "fail",
            )
        )
        or 0
    )
