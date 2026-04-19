"""Make channel_branding_updated_at timezone-aware

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-19

Fixes DBAPIError when storing a timezone-aware datetime into a
TIMESTAMP WITHOUT TIME ZONE column (asyncpg raises DataError).
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import context, op

revision = "0015"
down_revision = "0014"
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
    if not _table_exists("user_channel_config"):
        return
    op.alter_column(
        "user_channel_config",
        "channel_branding_updated_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
        postgresql_using="channel_branding_updated_at AT TIME ZONE 'UTC'",
    )


def downgrade() -> None:
    if not _table_exists("user_channel_config"):
        return
    op.alter_column(
        "user_channel_config",
        "channel_branding_updated_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=True,
        postgresql_using="channel_branding_updated_at AT TIME ZONE 'UTC'",
    )
