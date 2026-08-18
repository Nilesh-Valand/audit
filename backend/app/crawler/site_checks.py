from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from protego import Protego

AI_CRAWLER_USER_AGENTS = (
    "GPTBot",
    "PerplexityBot",
    "ClaudeBot",
    "Google-Extended",
)

SOFT_404_PATH = "/this-page-does-not-exist-12345"
MIN_REAL_404_WORDS = 20


@dataclass(slots=True)
class Soft404ProbeResult:
    url: str
    status_code: int | None
    word_count: int
    is_soft: bool
    detail: str


@dataclass(slots=True)
class SiteCheckResult:
    robots_txt_found: bool
    robots_txt_valid: bool | None
    robots_txt_ai_disallowed: list[str]
    robots_txt_raw: str | None
    llms_txt_present: bool
    soft_404: Soft404ProbeResult | None = None


def validate_robots_syntax(body: str) -> bool:
    """Lightweight robots.txt syntax check (not a full RFC validator)."""
    if not body or not body.strip():
        return True

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            return False
        directive = line.split(":", 1)[0].strip().lower()
        if not directive:
            return False
        if not re.match(r"^[a-z0-9\-]+$", directive):
            return False
    return True


def ai_agents_disallowed(robots_body: str, sample_url: str) -> list[str]:
    """Return AI crawler UAs that cannot fetch sample_url per robots.txt."""
    if not robots_body.strip():
        return []
    try:
        parser = Protego.parse(robots_body)
    except Exception:
        return []

    blocked: list[str] = []
    for agent in AI_CRAWLER_USER_AGENTS:
        try:
            allowed = parser.can_fetch(sample_url, agent)
        except Exception:
            continue
        if not allowed:
            blocked.append(agent)
    return blocked


def _visible_word_count(html: str) -> int:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.extract()
    text = " ".join(soup.get_text(" ", strip=True).split())
    return len(text.split()) if text else 0


async def probe_soft_404(client: httpx.AsyncClient, *, origin: str) -> Soft404ProbeResult:
    url = f"{origin.rstrip('/')}{SOFT_404_PATH}"
    try:
        response = await client.get(url)
    except httpx.HTTPError:
        return Soft404ProbeResult(
            url=url,
            status_code=None,
            word_count=0,
            is_soft=True,
            detail="Probe request failed; could not verify custom 404 behavior.",
        )

    content_type = response.headers.get("content-type", "").lower()
    word_count = 0
    if "html" in content_type or response.text:
        try:
            word_count = _visible_word_count(response.text)
        except Exception:
            word_count = len(response.text.split()) if response.text else 0

    status = response.status_code
    if status == 200:
        return Soft404ProbeResult(
            url=url,
            status_code=status,
            word_count=word_count,
            is_soft=True,
            detail="Broken URL returned HTTP 200 (soft 404) instead of 404/410.",
        )
    if status in {404, 410} and word_count < MIN_REAL_404_WORDS:
        return Soft404ProbeResult(
            url=url,
            status_code=status,
            word_count=word_count,
            is_soft=True,
            detail=(
                f"Broken URL returned HTTP {status} but the error page looks blank "
                f"({word_count} visible words)."
            ),
        )
    if status in {404, 410}:
        return Soft404ProbeResult(
            url=url,
            status_code=status,
            word_count=word_count,
            is_soft=False,
            detail=f"Proper HTTP {status} error page with content.",
        )
    return Soft404ProbeResult(
        url=url,
        status_code=status,
        word_count=word_count,
        is_soft=True,
        detail=f"Broken URL returned unexpected HTTP {status} (expected 404/410).",
    )


async def run_site_checks(
    client: httpx.AsyncClient,
    *,
    start_url: str,
) -> SiteCheckResult:
    parsed = urlparse(start_url)
    origin = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port and parsed.port not in {80, 443}:
        origin = f"{origin}:{parsed.port}"

    robots_url = f"{origin}/robots.txt"
    llms_url = f"{origin}/llms.txt"
    sample_url = f"{origin}/"

    robots_found = False
    robots_valid: bool | None = None
    robots_raw: str | None = None
    ai_disallowed: list[str] = []

    try:
        robots_response = await client.get(robots_url)
        if robots_response.status_code < 400:
            robots_found = True
            robots_raw = robots_response.text
            robots_valid = validate_robots_syntax(robots_raw)
            ai_disallowed = ai_agents_disallowed(robots_raw, sample_url)
        else:
            robots_found = False
            robots_valid = None
    except httpx.HTTPError:
        robots_found = False
        robots_valid = None

    llms_present = False
    try:
        llms_response = await client.get(llms_url)
        llms_present = llms_response.status_code < 400 and bool(llms_response.content)
    except httpx.HTTPError:
        llms_present = False

    soft_404 = await probe_soft_404(client, origin=origin)

    return SiteCheckResult(
        robots_txt_found=robots_found,
        robots_txt_valid=robots_valid,
        robots_txt_ai_disallowed=ai_disallowed,
        robots_txt_raw=robots_raw,
        llms_txt_present=llms_present,
        soft_404=soft_404,
    )
