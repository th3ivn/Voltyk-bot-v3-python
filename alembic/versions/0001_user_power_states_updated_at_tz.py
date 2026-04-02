"""user_power_states: convert updated_at and last_notification_at to TIMESTAMPTZ

Revision ID: 0001
Revises:
Create Date: 2026-03-13

Without timezone awareness on `user_power_states.updated_at`, SQLAlchemy raises
a PostgreSQL error when comparing the naive TIMESTAMP column to the
timezone-aware `datetime.now(UTC)` value used in `get_recent_user_power_states`.
This prevents `_restore_user_states()` from completing on every bot restart,
leaving every user in `is_first_check=True` and suppressing all notifications.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import context, op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
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
    op.execute(
        "ALTER TABLE user_power_states "
        "ALTER COLUMN updated_at TYPE TIMESTAMPTZ "
        "USING updated_at AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE user_power_states "
        "ALTER COLUMN last_notification_at TYPE TIMESTAMPTZ "
        "USING last_notification_at AT TIME ZONE 'UTC'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE user_power_states "
        "ALTER COLUMN updated_at TYPE TIMESTAMP WITHOUT TIME ZONE "
        "USING updated_at AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE user_power_states "
        "ALTER COLUMN last_notification_at TYPE TIMESTAMP WITHOUT TIME ZONE "
        "USING last_notification_at AT TIME ZONE 'UTC'"
    )
