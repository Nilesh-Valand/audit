"""SEO check package — registry is the single source of truth for scope."""

from app.checks.registry import (
    CHECK_SPECS,
    REGISTRY,
    CheckEntry,
    Scope,
    all_check_names,
    bind_registry,
    checks_for_scope,
    get_check,
    scope_for,
    severity_default_for,
    writes_to_site_issues,
)
from app.checks.cross_page_runner import (
    evaluate_cross_page_checks,
    load_cross_page_context,
    run_cross_page_checks,
)
from app.checks.homepage_runner import (
    evaluate_homepage_checks,
    load_homepage_snapshot,
    run_homepage_checks,
)
from app.checks.orchestrator import (
    AUDIT_STEPS,
    rerun_step,
    run_audit,
    run_step,
)
from app.checks.page_runner import (
    evaluate_page_checks,
    load_page_snapshots,
    run_page_checks,
)
from app.checks.site_runner import (
    SiteAssetCache,
    evaluate_site_checks,
    fetch_site_assets,
    run_site_checks,
)

__all__ = [
    "AUDIT_STEPS",
    "CHECK_SPECS",
    "REGISTRY",
    "CheckEntry",
    "Scope",
    "SiteAssetCache",
    "all_check_names",
    "bind_registry",
    "checks_for_scope",
    "evaluate_cross_page_checks",
    "evaluate_homepage_checks",
    "evaluate_page_checks",
    "evaluate_site_checks",
    "fetch_site_assets",
    "get_check",
    "load_cross_page_context",
    "load_homepage_snapshot",
    "load_page_snapshots",
    "rerun_step",
    "run_audit",
    "run_cross_page_checks",
    "run_homepage_checks",
    "run_page_checks",
    "run_site_checks",
    "run_step",
    "scope_for",
    "severity_default_for",
    "writes_to_site_issues",
]
