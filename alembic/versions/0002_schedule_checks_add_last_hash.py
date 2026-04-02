"""schedule_checks: add last_hash column

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-14
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import context, op

revision = "0002"
down_revision = "0001"
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
    if not _table_exists("schedule_checks"):
        return
    op.add_column(
        "schedule_checks",
        sa.Column("last_hash", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("schedule_checks", "last_hash")
