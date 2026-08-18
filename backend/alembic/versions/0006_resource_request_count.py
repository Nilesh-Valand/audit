"""add resource_request_count to page technical details

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    columns = _column_names("page_technical_details")
    if "resource_request_count" not in columns:
        op.add_column(
            "page_technical_details",
            sa.Column("resource_request_count", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    columns = _column_names("page_technical_details")
    if "resource_request_count" in columns:
        op.drop_column("page_technical_details", "resource_request_count")
