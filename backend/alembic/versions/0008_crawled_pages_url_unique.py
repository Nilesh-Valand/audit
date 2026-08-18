"""add crawled_pages.raw_url and unique (crawl_run_id, url)

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-31

"""
from __future__ import annotations

from collections import defaultdict
from typing import Sequence, Union
from urllib.parse import parse_qsl, urlencode, urldefrag, urlparse, urlunparse
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MULTI_SLASH_RE = re.compile(r"/{2,}")
_TRACKING = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "gclid",
    "fbclid",
    "msclkid",
    "sid",
    "sessionid",
    "session_id",
    "phpsessid",
    "_ga",
    "mc_cid",
    "mc_eid",
}


def _normalize(url: str) -> str:
    if not url:
        return url
    cleaned, _ = urldefrag(url.strip())
    parsed = urlparse(cleaned)
    scheme = (parsed.scheme or "https").lower()
    if scheme not in {"http", "https"}:
        return cleaned
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host:
        return cleaned
    port = parsed.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    else:
        netloc = host
    path = parsed.path or "/"
    path = _MULTI_SLASH_RE.sub("/", path)
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    kept = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in _TRACKING or lowered.startswith("utm_"):
            continue
        kept.append((key, value))
    query = urlencode(sorted(kept)) if kept else ""
    return urlunparse((scheme, netloc, path, "", query, ""))


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    columns = _column_names("crawled_pages")
    if "raw_url" not in columns:
        op.add_column("crawled_pages", sa.Column("raw_url", sa.Text(), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(
        text("SELECT id, crawl_run_id, url FROM crawled_pages ORDER BY id ASC")
    ).fetchall()

    groups: dict[tuple[int, str], list[int]] = defaultdict(list)
    for row in rows:
        page_id, crawl_run_id, url = row[0], row[1], row[2]
        groups[(crawl_run_id, _normalize(url or ""))].append(page_id)

    delete_ids: list[int] = []
    for (_run_id, canonical), ids in groups.items():
        keep_id = ids[0]
        conn.execute(
            text("UPDATE crawled_pages SET url = :url WHERE id = :id"),
            {"url": canonical, "id": keep_id},
        )
        delete_ids.extend(ids[1:])

    if delete_ids:
        # Chunk deletes for SQLite parameter limits.
        chunk_size = 400
        for i in range(0, len(delete_ids), chunk_size):
            chunk = delete_ids[i : i + chunk_size]
            params = {f"id{j}": value for j, value in enumerate(chunk)}
            placeholders = ", ".join(f":id{j}" for j in range(len(chunk)))
            for table, column in (
                ("page_links", "crawled_page_id"),
                ("page_vitals", "crawled_page_id"),
                ("page_technical_details", "crawled_page_id"),
                ("audit_issues", "crawled_page_id"),
            ):
                conn.execute(
                    text(f"DELETE FROM {table} WHERE {column} IN ({placeholders})"),
                    params,
                )
            conn.execute(
                text(f"DELETE FROM crawled_pages WHERE id IN ({placeholders})"),
                params,
            )

        # Refresh total_urls per run.
        run_ids = {run_id for run_id, _canonical in groups}
        for run_id in run_ids:
            count = conn.execute(
                text("SELECT COUNT(*) FROM crawled_pages WHERE crawl_run_id = :run_id"),
                {"run_id": run_id},
            ).scalar()
            conn.execute(
                text("UPDATE crawl_runs SET total_urls = :count WHERE id = :run_id"),
                {"count": count or 0, "run_id": run_id},
            )

    indexes = _index_names("crawled_pages")
    if "uq_crawled_pages_run_url" not in indexes:
        op.create_index(
            "uq_crawled_pages_run_url",
            "crawled_pages",
            ["crawl_run_id", "url"],
            unique=True,
        )


def downgrade() -> None:
    indexes = _index_names("crawled_pages")
    if "uq_crawled_pages_run_url" in indexes:
        op.drop_index("uq_crawled_pages_run_url", table_name="crawled_pages")
    columns = _column_names("crawled_pages")
    if "raw_url" in columns:
        op.drop_column("crawled_pages", "raw_url")
