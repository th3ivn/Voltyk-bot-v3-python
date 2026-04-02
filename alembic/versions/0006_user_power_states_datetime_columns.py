"""Convert user_power_states string columns to TIMESTAMPTZ

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-21
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import context, op

revision = "0006"
down_revision = "0005"
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
    if not _table_exists("user_power_states"):
        return
    op.execute("""
        ALTER TABLE user_power_states
            ALTER COLUMN pending_state_time
                TYPE TIMESTAMPTZ USING NULLIF(pending_state_time, '')::timestamptz,
            ALTER COLUMN last_stable_at
                TYPE TIMESTAMPTZ USING NULLIF(last_stable_at, '')::timestamptz,
            ALTER COLUMN instability_start
                TYPE TIMESTAMPTZ USING NULLIF(instability_start, '')::timestamptz
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE user_power_states
            ALTER COLUMN pending_state_time TYPE VARCHAR(64) USING pending_state_time::text,
            ALTER COLUMN last_stable_at TYPE VARCHAR(64) USING last_stable_at::text,
            ALTER COLUMN instability_start TYPE VARCHAR(64) USING instability_start::text
    """)
