from datetime import datetime
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    crawls: Mapped[list["Crawl"]] = relationship(  # noqa: F821
        back_populates="project", cascade="all, delete-orphan"
    )

    # Back-compat alias for older code paths.
    @property
    def crawl_runs(self) -> list:
        return self.crawls
