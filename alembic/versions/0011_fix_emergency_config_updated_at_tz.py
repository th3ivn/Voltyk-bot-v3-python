"""Fix user_emergency_config.updated_at to TIMESTAMPTZ

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-04

Revision 0007 created user_emergency_config.updated_at as a timezone-naive
TIMESTAMP, while user_emergency_state used TIMESTAMP WITH TIME ZONE for all
its datetime columns. This migration converts the column to TIMESTAMPTZ for
consistency and to prevent silent data-corruption on non-UTC servers when the
column is compared against or stored alongside TIMESTAMPTZ values.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import context, op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    """Return True if the table exists in the public schema (online mode only)."""
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
    return bool(result.scalar())


def upgrade() -> None:
    if not _table_exists("user_emergency_config"):
        return
    op.alter_column(
        "user_emergency_config",
        "updated_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
        existing_type=sa.DateTime(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "user_emergency_config",
        "updated_at",
        type_=sa.DateTime(),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=True,
    )
