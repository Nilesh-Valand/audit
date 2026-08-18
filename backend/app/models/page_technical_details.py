from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class PageTechnicalDetails(Base):
    """Additive per-page technical signals captured during crawl (1:1 with crawl_pages)."""

    __tablename__ = "page_technical_details"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    crawl_page_id: Mapped[int] = mapped_column(
        ForeignKey("crawl_pages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    url_has_uppercase: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    url_has_underscore: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    url_length: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    url_has_query_params: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    og_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    og_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    og_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    twitter_card: Mapped[str | None] = mapped_column(String(100), nullable=True)
    twitter_title: Mapped[str | None] = mapped_column(Text, nullable=True)

    html_lang: Mapped[str | None] = mapped_column(String(64), nullable=True)
    favicon_present: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    images_json: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    schema_json: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    total_page_weight_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resource_request_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    render_blocking_scripts_in_head: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stylesheets_in_head: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    redirect_chain_json: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)

    crawl_page: Mapped["CrawlPage"] = relationship(  # noqa: F821
        back_populates="technical_details"
    )
