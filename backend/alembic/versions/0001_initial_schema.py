"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-07-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_id", "projects", ["id"])
    op.create_index("ix_projects_domain", "projects", ["domain"])

    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("total_urls", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_runs_id", "crawl_runs", ["id"])
    op.create_index("ix_crawl_runs_project_id", "crawl_runs", ["project_id"])

    op.create_table(
        "crawled_pages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("crawl_run_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("meta_robots", sa.String(length=255), nullable=True),
        sa.Column("h1", sa.Text(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("response_time_ms", sa.Float(), nullable=True),
        sa.Column("is_indexable", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("has_schema", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("raw_html_path", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawled_pages_id", "crawled_pages", ["id"])
    op.create_index("ix_crawled_pages_crawl_run_id", "crawled_pages", ["crawl_run_id"])

    op.create_table(
        "page_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("crawled_page_id", sa.Integer(), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("is_internal", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("anchor_text", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["crawled_page_id"], ["crawled_pages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_page_links_id", "page_links", ["id"])
    op.create_index("ix_page_links_crawled_page_id", "page_links", ["crawled_page_id"])

    op.create_table(
        "audit_issues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("crawled_page_id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["crawled_page_id"], ["crawled_pages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_issues_id", "audit_issues", ["id"])
    op.create_index("ix_audit_issues_crawled_page_id", "audit_issues", ["crawled_page_id"])
    op.create_index("ix_audit_issues_rule_id", "audit_issues", ["rule_id"])

    op.create_table(
        "crawl_run_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("crawl_run_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_run_scores_id", "crawl_run_scores", ["id"])
    op.create_index("ix_crawl_run_scores_crawl_run_id", "crawl_run_scores", ["crawl_run_id"])


def downgrade() -> None:
    op.drop_table("crawl_run_scores")
    op.drop_table("audit_issues")
    op.drop_table("page_links")
    op.drop_table("crawled_pages")
    op.drop_table("crawl_runs")
    op.drop_table("projects")
