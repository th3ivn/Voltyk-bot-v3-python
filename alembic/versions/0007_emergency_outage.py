"""Add emergency outage tables and notification fields

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-21
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import context, op


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


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if _table_exists("users") and not _table_exists("user_emergency_config"):
        op.create_table(
            "user_emergency_config",
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("city", sa.String(128), nullable=True),
            sa.Column("street", sa.String(255), nullable=True),
            sa.Column("house", sa.String(32), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if _table_exists("users") and not _table_exists("user_emergency_state"):
        op.create_table(
            "user_emergency_state",
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("status", sa.String(16), server_default="none"),
            sa.Column("start_date", sa.String(32), nullable=True),
            sa.Column("end_date", sa.String(32), nullable=True),
            sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if _table_exists("user_notification_settings"):
        op.add_column(
            "user_notification_settings",
            sa.Column("notify_emergency_off", sa.Boolean, server_default="true", nullable=False),
        )
        op.add_column(
            "user_notification_settings",
            sa.Column("notify_emergency_on", sa.Boolean, server_default="true", nullable=False),
        )


def downgrade() -> None:
    op.drop_column("user_notification_settings", "notify_emergency_on")
    op.drop_column("user_notification_settings", "notify_emergency_off")
    op.drop_table("user_emergency_state")
    op.drop_table("user_emergency_config")
