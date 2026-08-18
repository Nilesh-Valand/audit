"""add audit issue target url and redirect hops

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    crawled_columns = _column_names("crawled_pages")
    if "redirect_hops" not in crawled_columns:
        op.add_column(
            "crawled_pages",
            sa.Column("redirect_hops", sa.Integer(), nullable=False, server_default="0"),
        )

    audit_columns = _column_names("audit_issues")
    if "crawl_run_id" not in audit_columns:
        op.add_column(
            "audit_issues",
            sa.Column("crawl_run_id", sa.Integer(), nullable=True),
        )

    if "target_url" not in audit_columns:
        op.add_column("audit_issues", sa.Column("target_url", sa.Text(), nullable=True))

    with op.batch_alter_table("audit_issues") as batch_op:
        batch_op.alter_column("crawled_page_id", existing_type=sa.Integer(), nullable=True)

    if "ix_audit_issues_crawl_run_id" not in _index_names("audit_issues"):
        op.create_index("ix_audit_issues_crawl_run_id", "audit_issues", ["crawl_run_id"])


def downgrade() -> None:
    if "ix_audit_issues_crawl_run_id" in _index_names("audit_issues"):
        op.drop_index("ix_audit_issues_crawl_run_id", table_name="audit_issues")

    audit_columns = _column_names("audit_issues")
    if "target_url" in audit_columns:
        op.drop_column("audit_issues", "target_url")

    with op.batch_alter_table("audit_issues") as batch_op:
        batch_op.alter_column("crawled_page_id", existing_type=sa.Integer(), nullable=False)

    if "crawl_run_id" in audit_columns:
        op.drop_column("audit_issues", "crawl_run_id")

    crawled_columns = _column_names("crawled_pages")
    if "redirect_hops" in crawled_columns:
        op.drop_column("crawled_pages", "redirect_hops")
