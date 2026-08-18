from __future__ import annotations

from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENV: str = "development"
    DB_URL: str = "sqlite:///./app/db/audit.db"
    # Comma-separated. Default allows web app on 3000 (localhost and 127.0.0.1).
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    CRAWLER_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 (SEOAuditBot/1.0)"
    )
    CRAWLER_CONCURRENCY: int = 10
    CRAWLER_REQUEST_DELAY: float = 0.05
    # Cap how long we'll honor a site's robots.txt Crawl-delay directive. Some
    # sites specify large values (10s+) that would make big-page-count audits
    # impractically slow; we still throttle, just not by an unbounded amount.
    CRAWLER_MAX_CRAWL_DELAY: float = 2.0
    CRAWLER_FLUSH_SIZE: int = 1
    CRAWLER_FLUSH_INTERVAL: float = 0.5
    CRAWLER_THIN_CONTENT_THRESHOLD: int = 200
    ENABLE_PAGESPEED: bool = False
    ENRICHMENT_PAGESPEED_SAMPLE_LIMIT: int = 25
    ENRICHMENT_PAGESPEED_BATCH_SIZE: int = 2
    ENRICHMENT_PAGESPEED_REQUEST_DELAY: float = 1.0
    ENRICHMENT_PAGESPEED_MAX_RETRIES: int = 3
    PAGESPEED_API_KEY: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def allowed_origins(self) -> list[str]:
        return [part.strip() for part in self.ALLOWED_ORIGINS.split(",") if part.strip()]

    @field_validator("PAGESPEED_API_KEY", mode="before")
    @classmethod
    def empty_str_to_none(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value


settings = Settings()
