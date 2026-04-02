"""Drop legacy schedule-state columns from users table

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-24

These four columns were used in an earlier scheduler implementation to cache
per-user schedule hashes.  Schedule state is now tracked in the
``schedule_checks`` and ``schedule_daily_snapshots`` tables, so the columns
on ``users`` are dead code and can be removed.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import context, op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    if context.is_offline_mode():
        return True
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=:t)"
        ),
        {"t": name},
    )
    return result.scalar()


def upgrade() -> None:
    if not _table_exists("users"):
        return
    op.drop_column("users", "last_hash")
    op.drop_column("users", "today_snapshot_hash")
    op.drop_column("users", "tomorrow_snapshot_hash")
    op.drop_column("users", "tomorrow_published_date")


def downgrade() -> None:
    op.add_column("users", sa.Column("tomorrow_published_date", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("tomorrow_snapshot_hash", sa.String(128), nullable=True))
    op.add_column("users", sa.Column("today_snapshot_hash", sa.String(128), nullable=True))
    op.add_column("users", sa.Column("last_hash", sa.String(128), nullable=True))
