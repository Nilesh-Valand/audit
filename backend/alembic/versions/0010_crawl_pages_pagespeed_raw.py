"""Add pagespeed_raw cache column on crawl_pages.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-05

Caches the raw PageSpeed Insights JSON response per crawled URL so report
re-generation does not re-hit the API for the same crawl.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if "crawl_pages" in inspect(op.get_bind()).get_table_names():
        if "pagespeed_raw" not in _columns("crawl_pages"):
            op.add_column("crawl_pages", sa.Column("pagespeed_raw", sa.JSON(), nullable=True))


def downgrade() -> None:
    if "crawl_pages" in inspect(op.get_bind()).get_table_names():
        if "pagespeed_raw" in _columns("crawl_pages"):
            op.drop_column("crawl_pages", "pagespeed_raw")
