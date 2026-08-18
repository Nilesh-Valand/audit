from sqlalchemy import Text, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class PageLink(Base):
    __tablename__ = "page_links"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    crawl_page_id: Mapped[int] = mapped_column(ForeignKey("crawl_pages.id"), nullable=False, index=True)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    anchor_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    crawl_page: Mapped["CrawlPage"] = relationship(back_populates="links")  # noqa: F821
