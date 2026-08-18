from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from app.crawler.normalize import normalize_url

WHITESPACE_RE = re.compile(r"\s+")
_NON_FETCHABLE_SCHEMES = frozenset(
    {"data", "blob", "javascript", "mailto", "tel", "about", "file"}
)


def is_http_url(url: str | None) -> bool:
    """True only for absolute http(s) URLs safe to request with httpx."""
    if not url or not str(url).strip():
        return False
    parsed = urlparse(str(url).strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _looks_like_data_uri(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith("data:") or ";base64," in lowered


def _absolute_resource_url(page_url: str, raw: str | None) -> str | None:
    """Resolve a resource URL; keep data: URIs, drop other non-http schemes."""
    if not raw:
        return None
    src = str(raw).strip()
    if not src:
        return None
    if _looks_like_data_uri(src):
        # Keep original data URI — never urljoin (can mangle scheme-less leftovers).
        if src.lower().startswith("data:"):
            return src
        return f"data:{src.lstrip('/')}" if src.lstrip("/").lower().startswith("image/") else None
    absolute = urljoin(page_url, src)
    parsed = urlparse(absolute)
    if parsed.scheme in _NON_FETCHABLE_SCHEMES:
        return None
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return absolute
    return None


@dataclass(slots=True)
class ExtractedLink:
    target_url: str
    is_internal: bool
    anchor_text: str | None


@dataclass(slots=True)
class ExtractedImage:
    src: str
    alt: str | None
    has_width: bool = False
    has_height: bool = False
    file_extension: str | None = None
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None


@dataclass(slots=True)
class ExtractedSchemaBlock:
    raw: str
    parsed: Any | None


@dataclass(slots=True)
class RedirectHop:
    url: str
    status_code: int | None


@dataclass(slots=True)
class ExtractedPage:
    url: str
    html: str | None
    status_code: int | None
    response_time_ms: float | None
    title: str | None
    meta_description: str | None
    canonical_url: str | None
    meta_robots: str | None
    redirect_hops: int = 0
    headings: dict[str, list[str]] = field(default_factory=dict)
    links: list[ExtractedLink] = field(default_factory=list)
    word_count: int = 0
    is_indexable: bool = True
    has_schema: bool = False
    schema_blocks: list[ExtractedSchemaBlock] = field(default_factory=list)
    images: list[ExtractedImage] = field(default_factory=list)
    js_rendered: bool = False
    rendered_diff_significant: bool = False

    # --- Additive technical signals (Phase 3) ---
    url_has_uppercase: bool = False
    url_has_underscore: bool = False
    url_length: int = 0
    url_has_query_params: bool = False
    og_title: str | None = None
    og_description: str | None = None
    og_image: str | None = None
    twitter_card: str | None = None
    twitter_title: str | None = None
    html_lang: str | None = None
    favicon_in_html: bool = False
    favicon_present: bool | None = None
    stylesheet_urls: list[str] = field(default_factory=list)
    script_urls: list[str] = field(default_factory=list)
    render_blocking_scripts_in_head: int = 0
    stylesheets_in_head: int = 0
    html_bytes: int | None = None
    total_page_weight_bytes: int | None = None
    resource_request_count: int | None = None
    redirect_chain: list[RedirectHop] = field(default_factory=list)
    raw_url: str | None = None

    @property
    def primary_h1(self) -> str | None:
        return (self.headings.get("h1") or [None])[0]


def extract_page_data(
    *,
    url: str,
    html: str,
    status_code: int | None,
    response_time_ms: float | None,
    root_host: str,
    redirect_hops: int = 0,
    html_bytes: int | None = None,
    redirect_chain: list[RedirectHop] | None = None,
) -> ExtractedPage:
    soup = BeautifulSoup(html, "lxml")

    title = _clean_text(soup.title.string if soup.title and soup.title.string else None)
    meta_description = _get_meta_content(soup, "description")
    canonical_url = _extract_canonical(url, soup)
    meta_robots = _get_meta_content(soup, "robots")
    headings = _extract_headings(soup)
    links = _extract_links(soup, url, root_host)
    schema_blocks = _extract_schema_blocks(soup)
    images = _extract_images(soup, url)
    url_signals = _extract_url_signals(url)
    social = _extract_social_tags(soup, url)
    html_lang = _extract_html_lang(soup)
    favicon_in_html = _has_favicon_link(soup)
    render_blocking = _extract_render_blocking(soup, url)
    # Destructive: removes script/style nodes — run after other HTML parses.
    visible_text = _extract_visible_text(soup)
    word_count = len(visible_text.split()) if visible_text else 0

    measured_html_bytes = html_bytes if html_bytes is not None else len(html.encode("utf-8", errors="replace"))

    return ExtractedPage(
        url=url,
        html=html,
        status_code=status_code,
        response_time_ms=response_time_ms,
        redirect_hops=redirect_hops,
        title=title,
        meta_description=meta_description,
        canonical_url=canonical_url,
        meta_robots=meta_robots,
        headings=headings,
        links=links,
        word_count=word_count,
        is_indexable=_is_indexable(meta_robots),
        has_schema=bool(schema_blocks),
        schema_blocks=schema_blocks,
        images=images,
        url_has_uppercase=url_signals["has_uppercase"],
        url_has_underscore=url_signals["has_underscore"],
        url_length=url_signals["length"],
        url_has_query_params=url_signals["has_query_params"],
        og_title=social["og_title"],
        og_description=social["og_description"],
        og_image=social["og_image"],
        twitter_card=social["twitter_card"],
        twitter_title=social["twitter_title"],
        html_lang=html_lang,
        favicon_in_html=favicon_in_html,
        stylesheet_urls=render_blocking["stylesheet_urls"],
        script_urls=render_blocking["script_urls"],
        render_blocking_scripts_in_head=render_blocking["render_blocking_scripts_in_head"],
        stylesheets_in_head=render_blocking["stylesheets_in_head"],
        html_bytes=measured_html_bytes,
        redirect_chain=list(redirect_chain or []),
    )


def rendered_content_differs(raw_page: ExtractedPage, rendered_page: ExtractedPage) -> bool:
    raw_words = raw_page.word_count
    rendered_words = rendered_page.word_count
    if raw_words == 0:
        return rendered_words >= 100

    delta = abs(rendered_words - raw_words)
    relative_delta = delta / max(raw_words, 1)

    raw_title = raw_page.title or ""
    rendered_title = rendered_page.title or ""
    title_changed = raw_title.strip() != rendered_title.strip()

    return delta >= 100 or relative_delta >= 0.5 or title_changed


def _extract_url_signals(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    # Path + query (decoded for underscore/length checks; uppercase on raw path+query).
    path_and_query = f"{parsed.path or ''}{('?' + parsed.query) if parsed.query else ''}"
    raw_check = unquote(path_and_query)
    return {
        "has_uppercase": any(ch.isupper() for ch in path_and_query),
        "has_underscore": "_" in raw_check,
        "length": len(url),
        "has_query_params": bool(parsed.query),
    }


def _extract_social_tags(soup: BeautifulSoup, page_url: str) -> dict[str, str | None]:
    og_image_raw = _get_meta_property(soup, "og:image")
    og_image = _absolute_resource_url(page_url, og_image_raw) if og_image_raw else None
    if og_image and not is_http_url(og_image):
        og_image = None
    return {
        "og_title": _get_meta_property(soup, "og:title"),
        "og_description": _get_meta_property(soup, "og:description"),
        "og_image": og_image,
        "twitter_card": _get_meta_name_or_property(soup, "twitter:card"),
        "twitter_title": _get_meta_name_or_property(soup, "twitter:title"),
    }


def _extract_html_lang(soup: BeautifulSoup) -> str | None:
    html_tag = soup.find("html")
    if html_tag is None:
        return None
    lang = html_tag.get("lang")
    if isinstance(lang, list):
        lang = lang[0] if lang else None
    return _clean_text(lang)


def _has_favicon_link(soup: BeautifulSoup) -> bool:
    for tag in soup.find_all("link", href=True):
        rel = tag.get("rel")
        if not rel:
            continue
        rel_values = [str(item).lower() for item in (rel if isinstance(rel, list) else [rel])]
        if any(value in {"icon", "shortcut icon", "apple-touch-icon"} for value in rel_values):
            return True
        if any("icon" in value for value in rel_values):
            return True
    return False


def _extract_render_blocking(soup: BeautifulSoup, page_url: str) -> dict[str, Any]:
    head = soup.head
    stylesheet_urls: list[str] = []
    script_urls: list[str] = []
    seen_css: set[str] = set()
    seen_js: set[str] = set()
    stylesheets_in_head = 0
    render_blocking_scripts = 0

    for tag in soup.find_all("link", href=True):
        rel = tag.get("rel")
        rel_values = [str(item).lower() for item in (rel if isinstance(rel, list) else [rel or ""])]
        if "stylesheet" not in rel_values:
            continue
        absolute = _normalize_link(page_url, tag.get("href"))
        if absolute and absolute not in seen_css:
            seen_css.add(absolute)
            stylesheet_urls.append(absolute)
        if head is not None and tag.find_parent("head") is head:
            stylesheets_in_head += 1

    for tag in soup.find_all("script", src=True):
        absolute = _normalize_link(page_url, tag.get("src"))
        if absolute and absolute not in seen_js:
            seen_js.add(absolute)
            script_urls.append(absolute)

    if head is not None:
        for tag in head.find_all("script", src=True):
            if tag.has_attr("async") or tag.has_attr("defer"):
                continue
            script_type = (tag.get("type") or "").lower()
            if script_type == "module":
                continue
            render_blocking_scripts += 1

    return {
        "stylesheet_urls": stylesheet_urls,
        "script_urls": script_urls,
        "render_blocking_scripts_in_head": render_blocking_scripts,
        "stylesheets_in_head": stylesheets_in_head,
    }


def _extract_headings(soup: BeautifulSoup) -> dict[str, list[str]]:
    headings: dict[str, list[str]] = {}
    for tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        values = [_clean_text(tag.get_text(" ", strip=True)) for tag in soup.find_all(tag_name)]
        values = [value for value in values if value]
        if values:
            headings[tag_name] = values
    return headings


def _extract_links(soup: BeautifulSoup, page_url: str, root_host: str) -> list[ExtractedLink]:
    links: list[ExtractedLink] = []
    seen: set[tuple[str, bool, str | None]] = set()
    for tag in soup.find_all("a", href=True):
        absolute = _normalize_link(page_url, tag["href"])
        if not absolute:
            continue

        anchor_text = _clean_text(tag.get_text(" ", strip=True))
        is_internal = _same_domain(urlparse(absolute).hostname, root_host)
        key = (absolute, is_internal, anchor_text)
        if key in seen:
            continue
        seen.add(key)
        links.append(
            ExtractedLink(
                target_url=absolute,
                is_internal=is_internal,
                anchor_text=anchor_text or None,
            )
        )
    return links


def _extract_visible_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.extract()
    return _clean_text(soup.get_text(" ", strip=True)) or ""


def _extract_schema_blocks(soup: BeautifulSoup) -> list[ExtractedSchemaBlock]:
    blocks: list[ExtractedSchemaBlock] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text(strip=True)
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        blocks.append(ExtractedSchemaBlock(raw=raw, parsed=parsed))
    return blocks


def _extract_images(soup: BeautifulSoup, page_url: str) -> list[ExtractedImage]:
    images: list[ExtractedImage] = []
    for tag in soup.find_all("img"):
        src = tag.get("src")
        if not src:
            continue
        absolute = _absolute_resource_url(page_url, src if isinstance(src, str) else str(src))
        if not absolute:
            continue
        width = _parse_int_attr(tag.get("width"))
        height = _parse_int_attr(tag.get("height"))
        images.append(
            ExtractedImage(
                src=absolute,
                alt=_clean_text(tag.get("alt")),
                has_width=tag.has_attr("width"),
                has_height=tag.has_attr("height"),
                file_extension=_file_extension(absolute),
                width=width,
                height=height,
            )
        )
    return images


def _parse_int_attr(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    text = str(value).strip().lower().removesuffix("px")
    try:
        number = int(float(text))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _file_extension(url: str) -> str | None:
    if url.lower().startswith("data:"):
        # data:image/png;base64,... → png
        header = url.split(",", 1)[0]
        mime = header[5:].split(";")[0].strip().lower()  # after "data:"
        if "/" in mime:
            return mime.split("/", 1)[1] or None
        return None
    path = urlparse(url).path
    suffix = PurePosixPath(unquote(path)).suffix.lower().lstrip(".")
    return suffix or None


def _extract_canonical(page_url: str, soup: BeautifulSoup) -> str | None:
    tag = soup.find("link", rel=lambda value: value and "canonical" in value)
    href = tag.get("href") if tag else None
    return _normalize_link(page_url, href)


def _get_meta_content(soup: BeautifulSoup, name: str) -> str | None:
    tag = soup.find("meta", attrs={"name": lambda value: value and value.lower() == name})
    if tag is None:
        tag = soup.find("meta", attrs={"property": lambda value: value and value.lower() == name})
    return _clean_text(tag.get("content")) if tag else None


def _get_meta_property(soup: BeautifulSoup, property_name: str) -> str | None:
    tag = soup.find(
        "meta",
        attrs={"property": lambda value: value and value.lower() == property_name.lower()},
    )
    return _clean_text(tag.get("content")) if tag else None


def _get_meta_name_or_property(soup: BeautifulSoup, key: str) -> str | None:
    value = _get_meta_content(soup, key)
    if value:
        return value
    return _get_meta_property(soup, key)


def _is_indexable(meta_robots: str | None) -> bool:
    if not meta_robots:
        return True
    return "noindex" not in meta_robots.lower()


def _normalize_link(base_url: str, href: str | None) -> str | None:
    if not href:
        return None
    absolute = urljoin(base_url, href.strip())
    absolute, _ = urldefrag(absolute)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return normalize_url(parsed._replace(fragment="").geturl(), seed_url=base_url)


def _same_domain(hostname: str | None, root_host: str) -> bool:
    if not hostname:
        return False
    return _normalize_host(hostname) == _normalize_host(root_host)


def _normalize_host(hostname: str) -> str:
    return hostname.lower().removeprefix("www.")


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = WHITESPACE_RE.sub(" ", value).strip()
    return cleaned or None
