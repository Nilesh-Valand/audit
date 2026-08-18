from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/page-html", tags=["page-check"])


class PageHtmlRequest(BaseModel):
    url: str


class PageHtmlResponse(BaseModel):
    url: str
    final_url: str
    status_code: int
    content_type: str | None = None
    html: str


@router.post("", response_model=PageHtmlResponse)
async def fetch_page_html(payload: PageHtmlRequest) -> PageHtmlResponse:
    raw_url = payload.url.strip()
    if not raw_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL is required.",
        )

    if not raw_url.startswith(("http://", "https://")):
        raw_url = f"https://{raw_url}"

    headers = {
        "User-Agent": settings.CRAWLER_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Upgrade-Insecure-Requests": "1",
    }

    timeout = httpx.Timeout(25.0, connect=10.0)

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers=headers,
            verify=False,
        ) as client:
            response = await client.get(raw_url)
            html_text = response.text or ""
            content_type = response.headers.get("content-type")

            return PageHtmlResponse(
                url=raw_url,
                final_url=str(response.url),
                status_code=response.status_code,
                content_type=content_type,
                html=html_text,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch HTML for '{raw_url}': {exc}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing '{raw_url}': {exc}",
        )
