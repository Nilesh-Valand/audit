"""add page technical details and crawl-run site checks

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    return set(inspector.get_table_names())


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    tables = _table_names()

    if "page_technical_details" not in tables:
        op.create_table(
            "page_technical_details",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("crawled_page_id", sa.Integer(), nullable=False),
            sa.Column("url_has_uppercase", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("url_has_underscore", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("url_length", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("url_has_query_params", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("og_title", sa.Text(), nullable=True),
            sa.Column("og_description", sa.Text(), nullable=True),
            sa.Column("og_image", sa.Text(), nullable=True),
            sa.Column("twitter_card", sa.String(length=100), nullable=True),
            sa.Column("twitter_title", sa.Text(), nullable=True),
            sa.Column("html_lang", sa.String(length=64), nullable=True),
            sa.Column("favicon_present", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("images_json", sa.JSON(), nullable=True),
            sa.Column("total_page_weight_bytes", sa.Integer(), nullable=True),
            sa.Column(
                "render_blocking_scripts_in_head",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("stylesheets_in_head", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("redirect_chain_json", sa.JSON(), nullable=True),
            sa.ForeignKeyConstraint(
                ["crawled_page_id"],
                ["crawled_pages.id"],
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint("crawled_page_id"),
        )
        op.create_index(
            "ix_page_technical_details_crawled_page_id",
            "page_technical_details",
            ["crawled_page_id"],
        )

    crawl_columns = _column_names("crawl_runs")
    if "robots_txt_found" not in crawl_columns:
        op.add_column("crawl_runs", sa.Column("robots_txt_found", sa.Boolean(), nullable=True))
    if "robots_txt_valid" not in crawl_columns:
        op.add_column("crawl_runs", sa.Column("robots_txt_valid", sa.Boolean(), nullable=True))
    if "robots_txt_ai_disallowed" not in crawl_columns:
        op.add_column("crawl_runs", sa.Column("robots_txt_ai_disallowed", sa.JSON(), nullable=True))
    if "robots_txt_raw" not in crawl_columns:
        op.add_column("crawl_runs", sa.Column("robots_txt_raw", sa.Text(), nullable=True))
    if "llms_txt_present" not in crawl_columns:
        op.add_column("crawl_runs", sa.Column("llms_txt_present", sa.Boolean(), nullable=True))


def downgrade() -> None:
    crawl_columns = _column_names("crawl_runs")
    for column in (
        "llms_txt_present",
        "robots_txt_raw",
        "robots_txt_ai_disallowed",
        "robots_txt_valid",
        "robots_txt_found",
    ):
        if column in crawl_columns:
            op.drop_column("crawl_runs", column)

    tables = _table_names()
    if "page_technical_details" in tables:
        op.drop_index(
            "ix_page_technical_details_crawled_page_id",
            table_name="page_technical_details",
        )
        op.drop_table("page_technical_details")
