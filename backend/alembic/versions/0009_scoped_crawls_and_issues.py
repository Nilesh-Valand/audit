"""Refactor schema: crawls, crawl_pages, site_issues, page_issues

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-04

Physically separates site-wide vs page-level issues. Renames crawl_runs→crawls
and crawled_pages→crawl_pages. Adds domain on crawls and h1_list on crawl_pages.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    tables = _tables()

    # --- crawls (from crawl_runs) -------------------------------------------------
    if "crawls" not in tables and "crawl_runs" in tables:
        conn.execute(text("ALTER TABLE crawl_runs RENAME TO crawls"))
        tables = _tables()

    if "crawls" in tables and "domain" not in _columns("crawls"):
        op.add_column("crawls", sa.Column("domain", sa.String(length=255), nullable=True))
        conn.execute(
            text(
                """
                UPDATE crawls
                SET domain = (
                    SELECT projects.domain FROM projects
                    WHERE projects.id = crawls.project_id
                )
                WHERE domain IS NULL
                """
            )
        )
        conn.execute(text("UPDATE crawls SET domain = 'unknown' WHERE domain IS NULL OR domain = ''"))
        # SQLite cannot easily alter nullability; leave nullable=False enforced at ORM layer.
        # Recreate with NOT NULL if needed for purity — ORM requires domain on insert.

    # --- crawl_pages (from crawled_pages) ----------------------------------------
    if "crawl_pages" not in tables and "crawled_pages" in tables:
        conn.execute(text("ALTER TABLE crawled_pages RENAME TO crawl_pages"))
        tables = _tables()

    if "crawl_pages" in tables:
        cols = _columns("crawl_pages")
        if "crawl_id" not in cols and "crawl_run_id" in cols:
            # Rename FK column via table rebuild for SQLite.
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(
                text(
                    """
                    CREATE TABLE crawl_pages_new (
                        id INTEGER NOT NULL PRIMARY KEY,
                        crawl_id INTEGER NOT NULL,
                        url TEXT NOT NULL,
                        raw_url TEXT,
                        status_code INTEGER,
                        title TEXT,
                        meta_description TEXT,
                        canonical TEXT,
                        meta_robots VARCHAR(255),
                        h1 TEXT,
                        h1_list JSON,
                        word_count INTEGER,
                        response_time_ms FLOAT,
                        redirect_hops INTEGER NOT NULL DEFAULT 0,
                        is_indexable BOOLEAN NOT NULL DEFAULT 1,
                        has_schema BOOLEAN NOT NULL DEFAULT 0,
                        js_rendered BOOLEAN NOT NULL DEFAULT 0,
                        rendered_diff_significant BOOLEAN NOT NULL DEFAULT 0,
                        raw_html_path TEXT,
                        FOREIGN KEY(crawl_id) REFERENCES crawls (id),
                        UNIQUE (crawl_id, url)
                    )
                    """
                )
            )
            # Map old canonical_url → canonical
            has_canonical_url = "canonical_url" in cols
            canonical_src = "canonical_url" if has_canonical_url else "NULL"
            conn.execute(
                text(
                    f"""
                    INSERT INTO crawl_pages_new (
                        id, crawl_id, url, raw_url, status_code, title, meta_description,
                        canonical, meta_robots, h1, h1_list, word_count, response_time_ms,
                        redirect_hops, is_indexable, has_schema, js_rendered,
                        rendered_diff_significant, raw_html_path
                    )
                    SELECT
                        id, crawl_run_id, url, raw_url, status_code, title, meta_description,
                        {canonical_src}, meta_robots, h1,
                        CASE
                            WHEN h1 IS NOT NULL AND TRIM(h1) != '' THEN json_array(h1)
                            ELSE json_array()
                        END,
                        word_count, response_time_ms, redirect_hops, is_indexable, has_schema,
                        js_rendered, rendered_diff_significant, raw_html_path
                    FROM crawl_pages
                    """
                )
            )
            conn.execute(text("DROP TABLE crawl_pages"))
            conn.execute(text("ALTER TABLE crawl_pages_new RENAME TO crawl_pages"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_crawl_pages_crawl_id ON crawl_pages (crawl_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_crawl_pages_id ON crawl_pages (id)"))
            conn.execute(text("PRAGMA foreign_keys=ON"))
        else:
            if "h1_list" not in _columns("crawl_pages"):
                op.add_column("crawl_pages", sa.Column("h1_list", sa.JSON(), nullable=True))
                conn.execute(
                    text(
                        """
                        UPDATE crawl_pages
                        SET h1_list = CASE
                            WHEN h1 IS NOT NULL AND TRIM(h1) != '' THEN json_array(h1)
                            ELSE json_array()
                        END
                        WHERE h1_list IS NULL
                        """
                    )
                )
            if "canonical" not in _columns("crawl_pages") and "canonical_url" in _columns("crawl_pages"):
                op.add_column("crawl_pages", sa.Column("canonical", sa.Text(), nullable=True))
                conn.execute(text("UPDATE crawl_pages SET canonical = canonical_url"))

    # Retarget child FKs that still point at crawled_pages / crawl_runs
    _retarget_page_child_fks(conn)
    _retarget_crawl_child_fks(conn)

    # --- site_issues / page_issues -----------------------------------------------
    tables = _tables()
    if "site_issues" not in tables:
        op.create_table(
            "site_issues",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("crawl_id", sa.Integer(), sa.ForeignKey("crawls.id"), nullable=False),
            sa.Column("check_name", sa.String(length=100), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("details", sa.Text(), nullable=False),
            sa.Column("severity", sa.String(length=50), nullable=False),
        )
        op.create_index("ix_site_issues_crawl_id", "site_issues", ["crawl_id"])
        op.create_index("ix_site_issues_check_name", "site_issues", ["check_name"])

    if "page_issues" not in tables:
        op.create_table(
            "page_issues",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("crawl_id", sa.Integer(), sa.ForeignKey("crawls.id"), nullable=False),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("check_name", sa.String(length=100), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("details", sa.Text(), nullable=False),
            sa.Column("severity", sa.String(length=50), nullable=False),
        )
        op.create_index("ix_page_issues_crawl_id", "page_issues", ["crawl_id"])
        op.create_index("ix_page_issues_url", "page_issues", ["url"])
        op.create_index("ix_page_issues_check_name", "page_issues", ["check_name"])

    if "audit_issues" in _tables():
        # Site-wide: no page FK
        conn.execute(
            text(
                """
                INSERT INTO site_issues (crawl_id, check_name, status, details, severity)
                SELECT
                    crawl_run_id,
                    rule_id,
                    'fail',
                    message,
                    severity
                FROM audit_issues
                WHERE crawled_page_id IS NULL
                  AND crawl_run_id IS NOT NULL
                """
            )
        )
        # Page-level: resolve URL from page row or target_url
        conn.execute(
            text(
                """
                INSERT INTO page_issues (crawl_id, url, check_name, status, details, severity)
                SELECT
                    ai.crawl_run_id,
                    COALESCE(cp.url, ai.target_url, ''),
                    ai.rule_id,
                    'fail',
                    ai.message,
                    ai.severity
                FROM audit_issues ai
                LEFT JOIN crawl_pages cp ON cp.id = ai.crawled_page_id
                WHERE ai.crawled_page_id IS NOT NULL
                  AND ai.crawl_run_id IS NOT NULL
                """
            )
        )
        op.drop_table("audit_issues")


def _retarget_page_child_fks(conn) -> None:
    """Rebuild page child tables so FKs reference crawl_pages and crawl_page_id."""
    tables = set(inspect(conn).get_table_names())

    if "page_links" in tables and "crawled_page_id" in _columns("page_links"):
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(
            text(
                """
                CREATE TABLE page_links_new (
                    id INTEGER NOT NULL PRIMARY KEY,
                    crawl_page_id INTEGER NOT NULL,
                    target_url TEXT NOT NULL,
                    is_internal BOOLEAN NOT NULL DEFAULT 1,
                    anchor_text TEXT,
                    FOREIGN KEY(crawl_page_id) REFERENCES crawl_pages (id)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO page_links_new (id, crawl_page_id, target_url, is_internal, anchor_text)
                SELECT id, crawled_page_id, target_url, is_internal, anchor_text FROM page_links
                """
            )
        )
        conn.execute(text("DROP TABLE page_links"))
        conn.execute(text("ALTER TABLE page_links_new RENAME TO page_links"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_page_links_crawl_page_id ON page_links (crawl_page_id)"))
        conn.execute(text("PRAGMA foreign_keys=ON"))

    if "page_vitals" in tables and "crawled_page_id" in _columns("page_vitals"):
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(
            text(
                """
                CREATE TABLE page_vitals_new (
                    id INTEGER NOT NULL PRIMARY KEY,
                    crawl_page_id INTEGER NOT NULL,
                    lcp_ms FLOAT,
                    inp_ms FLOAT,
                    cls FLOAT,
                    performance_score INTEGER,
                    strategy VARCHAR(20) NOT NULL,
                    FOREIGN KEY(crawl_page_id) REFERENCES crawl_pages (id)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO page_vitals_new (id, crawl_page_id, lcp_ms, inp_ms, cls, performance_score, strategy)
                SELECT id, crawled_page_id, lcp_ms, inp_ms, cls, performance_score, strategy FROM page_vitals
                """
            )
        )
        conn.execute(text("DROP TABLE page_vitals"))
        conn.execute(text("ALTER TABLE page_vitals_new RENAME TO page_vitals"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_page_vitals_crawl_page_id ON page_vitals (crawl_page_id)"))
        conn.execute(text("PRAGMA foreign_keys=ON"))

    if "page_technical_details" in tables and "crawled_page_id" in _columns("page_technical_details"):
        cols = _columns("page_technical_details")
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        # Preserve all known columns
        conn.execute(
            text(
                """
                CREATE TABLE page_technical_details_new (
                    id INTEGER NOT NULL PRIMARY KEY,
                    crawl_page_id INTEGER NOT NULL UNIQUE,
                    url_has_uppercase BOOLEAN NOT NULL DEFAULT 0,
                    url_has_underscore BOOLEAN NOT NULL DEFAULT 0,
                    url_length INTEGER NOT NULL DEFAULT 0,
                    url_has_query_params BOOLEAN NOT NULL DEFAULT 0,
                    og_title TEXT,
                    og_description TEXT,
                    og_image TEXT,
                    twitter_card VARCHAR(100),
                    twitter_title TEXT,
                    html_lang VARCHAR(64),
                    favicon_present BOOLEAN NOT NULL DEFAULT 0,
                    images_json JSON,
                    schema_json JSON,
                    total_page_weight_bytes INTEGER,
                    resource_request_count INTEGER,
                    render_blocking_scripts_in_head INTEGER NOT NULL DEFAULT 0,
                    stylesheets_in_head INTEGER NOT NULL DEFAULT 0,
                    redirect_chain_json JSON,
                    FOREIGN KEY(crawl_page_id) REFERENCES crawl_pages (id) ON DELETE CASCADE
                )
                """
            )
        )
        # Build dynamic select for optional columns
        optional = {
            "schema_json": "schema_json" if "schema_json" in cols else "NULL",
            "resource_request_count": "resource_request_count" if "resource_request_count" in cols else "NULL",
            "redirect_chain_json": "redirect_chain_json" if "redirect_chain_json" in cols else "NULL",
            "stylesheets_in_head": (
                "stylesheets_in_head" if "stylesheets_in_head" in cols else "0"
            ),
        }
        conn.execute(
            text(
                f"""
                INSERT INTO page_technical_details_new (
                    id, crawl_page_id, url_has_uppercase, url_has_underscore, url_length,
                    url_has_query_params, og_title, og_description, og_image, twitter_card,
                    twitter_title, html_lang, favicon_present, images_json, schema_json,
                    total_page_weight_bytes, resource_request_count,
                    render_blocking_scripts_in_head, stylesheets_in_head, redirect_chain_json
                )
                SELECT
                    id, crawled_page_id, url_has_uppercase, url_has_underscore, url_length,
                    url_has_query_params, og_title, og_description, og_image, twitter_card,
                    twitter_title, html_lang, favicon_present, images_json, {optional['schema_json']},
                    total_page_weight_bytes, {optional['resource_request_count']},
                    render_blocking_scripts_in_head, {optional['stylesheets_in_head']},
                    {optional['redirect_chain_json']}
                FROM page_technical_details
                """
            )
        )
        conn.execute(text("DROP TABLE page_technical_details"))
        conn.execute(text("ALTER TABLE page_technical_details_new RENAME TO page_technical_details"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_page_technical_details_crawl_page_id "
                "ON page_technical_details (crawl_page_id)"
            )
        )
        conn.execute(text("PRAGMA foreign_keys=ON"))


def _retarget_crawl_child_fks(conn) -> None:
    tables = set(inspect(conn).get_table_names())

    if "crawl_run_scores" in tables and "crawl_run_id" in _columns("crawl_run_scores"):
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(
            text(
                """
                CREATE TABLE crawl_run_scores_new (
                    id INTEGER NOT NULL PRIMARY KEY,
                    crawl_id INTEGER NOT NULL,
                    category VARCHAR(100) NOT NULL,
                    score FLOAT NOT NULL,
                    FOREIGN KEY(crawl_id) REFERENCES crawls (id)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO crawl_run_scores_new (id, crawl_id, category, score)
                SELECT id, crawl_run_id, category, score FROM crawl_run_scores
                """
            )
        )
        conn.execute(text("DROP TABLE crawl_run_scores"))
        conn.execute(text("ALTER TABLE crawl_run_scores_new RENAME TO crawl_run_scores"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_crawl_run_scores_crawl_id ON crawl_run_scores (crawl_id)"))
        conn.execute(text("PRAGMA foreign_keys=ON"))

    if "sitemap_findings" in tables and "crawl_run_id" in _columns("sitemap_findings"):
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(
            text(
                """
                CREATE TABLE sitemap_findings_new (
                    id INTEGER NOT NULL PRIMARY KEY,
                    crawl_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    finding_type VARCHAR(100) NOT NULL,
                    message TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(crawl_id) REFERENCES crawls (id)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO sitemap_findings_new (id, crawl_id, url, finding_type, message, created_at)
                SELECT id, crawl_run_id, url, finding_type, message, created_at FROM sitemap_findings
                """
            )
        )
        conn.execute(text("DROP TABLE sitemap_findings"))
        conn.execute(text("ALTER TABLE sitemap_findings_new RENAME TO sitemap_findings"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sitemap_findings_crawl_id ON sitemap_findings (crawl_id)"))
        conn.execute(text("PRAGMA foreign_keys=ON"))


def downgrade() -> None:
    raise NotImplementedError("Downgrade from scoped issues schema is not supported.")
