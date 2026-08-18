from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urldefrag, urlparse, urlunparse

_MULTI_SLASH_RE = re.compile(r"/{2,}")

# Align with unnecessary_url_parameters / tracking noise — drop from page identity.
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


def prefer_www_from_seed(seed_url: str | None) -> bool:
    """Default www policy from the crawl start URL host."""
    if not seed_url:
        return False
    host = (urlparse(seed_url).hostname or "").lower()
    return host.startswith("www.")


def normalize_url(
    url: str,
    *,
    prefer_www: bool | None = None,
    seed_url: str | None = None,
) -> str:
    """
    Produce a canonical URL for crawl identity / storage.

    - Removes trailing slash (except root "/")
    - Lowercases scheme and host (path case preserved)
    - Removes default ports (:80 / :443)
    - Strips fragments
    - Drops tracking/session query params; sorts remaining params
    - Resolves www vs non-www using prefer_www / seed_url (default: no www)
    """
    if not url:
        return url

    if prefer_www is None:
        prefer_www = prefer_www_from_seed(seed_url)

    cleaned, _ = urldefrag(url.strip())
    parsed = urlparse(cleaned)
    scheme = (parsed.scheme or "https").lower()
    if scheme not in {"http", "https"}:
        return cleaned

    host = (parsed.hostname or "").lower()
    if not host:
        return cleaned

    bare_host = host.removeprefix("www.")
    host = f"www.{bare_host}" if prefer_www else bare_host

    port = parsed.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    else:
        netloc = host

    path = parsed.path or "/"
    path = _MULTI_SLASH_RE.sub("/", path)
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    kept_params: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in TRACKING_QUERY_PARAMS or lowered.startswith("utm_"):
            continue
        kept_params.append((key, value))
    query = urlencode(sorted(kept_params)) if kept_params else ""

    return urlunparse((scheme, netloc, path, "", query, ""))


# Back-compat alias used by older call sites.
def canonicalize_crawl_url(url: str, *, strip_www: bool = True, seed_url: str | None = None) -> str:
    if seed_url is not None:
        return normalize_url(url, seed_url=seed_url)
    return normalize_url(url, prefer_www=not strip_www)
