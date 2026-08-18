from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class PageIssue(Base):
    """Page-level check result — one row per check per URL per crawl."""

    __tablename__ = "page_issues"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    crawl_id: Mapped[int] = mapped_column(ForeignKey("crawls.id"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    check_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="fail")
    details: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)

    crawl: Mapped["Crawl"] = relationship(back_populates="page_issues")  # noqa: F821
