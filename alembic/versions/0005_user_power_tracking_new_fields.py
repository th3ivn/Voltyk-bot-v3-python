"""Add last_ping_error_at, bot_power_message_id, ch_power_message_id, power_message_type to user_power_tracking

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_power_tracking",
        sa.Column("last_ping_error_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_power_tracking",
        sa.Column("bot_power_message_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "user_power_tracking",
        sa.Column("ch_power_message_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "user_power_tracking",
        sa.Column("power_message_type", sa.String(16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_power_tracking", "power_message_type")
    op.drop_column("user_power_tracking", "ch_power_message_id")
    op.drop_column("user_power_tracking", "bot_power_message_id")
    op.drop_column("user_power_tracking", "last_ping_error_at")
