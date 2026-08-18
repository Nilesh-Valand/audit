from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Crawl(Base):
    """One crawl job against a domain (renamed from crawl_runs)."""

    __tablename__ = "crawls"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_urls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_pages: Mapped[int | None] = mapped_column(Integer, nullable=True, default=200)

    # Live audit phase progress (read by lightweight status polls)
    phase: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phase_current: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phase_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Site-level probe results (once per crawl)
    robots_txt_found: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    robots_txt_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    robots_txt_ai_disallowed: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    robots_txt_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    llms_txt_present: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    soft_404_probe_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    soft_404_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    soft_404_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    soft_404_is_soft: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    soft_404_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="crawls")  # noqa: F821
    pages: Mapped[list["CrawlPage"]] = relationship(  # noqa: F821
        back_populates="crawl", cascade="all, delete-orphan"
    )
    scores: Mapped[list["CrawlRunScore"]] = relationship(  # noqa: F821
        back_populates="crawl", cascade="all, delete-orphan"
    )
    site_issues: Mapped[list["SiteIssue"]] = relationship(  # noqa: F821
        back_populates="crawl", cascade="all, delete-orphan"
    )
    page_issues: Mapped[list["PageIssue"]] = relationship(  # noqa: F821
        back_populates="crawl", cascade="all, delete-orphan"
    )


# Back-compat alias used while API routes still say "crawl-runs".
CrawlRun = Crawl
