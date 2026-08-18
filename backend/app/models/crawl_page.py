from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CrawlPage(Base):
    """Raw crawled page data for one URL in a crawl (renamed from crawled_pages)."""

    __tablename__ = "crawl_pages"
    __table_args__ = (
        UniqueConstraint("crawl_id", "url", name="uq_crawl_pages_crawl_url"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    crawl_id: Mapped[int] = mapped_column(ForeignKey("crawls.id"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    raw_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_robots: Mapped[str | None] = mapped_column(String(255), nullable=True)
    h1: Mapped[str | None] = mapped_column(Text, nullable=True)
    h1_list: Mapped[list | None] = mapped_column(JSON, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    redirect_hops: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_indexable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    has_schema: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    js_rendered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rendered_diff_significant: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    raw_html_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    pagespeed_raw: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)

    crawl: Mapped["Crawl"] = relationship(back_populates="pages")  # noqa: F821
    links: Mapped[list["PageLink"]] = relationship(  # noqa: F821
        back_populates="crawl_page", cascade="all, delete-orphan"
    )
    page_vitals: Mapped[list["PageVital"]] = relationship(  # noqa: F821
        back_populates="crawl_page", cascade="all, delete-orphan"
    )
    technical_details: Mapped["PageTechnicalDetails | None"] = relationship(  # noqa: F821
        back_populates="crawl_page",
        cascade="all, delete-orphan",
        uselist=False,
    )

    # Convenience alias for older call sites that used canonical_url.
    @property
    def canonical_url(self) -> str | None:
        return self.canonical

    @canonical_url.setter
    def canonical_url(self, value: str | None) -> None:
        self.canonical = value


# Back-compat alias.
CrawledPage = CrawlPage
