"""Human-readable recommendation copy keyed by audit rule id.

Used by ReportService so prioritized recommendations show actionable wording
instead of only the first per-page issue message.
"""

from __future__ import annotations

RULE_RECOMMENDATIONS: dict[str, str] = {
    "missing_canonical": (
        "Add a self-referencing <link rel=\"canonical\"> tag so search engines "
        "know the preferred URL for each indexable page."
    ),
    "self_canonical_mismatch": (
        "Review pages whose canonical URL differs from their own URL. Use a "
        "self-referencing canonical unless you intentionally consolidate "
        "signals to another URL (for example pagination → page 1)."
    ),
    "broken_canonical_url": (
        "Fix or remove broken canonical URLs. Canonical targets must be valid "
        "and return a successful response — broken targets waste ranking signals."
    ),
    "canonical_points_to_redirect": (
        "Update canonical tags to point directly at the final 200 URL. Do not "
        "point canonicals through 3xx redirects."
    ),
    "canonical_points_to_noindex": (
        "Do not canonicalize to a noindex page. Point the canonical at an "
        "indexable URL, or remove noindex from the intended canonical target."
    ),
    "organization_schema": (
        "Add Organization JSON-LD on the homepage so search engines and AI "
        "systems can identify your brand entity (name, URL, logo)."
    ),
    "website_schema": (
        "Add WebSite JSON-LD on the homepage (optionally with SearchAction) "
        "so crawlers understand the site as a whole."
    ),
    "missing_favicon": (
        "Add a favicon on the homepage via <link rel=\"icon\"> or /favicon.ico "
        "so browsers and SERPs can display your brand mark."
    ),
}


def recommendation_for_rule(rule_id: str, fallback: str) -> str:
    return RULE_RECOMMENDATIONS.get(rule_id, fallback)
