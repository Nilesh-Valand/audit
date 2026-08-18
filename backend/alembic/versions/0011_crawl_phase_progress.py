"""Add phase progress fields on crawls for live audit status polling.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-07

Stores the current audit phase and optional counters so GET /crawl-runs/{id}
can return lightweight live progress while PageSpeed / checks run in the
background.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if "crawls" not in inspect(op.get_bind()).get_table_names():
        return
    cols = _columns("crawls")
    if "phase" not in cols:
        op.add_column("crawls", sa.Column("phase", sa.String(length=50), nullable=True))
    if "phase_current" not in cols:
        op.add_column("crawls", sa.Column("phase_current", sa.Integer(), nullable=True))
    if "phase_total" not in cols:
        op.add_column("crawls", sa.Column("phase_total", sa.Integer(), nullable=True))
    if "error_message" not in cols:
        op.add_column("crawls", sa.Column("error_message", sa.Text(), nullable=True))


def downgrade() -> None:
    if "crawls" not in inspect(op.get_bind()).get_table_names():
        return
    cols = _columns("crawls")
    for name in ("error_message", "phase_total", "phase_current", "phase"):
        if name in cols:
            op.drop_column("crawls", name)
