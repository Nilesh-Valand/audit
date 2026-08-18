"""add soft 404 probe fields and schema_json

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    crawl_columns = _column_names("crawl_runs")
    additions = [
        ("soft_404_probe_url", sa.Column("soft_404_probe_url", sa.Text(), nullable=True)),
        ("soft_404_status_code", sa.Column("soft_404_status_code", sa.Integer(), nullable=True)),
        ("soft_404_word_count", sa.Column("soft_404_word_count", sa.Integer(), nullable=True)),
        ("soft_404_is_soft", sa.Column("soft_404_is_soft", sa.Boolean(), nullable=True)),
        ("soft_404_detail", sa.Column("soft_404_detail", sa.Text(), nullable=True)),
    ]
    for name, column in additions:
        if name not in crawl_columns:
            op.add_column("crawl_runs", column)

    tech_columns = _column_names("page_technical_details")
    if "schema_json" not in tech_columns:
        op.add_column("page_technical_details", sa.Column("schema_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    tech_columns = _column_names("page_technical_details")
    if "schema_json" in tech_columns:
        op.drop_column("page_technical_details", "schema_json")

    crawl_columns = _column_names("crawl_runs")
    for name in (
        "soft_404_detail",
        "soft_404_is_soft",
        "soft_404_word_count",
        "soft_404_status_code",
        "soft_404_probe_url",
    ):
        if name in crawl_columns:
            op.drop_column("crawl_runs", name)
