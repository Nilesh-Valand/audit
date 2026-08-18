"""add enrichment tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "page_vitals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("crawled_page_id", sa.Integer(), nullable=False),
        sa.Column("lcp_ms", sa.Float(), nullable=True),
        sa.Column("inp_ms", sa.Float(), nullable=True),
        sa.Column("cls", sa.Float(), nullable=True),
        sa.Column("performance_score", sa.Integer(), nullable=True),
        sa.Column("strategy", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["crawled_page_id"], ["crawled_pages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_page_vitals_id", "page_vitals", ["id"])
    op.create_index("ix_page_vitals_crawled_page_id", "page_vitals", ["crawled_page_id"])

    op.create_table(
        "gsc_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("indexed_page_count", sa.Integer(), nullable=True),
        sa.Column("inspected_url_count", sa.Integer(), nullable=True),
        sa.Column("sitemap_submission_status", sa.String(length=255), nullable=True),
        sa.Column("coverage_errors", sa.Integer(), nullable=True),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gsc_snapshots_id", "gsc_snapshots", ["id"])
    op.create_index("ix_gsc_snapshots_project_id", "gsc_snapshots", ["project_id"])

    op.create_table(
        "gsc_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("property_url", sa.String(length=255), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_type", sa.String(length=50), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )
    op.create_index("ix_gsc_credentials_id", "gsc_credentials", ["id"])
    op.create_index("ix_gsc_credentials_project_id", "gsc_credentials", ["project_id"])

    op.create_table(
        "sitemap_findings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("crawl_run_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("finding_type", sa.String(length=100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sitemap_findings_id", "sitemap_findings", ["id"])
    op.create_index("ix_sitemap_findings_crawl_run_id", "sitemap_findings", ["crawl_run_id"])


def downgrade() -> None:
    op.drop_table("sitemap_findings")
    op.drop_table("gsc_credentials")
    op.drop_table("gsc_snapshots")
    op.drop_table("page_vitals")
