"""PAGE-scoped check runner — once per URL already stored in crawl_pages.

Reads crawled HTML/data only (never re-crawls, never fetches robots/sitemap/llms).
Splits PAGE registry checks into:

1. Static / HTML-derived checks against crawl_pages (+ technical_details / links)
2. PageSpeed Insights checks (LCP, CLS, INP, TTFB) with raw JSON cached on
   crawl_pages.pagespeed_raw so report re-runs do not re-hit the API
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.checks.registry import Scope, checks_for_scope, severity_default_for
from app.config import settings
from app.crawler.normalize import normalize_url
from app.db.database import SessionLocal
from app.models import CrawlPage, PageIssue, PageTechnicalDetails
from app.rules.schema_validation import validate_schema_blocks

logger = logging.getLogger(__name__)

PAGESPEED_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
PAGESPEED_MAX_CONCURRENT = 5
PAGESPEED_TIMEOUT = httpx.Timeout(60.0, connect=15.0)

EXCESSIVE_URL_LENGTH = 115
LARGE_PAGE_WEIGHT_BYTES = 3 * 1024 * 1024
EXCESSIVE_RESOURCE_REQUESTS = 100
MAX_BLOCKING_STYLESHEETS = 2
OVERSIZED_IMAGE_BYTES = 200 * 1024
THIN_CONTENT_WORDS = 300
LONG_FORM_WORD_COUNT = 800
ANSWER_FIRST_MIN_WORDS = 20
OUTDATED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}

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

# Core Web Vitals thresholds (good / needs improvement / poor).
# Values are compared with numericValue from Lighthouse audits (ms except CLS).
CWV_THRESHOLDS: dict[str, tuple[float, float]] = {
    # metric: (good_max, needs_improvement_max)
    "lcp_ms": (2500.0, 4000.0),
    "cls": (0.1, 0.25),
    "inp_ms": (200.0, 500.0),
    "ttfb_ms": (800.0, 1800.0),
}

PAGESPEED_CHECK_NAMES: frozenset[str] = frozenset(
    {"lcp_fail", "cls_fail", "inp_fail", "slow_ttfb"}
)
PAGESPEED_FAILED_CHECK = "pagespeed_failed"


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CheckOutcome:
    status: str  # "pass" | "fail"
    details: str
    severity: str | None = None  # override registry default when set


@dataclass(slots=True)
class PageCheckWrite:
    url: str
    check_name: str
    status: str
    details: str
    severity: str


@dataclass(slots=True)
class HtmlSignals:
    h1_count: int = 0
    h2_count: int = 0
    h3_count: int = 0
    has_mixed_content: bool = False
    answer_first: tuple[int, str] | None = None
    """(word_count, reason) for first post-H1 paragraph, if evaluable."""


@dataclass(slots=True)
class PageSnapshot:
    """In-memory view of one crawl_pages row + derived signals (no network)."""

    id: int
    url: str
    status_code: int | None
    title: str | None
    meta_description: str | None
    canonical: str | None
    meta_robots: str | None
    h1: str | None
    h1_list: list | None
    word_count: int | None
    redirect_hops: int
    is_indexable: bool
    has_schema: bool
    raw_html_path: str | None
    pagespeed_raw: dict[str, Any] | None
    technical: PageTechnicalDetails | None
    outgoing_targets: list[str]
    html: HtmlSignals = field(default_factory=HtmlSignals)


@dataclass(slots=True)
class CrawlPageIndex:
    """Lookup helpers shared across per-URL static checks."""

    by_normalized_url: dict[str, PageSnapshot]
    pages: list[PageSnapshot]


@dataclass(slots=True)
class PagespeedMetrics:
    lcp_ms: float | None
    cls: float | None
    inp_ms: float | None
    inp_source: str  # "inp" | "tbt" | "missing"
    ttfb_ms: float | None
    raw: dict[str, Any]


PageCheckFn = Callable[[PageSnapshot, CrawlPageIndex], CheckOutcome]


# ---------------------------------------------------------------------------
# Load from crawl_pages only
# ---------------------------------------------------------------------------


def load_page_snapshots(
    crawl_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> list[PageSnapshot]:
    """Load every crawl_pages row for this crawl (plus tech details + links)."""
    factory = session_factory or SessionLocal
    with factory() as db:
        pages = (
            db.scalars(
                select(CrawlPage)
                .where(CrawlPage.crawl_id == crawl_id)
                .options(
                    joinedload(CrawlPage.technical_details),
                    joinedload(CrawlPage.links),
                )
                .order_by(CrawlPage.id.asc())
            )
            .unique()
            .all()
        )

        snapshots: list[PageSnapshot] = []
        for page in pages:
            outgoing = [link.target_url for link in page.links if link.target_url]
            raw = page.pagespeed_raw if isinstance(page.pagespeed_raw, dict) else None
            snap = PageSnapshot(
                id=page.id,
                url=page.url,
                status_code=page.status_code,
                title=page.title,
                meta_description=page.meta_description,
                canonical=page.canonical,
                meta_robots=page.meta_robots,
                h1=page.h1,
                h1_list=page.h1_list if isinstance(page.h1_list, list) else None,
                word_count=page.word_count,
                redirect_hops=page.redirect_hops or 0,
                is_indexable=bool(page.is_indexable),
                has_schema=bool(page.has_schema),
                raw_html_path=page.raw_html_path,
                pagespeed_raw=raw,
                technical=page.technical_details,
                outgoing_targets=outgoing,
                html=_html_signals(page.raw_html_path, page.url),
            )
            if snap.html.h1_count == 0 and snap.h1_list:
                snap.html.h1_count = len(snap.h1_list)
            elif snap.html.h1_count == 0 and (snap.h1 or "").strip():
                snap.html.h1_count = 1
            snapshots.append(snap)
        return snapshots


def _html_signals(raw_html_path: str | None, page_url: str) -> HtmlSignals:
    if not raw_html_path:
        return HtmlSignals()
    path = Path(raw_html_path)
    if not path.exists():
        return HtmlSignals()
    try:
        html = path.read_text(encoding="utf-8")
    except OSError:
        return HtmlSignals()

    soup = BeautifulSoup(html, "lxml")
    return HtmlSignals(
        h1_count=len(soup.find_all("h1")),
        h2_count=len(soup.find_all("h2")),
        h3_count=len(soup.find_all("h3")),
        has_mixed_content=_has_mixed_content(soup, page_url),
        answer_first=_first_answer_paragraph(soup),
    )


def _has_mixed_content(soup: BeautifulSoup, page_url: str) -> bool:
    if not page_url.startswith("https://"):
        return False
    for tag in soup.find_all(["img", "script", "iframe", "audio", "video", "source", "link"]):
        candidate = tag.get("src") or tag.get("href")
        if isinstance(candidate, str) and candidate.strip().lower().startswith("http://"):
            return True
    return False


def _first_answer_paragraph(soup: BeautifulSoup) -> tuple[int, str] | None:
    body = soup.body or soup
    h1 = body.find("h1")
    if h1 is None:
        return None

    for element in h1.find_all_next(["p", "h2", "h3", "h4", "h5", "h6"]):
        name = (element.name or "").lower()
        if name in {"h2", "h3", "h4", "h5", "h6"}:
            return 0, "no substantive paragraph found before the first subheading"
        text = " ".join(element.get_text(" ", strip=True).split())
        if _looks_like_nav_crumb(element, text):
            continue
        words = text.split()
        return len(words), "opening paragraph is very short or thin"

    return 0, "no paragraph content found after the H1"


def _looks_like_nav_crumb(element: Any, text: str) -> bool:
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
    links = element.find_all("a") if hasattr(element, "find_all") else []
    if links and len(text.split()) <= 12 and len(links) >= max(1, len(text.split()) // 3):
        return True
    return False


# ---------------------------------------------------------------------------
# Static / HTML-derived check handlers
# ---------------------------------------------------------------------------


def _pass(details: str, *, severity: str | None = None) -> CheckOutcome:
    return CheckOutcome(status="pass", details=details, severity=severity)


def _fail(details: str, *, severity: str | None = None) -> CheckOutcome:
    return CheckOutcome(status="fail", details=details, severity=severity)


def check_missing_title(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    if (page.title or "").strip():
        return _pass("Page has a title tag.")
    return _fail("Page is missing a title tag.")


def check_missing_meta_description(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    if (page.meta_description or "").strip():
        return _pass("Page has a meta description.")
    return _fail("Page is missing a meta description.")


def check_missing_h1(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    if page.html.h1_count > 0:
        return _pass("Page has an H1 heading.")
    return _fail("Page is missing an H1 heading.")


def check_multiple_h1(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    if page.html.h1_count <= 1:
        return _pass("Page does not have multiple H1 headings.")
    return _fail(f"Page contains {page.html.h1_count} H1 headings.")


def check_canonical_noindex_conflict(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    has_canonical = bool((page.canonical or "").strip())
    has_noindex = "noindex" in (page.meta_robots or "").lower()
    if has_canonical and has_noindex:
        return _fail("Page sets a canonical URL while also including noindex.")
    return _pass("No canonical + noindex conflict.")


def check_broken_link(page: PageSnapshot, index: CrawlPageIndex) -> CheckOutcome:
    if page.status_code is not None and page.status_code >= 400:
        return _fail(f"Page returned status {page.status_code}.")

    broken: list[str] = []
    for target in page.outgoing_targets:
        key = normalize_url(target)
        dest = index.by_normalized_url.get(key)
        if dest is None or dest.status_code is None or dest.status_code < 400:
            continue
        broken.append(f"{dest.url} ({dest.status_code})")
    if not broken:
        return _pass("No broken outgoing links to crawled pages detected.")
    sample = "; ".join(broken[:3])
    extra = f" (+{len(broken) - 3} more)" if len(broken) > 3 else ""
    return _fail(
        f"{len(broken)} outgoing link(s) point to broken crawled URL(s): {sample}{extra}."
    )


def check_uppercase_url(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    tech = page.technical
    has_upper = (
        tech.url_has_uppercase if tech is not None else _url_has_uppercase(page.url)
    )
    if has_upper:
        return _fail(
            "URL contains uppercase characters, which can cause duplicate-content "
            "and crawl inconsistencies."
        )
    return _pass("URL has no uppercase characters in the path/query.")


def check_underscore_in_url(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    tech = page.technical
    has_underscore = (
        tech.url_has_underscore
        if tech is not None
        else ("_" in urlparse(page.url).path)
    )
    if has_underscore:
        return _fail(
            "URL path uses underscores; hyphens are preferred for readability and SEO."
        )
    return _pass("URL path does not use underscores.")


def check_excessive_url_length(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    tech = page.technical
    length = tech.url_length if tech is not None else len(page.url)
    if length > EXCESSIVE_URL_LENGTH:
        return _fail(f"URL is {length} characters long (threshold {EXCESSIVE_URL_LENGTH}).")
    return _pass(f"URL length is within {EXCESSIVE_URL_LENGTH} characters.")


def check_unnecessary_url_parameters(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    if not page.is_indexable:
        return _pass("Page is non-indexable; tracking-parameter check not applicable.")
    if page.status_code is not None and page.status_code >= 400:
        return _pass("Broken page; tracking-parameter check not applicable.")
    params = _tracking_params_present(page.url)
    if params:
        return _fail(
            "Indexable page URL includes tracking/session parameters: "
            + ", ".join(sorted(params))
            + "."
        )
    return _pass("No unnecessary tracking/session parameters in the URL.")


def check_redirect_chain(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    if page.redirect_hops >= 3:
        return _fail(
            f"Page required {page.redirect_hops} redirects before resolving."
        )
    return _pass("Redirect chain is within acceptable length.")


def check_temp_redirect_should_be_permanent(
    page: PageSnapshot, _: CrawlPageIndex
) -> CheckOutcome:
    pairs = _redirect_hop_pairs(page)
    temp = [
        (src, dst)
        for src, dst, status in pairs
        if status == 302 and normalize_url(src) != normalize_url(dst)
    ]
    if not temp:
        return _pass("No temporary (302) redirects in this page's redirect chain.")
    examples = ", ".join(f"{src} → {dst}" for src, dst in temp[:3])
    return _fail(
        "Temporary (302) redirect(s) in chain; consider permanent (301) if the "
        f"move is lasting: {examples}."
    )


def check_render_blocking_resources(
    page: PageSnapshot, _: CrawlPageIndex
) -> CheckOutcome:
    tech = page.technical
    if tech is None:
        return _pass("No technical resource signals available.")
    blocking_scripts = tech.render_blocking_scripts_in_head or 0
    stylesheets = tech.stylesheets_in_head or 0
    if blocking_scripts <= 0 and stylesheets <= MAX_BLOCKING_STYLESHEETS:
        return _pass("No excessive render-blocking resources in <head>.")
    parts: list[str] = []
    if blocking_scripts > 0:
        parts.append(
            f"{blocking_scripts} render-blocking script(s) in <head> without async/defer"
        )
    if stylesheets > MAX_BLOCKING_STYLESHEETS:
        parts.append(
            f"{stylesheets} stylesheet(s) in <head> (threshold {MAX_BLOCKING_STYLESHEETS})"
        )
    return _fail("; ".join(parts) + ".")


def check_large_page_weight(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    weight = page.technical.total_page_weight_bytes if page.technical else None
    if weight is None:
        return _pass("Page weight was not measured.")
    if weight <= LARGE_PAGE_WEIGHT_BYTES:
        return _pass(
            f"Page weight is within {LARGE_PAGE_WEIGHT_BYTES / (1024 * 1024):.0f}MB."
        )
    mb = weight / (1024 * 1024)
    return _fail(
        f"Measured page weight is {mb:.2f}MB "
        f"(threshold {LARGE_PAGE_WEIGHT_BYTES / (1024 * 1024):.0f}MB)."
    )


def check_oversized_images(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    oversized: list[str] = []
    for image in _iter_images(page):
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
        return _pass("No oversized images detected.")
    sample = "; ".join(oversized[:3])
    extra = f" (+{len(oversized) - 3} more)" if len(oversized) > 3 else ""
    return _fail(
        f"{len(oversized)} image(s) exceed {OVERSIZED_IMAGE_BYTES // 1024}KB "
        f"(consider resizing/compression): {sample}{extra}."
    )


def check_missing_image_dimensions(
    page: PageSnapshot, _: CrawlPageIndex
) -> CheckOutcome:
    missing = [
        str(image.get("src") or "image")
        for image in _iter_images(page)
        if not image.get("has_width") or not image.get("has_height")
    ]
    if not missing:
        return _pass("Images declare width/height attributes where measured.")
    sample = ", ".join(missing[:3])
    extra = f" (+{len(missing) - 3} more)" if len(missing) > 3 else ""
    return _fail(
        f"{len(missing)} <img> tag(s) missing width and/or height attributes "
        f"(can cause layout shift): {sample}{extra}."
    )


def check_outdated_image_format(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    outdated = [
        f"{image.get('src')} (.{image.get('file_extension')})"
        for image in _iter_images(page)
        if str(image.get("file_extension") or "").lower() in OUTDATED_IMAGE_EXTENSIONS
    ]
    if not outdated:
        return _pass("No jpg/png images flagged for modern format conversion.")
    sample = ", ".join(outdated[:3])
    extra = f" (+{len(outdated) - 3} more)" if len(outdated) > 3 else ""
    return _fail(
        f"{len(outdated)} image(s) use jpg/png; consider WebP/AVIF where supported: "
        f"{sample}{extra}."
    )


def check_missing_og_tags(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    tech = page.technical
    if tech is None:
        return _pass("No Open Graph signals captured.")
    missing = []
    if not (tech.og_title or "").strip():
        missing.append("og:title")
    if not (tech.og_description or "").strip():
        missing.append("og:description")
    if not (tech.og_image or "").strip():
        missing.append("og:image")
    if not missing:
        return _pass("Open Graph tags are present.")
    return _fail(f"Missing Open Graph tag(s): {', '.join(missing)}.")


def check_missing_twitter_card(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    tech = page.technical
    if tech is None:
        return _pass("No Twitter card signals captured.")
    if (tech.twitter_card or "").strip() and (tech.twitter_title or "").strip():
        return _pass("Twitter card tags are present.")
    missing = []
    if not (tech.twitter_card or "").strip():
        missing.append("twitter:card")
    if not (tech.twitter_title or "").strip():
        missing.append("twitter:title")
    return _fail(f"Missing Twitter card tag(s): {', '.join(missing)}.")


def check_missing_html_lang(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    tech = page.technical
    if tech is None:
        return _pass("No html lang signal captured.")
    if (tech.html_lang or "").strip():
        return _pass("The <html> tag declares a lang attribute.")
    return _fail("The <html> tag is missing a lang attribute.")


def check_thin_content(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    words = page.word_count or 0
    if words < THIN_CONTENT_WORDS:
        return _fail(f"Page has only {words} visible words.")
    return _pass(f"Page has {words} visible words.")


def check_missing_schema(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    if page.has_schema:
        return _pass("JSON-LD schema is present.")
    haystack = " ".join(filter(None, [page.url, page.title, page.h1])).lower()
    likely = any(
        token in haystack
        for token in (
            "product",
            "service",
            "blog",
            "article",
            "faq",
            "recipe",
            "event",
            "job",
            "news",
        )
    )
    if likely:
        return _fail(
            "Page looks like a rich-result candidate but no JSON-LD schema was found."
        )
    return _pass("No strong rich-result schema expectation for this page.")


def check_schema_invalid(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    tech = page.technical
    if tech is None or not isinstance(tech.schema_json, list) or not tech.schema_json:
        return _pass("No schema blocks to validate.")
    problems = validate_schema_blocks(tech.schema_json)
    if not problems:
        return _pass("JSON-LD schema blocks look valid.")
    detail = " ".join(problems[:3]) + (
        f" (+{len(problems) - 3} more)." if len(problems) > 3 else ""
    )
    return _fail(detail)


def check_mixed_content(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    if page.url.startswith("https://") and page.html.has_mixed_content:
        return _fail("HTTPS page loads one or more HTTP resources.")
    return _pass("No mixed content detected.")


def check_answer_first_heuristic(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    if not page.is_indexable:
        return _pass("Non-indexable page; answer-first check not applicable.")
    if page.status_code is not None and page.status_code >= 400:
        return _pass("Broken page; answer-first check not applicable.")
    result = page.html.answer_first
    if result is None:
        return _pass("Answer-first heuristic not evaluable (no stored HTML/H1).")
    word_count, reason = result
    if word_count >= ANSWER_FIRST_MIN_WORDS:
        return _pass("Opening content appears answer-first.")
    return _fail(
        "Content may bury the answer: "
        f"{reason} (first meaningful paragraph has {word_count} words; "
        f"aim for {ANSWER_FIRST_MIN_WORDS}+ before the first H2)."
    )


def check_poor_content_structure(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    words = page.word_count or 0
    if words > LONG_FORM_WORD_COUNT and page.html.h2_count == 0 and page.html.h3_count == 0:
        return _fail(f"Long-form page ({words} words) has no H2/H3 subheadings.")
    return _pass("Heading structure is adequate for page length.")


def check_excessive_requests(page: PageSnapshot, _: CrawlPageIndex) -> CheckOutcome:
    count = page.technical.resource_request_count if page.technical else None
    if count is None:
        return _pass("Resource request count was not measured.")
    if count <= EXCESSIVE_RESOURCE_REQUESTS:
        return _pass(f"Resource request count ({count}) is within threshold.")
    return _fail(
        f"Page references about {count} resources "
        f"(threshold {EXCESSIVE_RESOURCE_REQUESTS})."
    )


STATIC_CHECK_HANDLERS: dict[str, PageCheckFn] = {
    "missing_title": check_missing_title,
    "missing_meta_description": check_missing_meta_description,
    "missing_h1": check_missing_h1,
    "multiple_h1": check_multiple_h1,
    "canonical_noindex_conflict": check_canonical_noindex_conflict,
    "broken_link": check_broken_link,
    "uppercase_url": check_uppercase_url,
    "underscore_in_url": check_underscore_in_url,
    "excessive_url_length": check_excessive_url_length,
    "unnecessary_url_parameters": check_unnecessary_url_parameters,
    "redirect_chain": check_redirect_chain,
    "temp_redirect_should_be_permanent": check_temp_redirect_should_be_permanent,
    "render_blocking_resources": check_render_blocking_resources,
    "large_page_weight": check_large_page_weight,
    "oversized_images": check_oversized_images,
    "missing_image_dimensions": check_missing_image_dimensions,
    "outdated_image_format": check_outdated_image_format,
    "missing_og_tags": check_missing_og_tags,
    "missing_twitter_card": check_missing_twitter_card,
    "missing_html_lang": check_missing_html_lang,
    "thin_content": check_thin_content,
    "missing_schema": check_missing_schema,
    "schema_invalid": check_schema_invalid,
    "mixed_content": check_mixed_content,
    "answer_first_heuristic": check_answer_first_heuristic,
    "poor_content_structure": check_poor_content_structure,
    "excessive_requests": check_excessive_requests,
}


def _iter_images(page: PageSnapshot) -> list[dict[str, Any]]:
    tech = page.technical
    if tech is None or not isinstance(tech.images_json, list):
        return []
    return [image for image in tech.images_json if isinstance(image, dict)]


def _tracking_params_present(url: str) -> set[str]:
    query = parse_qs(urlparse(url).query, keep_blank_values=True)
    found: set[str] = set()
    for key in query:
        lowered = key.lower()
        if lowered in TRACKING_QUERY_PARAMS or lowered.startswith("utm_"):
            found.add(lowered)
    return found


def _url_has_uppercase(url: str) -> bool:
    parsed = urlparse(url)
    path_and_query = f"{parsed.path or ''}{('?' + parsed.query) if parsed.query else ''}"
    return any(ch.isupper() for ch in path_and_query)


def _redirect_hop_pairs(page: PageSnapshot) -> list[tuple[str, str, int | None]]:
    tech = page.technical
    hops: list[dict[str, Any]] = []
    if tech and isinstance(tech.redirect_chain_json, list):
        hops = [
            hop
            for hop in tech.redirect_chain_json
            if isinstance(hop, dict) and hop.get("url")
        ]
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
            destination = page.url
        pairs.append((source, destination, status_code))
    return pairs


# ---------------------------------------------------------------------------
# PageSpeed Insights
# ---------------------------------------------------------------------------


class _PagespeedRateLimiter:
    def __init__(self, delay: float) -> None:
        self._delay = delay
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait_time = self._next_at - now
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self._next_at = time.monotonic() + self._delay


def _cwv_rating(metric_key: str, value: float) -> str:
    good_max, ni_max = CWV_THRESHOLDS[metric_key]
    if value <= good_max:
        return "good"
    if value <= ni_max:
        return "needs_improvement"
    return "poor"


def _cwv_severity(check_name: str, rating: str) -> str:
    if rating == "good":
        return severity_default_for(check_name) or "low"
    if rating == "needs_improvement":
        return "medium"
    return severity_default_for(check_name) or "high"


def _parse_pagespeed_payload(payload: dict[str, Any]) -> PagespeedMetrics:
    lighthouse = payload.get("lighthouseResult") or {}
    audits = lighthouse.get("audits") or {}

    lcp = _audit_numeric(audits.get("largest-contentful-paint"))
    cls = _audit_numeric(audits.get("cumulative-layout-shift"))
    ttfb = _audit_numeric(audits.get("server-response-time"))

    inp = _audit_numeric(audits.get("interaction-to-next-paint"))
    inp_source = "inp"
    if inp is None:
        inp = _audit_numeric(audits.get("total-blocking-time"))
        inp_source = "tbt" if inp is not None else "missing"

    return PagespeedMetrics(
        lcp_ms=lcp,
        cls=cls,
        inp_ms=inp,
        inp_source=inp_source,
        ttfb_ms=ttfb,
        raw=payload,
    )


def _audit_numeric(audit: Any) -> float | None:
    if not isinstance(audit, dict):
        return None
    value = audit.get("numericValue")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def evaluate_pagespeed_checks(
    metrics: PagespeedMetrics | None,
    *,
    skipped_reason: str | None = None,
) -> list[tuple[str, CheckOutcome]]:
    """Return outcomes for the four CWV PAGE checks (success / skipped paths)."""
    if skipped_reason or metrics is None:
        reason = skipped_reason or "PageSpeed metrics unavailable."
        return [
            (name, _pass(reason))
            for name in ("lcp_fail", "cls_fail", "inp_fail", "slow_ttfb")
        ]

    results: list[tuple[str, CheckOutcome]] = []

    results.append(
        (
            "lcp_fail",
            _metric_outcome(
                "lcp_fail",
                "lcp_ms",
                metrics.lcp_ms,
                label="LCP",
                unit="ms",
                fmt="{value:.0f}",
            ),
        )
    )
    results.append(
        (
            "cls_fail",
            _metric_outcome(
                "cls_fail",
                "cls",
                metrics.cls,
                label="CLS",
                unit="",
                fmt="{value:.2f}",
            ),
        )
    )
    inp_label = "INP" if metrics.inp_source == "inp" else "INP (via TBT)"
    results.append(
        (
            "inp_fail",
            _metric_outcome(
                "inp_fail",
                "inp_ms",
                metrics.inp_ms,
                label=inp_label,
                unit="ms",
                fmt="{value:.0f}",
            ),
        )
    )
    results.append(
        (
            "slow_ttfb",
            _metric_outcome(
                "slow_ttfb",
                "ttfb_ms",
                metrics.ttfb_ms,
                label="TTFB",
                unit="ms",
                fmt="{value:.0f}",
            ),
        )
    )
    return results


def _metric_outcome(
    check_name: str,
    metric_key: str,
    value: float | None,
    *,
    label: str,
    unit: str,
    fmt: str,
) -> CheckOutcome:
    if value is None:
        return _fail(f"{label} was not reported by PageSpeed Insights.")
    rating = _cwv_rating(metric_key, value)
    severity = _cwv_severity(check_name, rating)
    rendered = fmt.format(value=value) + (unit if unit else "")
    good_max, ni_max = CWV_THRESHOLDS[metric_key]
    if rating == "good":
        return _pass(
            f"{label} is {rendered} (good; <= {fmt.format(value=good_max)}{unit}).",
            severity=severity,
        )
    if rating == "needs_improvement":
        return _fail(
            f"{label} is {rendered} (needs improvement; "
            f"good <= {fmt.format(value=good_max)}{unit}, "
            f"poor > {fmt.format(value=ni_max)}{unit}).",
            severity=severity,
        )
    return _fail(
        f"{label} is {rendered} (poor; > {fmt.format(value=ni_max)}{unit}).",
        severity=severity,
    )


async def _fetch_pagespeed_raw(
    client: httpx.AsyncClient,
    url: str,
    *,
    strategy: str,
    api_key: str,
    limiter: _PagespeedRateLimiter,
) -> dict[str, Any]:
    params: dict[str, str] = {
        "url": url,
        "strategy": strategy,
        "category": "performance",
        "key": api_key,
    }
    backoff = settings.ENRICHMENT_PAGESPEED_REQUEST_DELAY
    last_error: Exception | None = None
    for attempt in range(settings.ENRICHMENT_PAGESPEED_MAX_RETRIES):
        await limiter.wait()
        try:
            response = await client.get(PAGESPEED_ENDPOINT, params=params)
            if response.status_code == 429:
                await asyncio.sleep(backoff * (attempt + 1))
                continue
            if response.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"PageSpeed HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("PageSpeed response was not a JSON object.")
            return payload
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            last_error = exc
            if attempt == settings.ENRICHMENT_PAGESPEED_MAX_RETRIES - 1:
                break
            await asyncio.sleep(backoff * (attempt + 1))
    raise RuntimeError(str(last_error) if last_error else "PageSpeed request failed")


async def collect_pagespeed_for_pages(
    pages: list[PageSnapshot],
    *,
    enable_pagespeed: bool,
    strategy: str = "mobile",
    client: httpx.AsyncClient | None = None,
    session_factory: Callable[[], Session] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[int, tuple[PagespeedMetrics | None, str | None, str | None]]:
    """Return page_id → (metrics | None, error | None, skipped_reason | None).

    Uses crawl_pages.pagespeed_raw when present; otherwise calls the API (rate-
    limited) and persists the raw JSON back onto the row.
    """
    results: dict[int, tuple[PagespeedMetrics | None, str | None, str | None]] = {}
    api_key = settings.PAGESPEED_API_KEY
    total = len(pages)
    done = 0
    progress_lock = asyncio.Lock()

    async def _bump() -> None:
        nonlocal done
        async with progress_lock:
            done += 1
            current = done
        if progress_callback is None:
            return
        # Throttle DB writes; always emit first + last.
        if current != 1 and current != total and current % 5 != 0:
            return
        try:
            await asyncio.to_thread(progress_callback, current, total)
        except Exception:  # noqa: BLE001 — progress must not break enrichment
            logger.debug("PageSpeed progress callback failed", exc_info=True)

    need_fetch: list[PageSnapshot] = []
    for page in pages:
        if page.pagespeed_raw:
            try:
                metrics = _parse_pagespeed_payload(page.pagespeed_raw)
                results[page.id] = (metrics, None, None)
            except Exception as exc:  # noqa: BLE001 — corrupt cache → refetch
                logger.warning(
                    "Invalid pagespeed_raw cache for page %s (%s); will refetch.",
                    page.id,
                    exc,
                )
                need_fetch.append(page)
                continue
            await _bump()
            continue

        if not enable_pagespeed:
            results[page.id] = (None, None, "PageSpeed not enabled for this run.")
            await _bump()
            continue
        if not api_key:
            results[page.id] = (
                None,
                None,
                "PageSpeed skipped: PAGESPEED_API_KEY is not configured.",
            )
            await _bump()
            continue
        if page.status_code is not None and page.status_code >= 400:
            results[page.id] = (
                None,
                None,
                "PageSpeed skipped: page returned an error status.",
            )
            await _bump()
            continue
        need_fetch.append(page)

    if not need_fetch:
        return results

    owns_client = client is None
    http = client or httpx.AsyncClient(
        headers={"User-Agent": settings.CRAWLER_USER_AGENT},
        timeout=PAGESPEED_TIMEOUT,
        follow_redirects=True,
    )
    limiter = _PagespeedRateLimiter(settings.ENRICHMENT_PAGESPEED_REQUEST_DELAY)
    semaphore = asyncio.Semaphore(PAGESPEED_MAX_CONCURRENT)
    factory = session_factory or SessionLocal
    cache_writes: list[tuple[int, dict[str, Any]]] = []

    async def fetch_one(page: PageSnapshot) -> None:
        assert api_key is not None
        async with semaphore:
            try:
                raw = await _fetch_pagespeed_raw(
                    http,
                    page.url,
                    strategy=strategy,
                    api_key=api_key,
                    limiter=limiter,
                )
                metrics = _parse_pagespeed_payload(raw)
                results[page.id] = (metrics, None, None)
                cache_writes.append((page.id, raw))
                page.pagespeed_raw = raw
            except Exception as exc:  # noqa: BLE001 — per-URL isolation
                logger.warning(
                    "PageSpeed check failed for %s: %s", page.url, exc
                )
                results[page.id] = (None, str(exc) or "PageSpeed check failed", None)
            finally:
                await _bump()

    try:
        await asyncio.gather(*(fetch_one(page) for page in need_fetch))
    finally:
        if owns_client:
            await http.aclose()

    if cache_writes:
        with factory() as db:
            for page_id, raw in cache_writes:
                row = db.get(CrawlPage, page_id)
                if row is not None:
                    row.pagespeed_raw = raw
            db.commit()

    return results


# ---------------------------------------------------------------------------
# Evaluate + persist
# ---------------------------------------------------------------------------


def evaluate_static_checks(
    page: PageSnapshot,
    index: CrawlPageIndex,
) -> list[PageCheckWrite]:
    writes: list[PageCheckWrite] = []
    for entry in checks_for_scope(Scope.PAGE):
        if entry.name in PAGESPEED_CHECK_NAMES:
            continue
        handler = STATIC_CHECK_HANDLERS.get(entry.name)
        if handler is None:
            logger.warning(
                "No page_runner handler for PAGE check '%s'; skipping.", entry.name
            )
            continue
        outcome = handler(page, index)
        writes.append(
            PageCheckWrite(
                url=page.url,
                check_name=entry.name,
                status=outcome.status,
                details=outcome.details,
                severity=outcome.severity
                or severity_default_for(entry.name)
                or entry.severity_default,
            )
        )
    return writes


def evaluate_page_checks(
    pages: list[PageSnapshot],
    pagespeed_by_id: dict[int, tuple[PagespeedMetrics | None, str | None, str | None]],
) -> list[PageCheckWrite]:
    """Run every PAGE-scoped registry check once per URL."""
    index = CrawlPageIndex(
        by_normalized_url={normalize_url(p.url): p for p in pages},
        pages=pages,
    )
    writes: list[PageCheckWrite] = []
    for page in pages:
        writes.extend(evaluate_static_checks(page, index))

        metrics, error, skipped = pagespeed_by_id.get(page.id, (None, None, None))
        if error:
            # One row per failed URL — do not abort the runner or fan out 4 CWV rows.
            writes.append(
                PageCheckWrite(
                    url=page.url,
                    check_name=PAGESPEED_FAILED_CHECK,
                    status="fail",
                    details=f"PageSpeed check failed: {error}",
                    severity="high",
                )
            )
            continue

        for check_name, outcome in evaluate_pagespeed_checks(
            metrics, skipped_reason=skipped
        ):
            writes.append(
                PageCheckWrite(
                    url=page.url,
                    check_name=check_name,
                    status=outcome.status,
                    details=outcome.details,
                    severity=outcome.severity
                    or severity_default_for(check_name)
                    or "high",
                )
            )
    return writes


def persist_page_issues(
    crawl_id: int,
    writes: list[PageCheckWrite],
    *,
    session_factory: Callable[[], Session] | None = None,
) -> int:
    """Replace PAGE-scoped page_issues for this crawl (one row per check per URL)."""
    page_check_names = {entry.name for entry in checks_for_scope(Scope.PAGE)}
    page_check_names.add(PAGESPEED_FAILED_CHECK)
    factory = session_factory or SessionLocal
    with factory() as db:
        db.execute(
            delete(PageIssue).where(
                PageIssue.crawl_id == crawl_id,
                PageIssue.check_name.in_(page_check_names),
            )
        )
        for row in writes:
            db.add(
                PageIssue(
                    crawl_id=crawl_id,
                    url=row.url,
                    check_name=row.check_name,
                    status=row.status,
                    details=row.details,
                    severity=row.severity,
                )
            )
        db.commit()
    return len(writes)


async def run_page_checks(
    crawl_id: int,
    *,
    enable_pagespeed: bool | None = None,
    strategy: str = "mobile",
    client: httpx.AsyncClient | None = None,
    session_factory: Callable[[], Session] | None = None,
    phase_progress: Callable[[str, int, int | None], None] | None = None,
) -> list[PageCheckWrite]:
    """Load crawl_pages, run PAGE checks, persist page_issues.

    Never fetches robots.txt / sitemap.xml / llms.txt and never re-crawls pages.
    PageSpeed uses strategy=mobile by default; pass strategy='desktop' (or call
    twice) only when both strategies are desired.
    """
    factory = session_factory or SessionLocal
    pages = await asyncio.to_thread(load_page_snapshots, crawl_id, session_factory=factory)
    if not pages:
        return []

    run_ps = settings.ENABLE_PAGESPEED if enable_pagespeed is None else enable_pagespeed

    def _ps_progress(current: int, total: int) -> None:
        if phase_progress is not None:
            phase_progress("pagespeed" if run_ps else "page_checks", current, total)

    if phase_progress is not None:
        await asyncio.to_thread(
            phase_progress, "pagespeed" if run_ps else "page_checks", 0, len(pages)
        )

    pagespeed_by_id = await collect_pagespeed_for_pages(
        pages,
        enable_pagespeed=run_ps,
        strategy=strategy,
        client=client,
        session_factory=factory,
        progress_callback=_ps_progress,
    )
    if phase_progress is not None:
        await asyncio.to_thread(phase_progress, "page_checks", 0, len(pages))
    # CPU-bound BeautifulSoup / check evaluation must not block the API event loop.
    writes = await asyncio.to_thread(evaluate_page_checks, pages, pagespeed_by_id)
    await asyncio.to_thread(persist_page_issues, crawl_id, writes, session_factory=factory)
    if phase_progress is not None:
        await asyncio.to_thread(phase_progress, "page_checks", len(pages), len(pages))
    return writes
