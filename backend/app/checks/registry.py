"""Central check registry — single source of truth for check scope.

No other module should hardcode whether a check is site-, page-, cross-page-,
or homepage-scoped. Import helpers from here instead.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Callable


class Scope(str, Enum):
    SITE = "site"
    PAGE = "page"
    CROSS_PAGE = "cross_page"
    HOMEPAGE = "homepage"


CheckRunFn = Callable[..., list[Any]]


@dataclass(frozen=True, slots=True)
class CheckEntry:
    """One registered SEO check."""

    name: str
    scope: Scope
    severity_default: str
    run_fn: CheckRunFn | None = None
    # Engine method name used to bind run_fn (RuleEngine._missing_title → "_missing_title").
    method: str = ""


def _entry(
    name: str,
    scope: Scope,
    severity_default: str,
    *,
    method: str | None = None,
) -> CheckEntry:
    return CheckEntry(
        name=name,
        scope=scope,
        severity_default=severity_default,
        method=method or f"_{name}",
    )


# ---------------------------------------------------------------------------
# Registry population (name + scope + default severity). run_fn is bound later.
# ---------------------------------------------------------------------------

CHECK_SPECS: tuple[CheckEntry, ...] = (
    # --- SITE -----------------------------------------------------------------
    _entry("robots_txt_missing", Scope.SITE, "low"),
    _entry("robots_txt_syntax_error", Scope.SITE, "medium"),
    _entry("sitemap_not_found", Scope.SITE, "medium"),
    _entry("sitemap_malformed", Scope.SITE, "high"),
    _entry("sitemap_child_broken", Scope.SITE, "high"),
    _entry("llms_txt_missing", Scope.SITE, "low"),
    _entry("ai_crawler_blocked", Scope.SITE, "low"),
    _entry("redirect_loop", Scope.SITE, "high"),
    _entry("sitemap_orphan", Scope.SITE, "medium"),  # sitemap URLs not found in crawl
    _entry("crawled_not_in_sitemap", Scope.SITE, "low"),  # crawled pages missing from sitemap
    # Kept as site-level probe (not in the brief list, but existing check).
    _entry("generic_404_page", Scope.SITE, "medium"),
    # --- PAGE -----------------------------------------------------------------
    _entry("missing_title", Scope.PAGE, "high"),
    _entry("missing_meta_description", Scope.PAGE, "medium"),
    _entry("missing_h1", Scope.PAGE, "medium"),
    _entry("multiple_h1", Scope.PAGE, "low"),
    _entry("canonical_noindex_conflict", Scope.PAGE, "high"),
    _entry("broken_link", Scope.PAGE, "high"),  # broken outgoing / page status
    _entry("uppercase_url", Scope.PAGE, "low"),
    _entry("underscore_in_url", Scope.PAGE, "low"),
    _entry("excessive_url_length", Scope.PAGE, "medium"),
    _entry("unnecessary_url_parameters", Scope.PAGE, "medium"),
    _entry("redirect_chain", Scope.PAGE, "medium"),
    _entry("temp_redirect_should_be_permanent", Scope.PAGE, "medium"),  # 302 vs 301
    _entry("lcp_fail", Scope.PAGE, "high"),
    _entry("cls_fail", Scope.PAGE, "medium"),
    _entry("inp_fail", Scope.PAGE, "high"),
    _entry("slow_ttfb", Scope.PAGE, "high"),
    _entry("render_blocking_resources", Scope.PAGE, "medium"),
    _entry("large_page_weight", Scope.PAGE, "high"),
    _entry("oversized_images", Scope.PAGE, "medium"),
    _entry("missing_image_dimensions", Scope.PAGE, "medium"),
    _entry("outdated_image_format", Scope.PAGE, "low"),
    _entry("missing_og_tags", Scope.PAGE, "medium"),
    _entry("missing_twitter_card", Scope.PAGE, "low"),
    _entry("missing_html_lang", Scope.PAGE, "medium"),
    _entry("thin_content", Scope.PAGE, "medium"),
    _entry("missing_schema", Scope.PAGE, "medium"),
    _entry("schema_invalid", Scope.PAGE, "medium"),
    _entry("mixed_content", Scope.PAGE, "critical"),
    _entry("answer_first_heuristic", Scope.PAGE, "low"),
    _entry("poor_content_structure", Scope.PAGE, "medium"),
    _entry("excessive_requests", Scope.PAGE, "medium"),
    # --- CROSS_PAGE -----------------------------------------------------------
    _entry("duplicate_title", Scope.CROSS_PAGE, "medium"),
    _entry("duplicate_meta_description", Scope.CROSS_PAGE, "low"),
    _entry("duplicate_content", Scope.CROSS_PAGE, "high"),
    _entry("keyword_cannibalization", Scope.CROSS_PAGE, "medium"),
    _entry("orphan_page", Scope.CROSS_PAGE, "medium"),
    # Canonical target validation suite
    _entry("missing_canonical", Scope.CROSS_PAGE, "medium"),
    _entry("self_canonical_mismatch", Scope.CROSS_PAGE, "medium"),
    _entry("broken_canonical_url", Scope.CROSS_PAGE, "high"),
    _entry("canonical_points_to_redirect", Scope.CROSS_PAGE, "high"),
    _entry("canonical_points_to_noindex", Scope.CROSS_PAGE, "high"),
    # --- HOMEPAGE -------------------------------------------------------------
    _entry("missing_favicon", Scope.HOMEPAGE, "low"),
    _entry("organization_schema", Scope.HOMEPAGE, "medium"),
    _entry("website_schema", Scope.HOMEPAGE, "medium"),
)

# Ordered list + name lookup (unbound run_fn until bind_registry()).
REGISTRY: dict[str, CheckEntry] = {entry.name: entry for entry in CHECK_SPECS}


def get_check(name: str) -> CheckEntry | None:
    return REGISTRY.get(name)


def scope_for(name: str) -> Scope | None:
    entry = REGISTRY.get(name)
    return entry.scope if entry else None


def severity_default_for(name: str) -> str | None:
    entry = REGISTRY.get(name)
    return entry.severity_default if entry else None


def checks_for_scope(scope: Scope) -> list[CheckEntry]:
    return [entry for entry in CHECK_SPECS if entry.scope is scope]


def writes_to_site_issues(scope: Scope) -> bool:
    """SITE / CROSS_PAGE / HOMEPAGE findings go to site_issues; PAGE → page_issues."""
    return scope in {Scope.SITE, Scope.CROSS_PAGE, Scope.HOMEPAGE}


def bind_registry(engine: Any) -> dict[str, CheckEntry]:
    """Attach RuleEngine methods as run_fn on each registry entry.

    Returns a name→bound CheckEntry map. The module-level REGISTRY is also
    updated so scope_for() / get_check() see bound callables.
    """
    bound: dict[str, CheckEntry] = {}
    for spec in CHECK_SPECS:
        method_name = spec.method or f"_{spec.name}"
        run_fn = getattr(engine, method_name, None)
        if run_fn is None or not callable(run_fn):
            raise AttributeError(
                f"Check '{spec.name}' expects engine method '{method_name}', which is missing."
            )
        entry = replace(spec, run_fn=run_fn)
        bound[spec.name] = entry
        REGISTRY[spec.name] = entry
    return bound


def all_check_names() -> frozenset[str]:
    return frozenset(REGISTRY)
