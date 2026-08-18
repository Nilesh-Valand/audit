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
    "canonical_noindex_conflict": (
        "A page is both canonical (the preferred version) and marked noindex. "
        "Remove noindex from the intended canonical target, or repoint the "
        "canonical to a page that is actually indexable."
    ),
    "ai_crawler_blocked": (
        "Your robots.txt disallows AI crawlers (e.g. GPTBot, PerplexityBot). "
        "If you want your content discoverable by AI assistants and answer "
        "engines, remove the blanket disallow and scope any restrictions to "
        "specific paths instead."
    ),
    "answer_first_heuristic": (
        "Lead each page with a direct 20+ word answer to its main query before "
        "the first H2 — search and AI answer engines favor content that states "
        "the takeaway immediately rather than building up to it."
    ),
    "broken_link": (
        "Fix or remove broken internal/external links. Update the href to the "
        "correct URL, or delete the link if the target no longer exists — "
        "broken links waste crawl budget and hurt user trust."
    ),
    "cls_fail": (
        "Cumulative Layout Shift exceeds the Core Web Vitals threshold. Set "
        "explicit width/height (or aspect-ratio) on images and embeds, and "
        "reserve space for ads/fonts so content doesn't jump as the page loads."
    ),
    "crawled_not_in_sitemap": (
        "These crawled URLs aren't listed in your sitemap. Add them to keep "
        "the sitemap a complete, accurate index of your indexable pages."
    ),
    "duplicate_content": (
        "Multiple pages share substantially the same content. Consolidate "
        "them into one page, add self-referencing canonicals to signal the "
        "preferred version, or differentiate the content meaningfully."
    ),
    "duplicate_meta_description": (
        "Write a unique meta description for each page summarizing its "
        "specific content — duplicate descriptions waste an opportunity to "
        "improve click-through from search results."
    ),
    "duplicate_title": (
        "Give each page a unique, descriptive <title> — duplicate titles make "
        "it harder for search engines and users to tell pages apart in results."
    ),
    "excessive_requests": (
        "This page loads an unusually high number of subresources. Combine or "
        "lazy-load scripts/stylesheets/images, and remove any unused tags or "
        "trackers to reduce request count and speed up load time."
    ),
    "excessive_url_length": (
        "Shorten this URL. Long URLs are harder to share, read, and can get "
        "truncated in search results — aim for concise, descriptive paths."
    ),
    "generic_404_page": (
        "Return a true 404 (or 410) status code for missing pages instead of "
        "a soft-404 (a 200 response with 'not found' wording) — soft-404s "
        "confuse crawlers about which URLs are actually valid."
    ),
    "inp_fail": (
        "Interaction to Next Paint exceeds the Core Web Vitals threshold. "
        "Break up long JavaScript tasks, defer non-critical scripts, and "
        "reduce main-thread work so the page responds faster to input."
    ),
    "keyword_cannibalization": (
        "Multiple pages are competing for the same target keyword. Consolidate "
        "them into a single authoritative page, or differentiate each page's "
        "focus keyword and internal linking so they don't compete with each "
        "other in search results."
    ),
    "large_page_weight": (
        "This page's total transfer weight is high. Compress and resize "
        "images, minify/defer scripts and stylesheets, and lazy-load "
        "below-the-fold assets to reduce load time."
    ),
    "lcp_fail": (
        "Largest Contentful Paint exceeds the Core Web Vitals threshold. "
        "Optimize/preload the hero image or text block, reduce render-blocking "
        "CSS/JS, and improve server response time (TTFB)."
    ),
    "llms_txt_missing": (
        "Add an /llms.txt file at the site root summarizing your site's "
        "purpose and key pages for AI assistants and answer engines to "
        "reference — an emerging convention alongside robots.txt/sitemap.xml."
    ),
    "missing_h1": (
        "Add a single, descriptive <h1> heading to this page — it's the "
        "primary signal to search engines (and users) of what the page is "
        "about."
    ),
    "missing_html_lang": (
        "Add a lang attribute to the <html> tag (e.g. <html lang=\"en\">) so "
        "browsers, screen readers, and search engines correctly identify the "
        "page's language."
    ),
    "missing_image_dimensions": (
        "Add explicit width and height attributes (or CSS aspect-ratio) to "
        "<img> tags so the browser can reserve space before the image loads, "
        "preventing layout shift."
    ),
    "missing_meta_description": (
        "Add a unique, ~150-160 character meta description summarizing the "
        "page — it's often shown as the search-result snippet and influences "
        "click-through rate."
    ),
    "missing_og_tags": (
        "Add Open Graph tags (og:title, og:description, og:image, og:url) so "
        "the page renders correctly with a title, description, and image when "
        "shared on social platforms."
    ),
    "missing_schema": (
        "Add relevant JSON-LD structured data (e.g. Article, Product, "
        "FAQPage) so search engines can understand and potentially surface "
        "this content as a rich result."
    ),
    "missing_title": (
        "Add a unique, descriptive <title> tag to this page — it's one of the "
        "strongest on-page ranking signals and what users see in search "
        "results and browser tabs."
    ),
    "missing_twitter_card": (
        "Add Twitter Card meta tags (twitter:card, twitter:title, "
        "twitter:description, twitter:image) so links to this page render "
        "with a rich preview on X/Twitter."
    ),
    "mixed_content": (
        "This HTTPS page loads resources over plain HTTP. Update those "
        "resource URLs to HTTPS — mixed content gets blocked or flagged by "
        "browsers and undermines the page's security posture."
    ),
    "multiple_h1": (
        "Use only one <h1> per page as the primary heading, and demote "
        "additional top-level headings to <h2>/<h3> to keep a clear content "
        "hierarchy."
    ),
    "orphan_page": (
        "This page has no internal links pointing to it. Add links from "
        "relevant pages (navigation, related content, sitemap) so crawlers "
        "and users can actually discover it."
    ),
    "outdated_image_format": (
        "Convert JPG/PNG images to WebP or AVIF where supported — they "
        "typically cut file size significantly at the same visual quality, "
        "improving load time."
    ),
    "oversized_images": (
        "These images are served larger than their displayed size. Resize "
        "them to the actual rendered dimensions (and use srcset for "
        "responsive sizing) to cut unnecessary transfer weight."
    ),
    "poor_content_structure": (
        "Break up this content with a clear heading hierarchy (H2s/H3s), "
        "shorter paragraphs, and lists where appropriate — both readers and "
        "search engines parse well-structured content more easily."
    ),
    "redirect_chain": (
        "Update the source link/reference to point directly at the final "
        "destination URL instead of hopping through intermediate redirects — "
        "each extra hop adds latency and dilutes link equity."
    ),
    "redirect_loop": (
        "Fix this circular redirect — the URL currently redirects back to "
        "itself (directly or via a chain), which makes the page completely "
        "unreachable for users and crawlers."
    ),
    "render_blocking_resources": (
        "Move non-critical stylesheets out of <head> (or load them async/"
        "deferred) and inline critical CSS — render-blocking resources delay "
        "first paint."
    ),
    "robots_txt_missing": (
        "Add a robots.txt file at the site root. Even a permissive one "
        "(Allow: /) is preferable to a missing file, and it's the standard "
        "place to reference your sitemap."
    ),
    "robots_txt_syntax_error": (
        "Fix the malformed directive(s) in robots.txt — syntax errors can "
        "cause crawlers to misinterpret your crawl rules or ignore the file "
        "entirely."
    ),
    "schema_invalid": (
        "Fix the JSON-LD parse error on this page (check for trailing commas, "
        "unescaped quotes, or mismatched brackets) — invalid structured data "
        "is ignored by search engines."
    ),
    "sitemap_child_broken": (
        "This child sitemap referenced from your sitemap index returns an "
        "error. Fix or remove the broken child sitemap URL so the full "
        "sitemap set resolves correctly."
    ),
    "sitemap_malformed": (
        "Fix the sitemap XML so it validates against the sitemap protocol "
        "(well-formed XML, correct <urlset>/<loc> structure) — malformed "
        "sitemaps may be rejected or partially ignored by search engines."
    ),
    "sitemap_not_found": (
        "Publish a sitemap.xml at the site root (or reference its actual "
        "location in robots.txt) so search engines have a complete list of "
        "URLs to crawl and index."
    ),
    "sitemap_orphan": (
        "Pages listed in your sitemap weren't reached by this crawl. Re-run "
        "the audit with a higher max-pages limit to cover the full sitemap, "
        "and check that these URLs are actually linked internally, not just "
        "sitemap-only orphans."
    ),
    "slow_ttfb": (
        "Time to First Byte is slow. Investigate server/database response "
        "time, enable caching (page or edge/CDN), and consider a faster "
        "hosting tier — TTFB is the floor under every other performance "
        "metric."
    ),
    "temp_redirect_should_be_permanent": (
        "This redirect looks permanent in practice but returns a 302 (temporary) "
        "status. Switch it to a 301 so link equity and rankings transfer "
        "properly to the destination URL."
    ),
    "thin_content": (
        "Expand this page's content — it falls below a healthy word-count "
        "threshold for the topic. Add substantive, unique detail, or "
        "consolidate it into a more comprehensive page if it can't stand on "
        "its own."
    ),
    "underscore_in_url": (
        "Use hyphens instead of underscores in URL paths (e.g. /my-page not "
        "/my_page) — search engines treat hyphens as word separators but "
        "underscores as joiners, which can hurt keyword matching."
    ),
    "unnecessary_url_parameters": (
        "Strip tracking/session query parameters from canonical/internal "
        "links where possible, and ensure a clean canonical URL — unnecessary "
        "parameters create duplicate-content variants of the same page."
    ),
    "uppercase_url": (
        "Use lowercase URL paths consistently. Mixed-case URLs can be treated "
        "as distinct URLs on case-sensitive servers, splitting ranking "
        "signals and creating duplicate-content risk."
    ),
}


def recommendation_for_rule(rule_id: str, fallback: str) -> str:
    return RULE_RECOMMENDATIONS.get(rule_id, fallback)
