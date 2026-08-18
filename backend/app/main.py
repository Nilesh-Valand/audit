import asyncio
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Windows + Playwright needs ProactorEventLoop for subprocess support.
# Playwright is optional; the crawler continues with httpx if it fails.
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from app.config import settings
from app.db.database import init_db
from app.api.crawl_runs import router as crawl_runs_router
from app.api.health import router as health_router
from app.api.page_html import router as page_html_router
from app.api.projects import router as projects_router

init_db()

app = FastAPI(title="SEO Audit API", version="0.1.0")


class ChromeExtensionCorsMiddleware(BaseHTTPMiddleware):
    """In development, reflect chrome-extension:// origins so unpacked IDs work
    before ALLOWED_ORIGINS is set. Prefer an explicit chrome-extension://<id>
    in ALLOWED_ORIGINS once the extension ID is known.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        origin = request.headers.get("origin", "")
        is_extension = origin.startswith("chrome-extension://")
        allow = is_extension and settings.ENV == "development"

        if request.method == "OPTIONS" and allow:
            return Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": request.headers.get(
                        "access-control-request-headers", "*"
                    ),
                    "Access-Control-Allow-Credentials": "true",
                },
            )

        response = await call_next(request)
        if allow:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
        return response


if settings.ENV == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    cors_origins = settings.allowed_origins or [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Always reflect chrome-extension:// origins in development so unpacked IDs
# keep working even when ALLOWED_ORIGINS lists a different extension ID.
if settings.ENV == "development":
    app.add_middleware(ChromeExtensionCorsMiddleware)

app.include_router(health_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(crawl_runs_router, prefix="/api")
app.include_router(page_html_router, prefix="/api")
