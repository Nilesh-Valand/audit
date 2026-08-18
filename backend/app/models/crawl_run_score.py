from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CrawlRunScore(Base):
    __tablename__ = "crawl_run_scores"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    crawl_id: Mapped[int] = mapped_column(ForeignKey("crawls.id"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)

    crawl: Mapped["Crawl"] = relationship(back_populates="scores")  # noqa: F821
