from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class SiteIssue(Base):
    """Site-wide / cross-page / homepage check result.

    SITE / HOMEPAGE: one row per check per crawl (pass or fail).
    CROSS_PAGE: one row per issue found (e.g. one duplicate-title group),
    never one row per offending URL. HOMEPAGE details include the root URL.
    """

    __tablename__ = "site_issues"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    crawl_id: Mapped[int] = mapped_column(ForeignKey("crawls.id"), nullable=False, index=True)
    check_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="fail")
    details: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)

    crawl: Mapped["Crawl"] = relationship(back_populates="site_issues")  # noqa: F821
