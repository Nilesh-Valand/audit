"""add js render flags to crawled pages

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "crawled_pages",
        sa.Column("js_rendered", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "crawled_pages",
        sa.Column(
            "rendered_diff_significant",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("crawled_pages", "rendered_diff_significant")
    op.drop_column("crawled_pages", "js_rendered")
