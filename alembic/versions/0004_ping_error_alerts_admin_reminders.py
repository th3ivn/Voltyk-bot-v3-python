"""Add ping_error_alerts, admin_ticket_reminders tables; add last_power_message_id to user_channel_config

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=:t)"
        ),
        {"t": name},
    )
    return result.scalar()


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ping_error_alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.String(64), nullable=False),
        sa.Column("router_ip", sa.String(255), nullable=False),
        sa.Column("last_alert_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_id", name="uq_ping_error_alert_user"),
    )
    op.create_index("idx_ping_error_alerts_telegram_id", "ping_error_alerts", ["telegram_id"])

    op.create_table(
        "admin_ticket_reminders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("admin_telegram_id", sa.String(64), nullable=False),
        sa.Column(
            "last_reminder_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_resolved", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_admin_ticket_reminders_ticket_id", "admin_ticket_reminders", ["ticket_id"])

    if _table_exists("user_channel_config"):
        op.add_column(
            "user_channel_config",
            sa.Column("last_power_message_id", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("user_channel_config", "last_power_message_id")
    op.drop_index("idx_admin_ticket_reminders_ticket_id", table_name="admin_ticket_reminders")
    op.drop_table("admin_ticket_reminders")
    op.drop_index("idx_ping_error_alerts_telegram_id", table_name="ping_error_alerts")
    op.drop_table("ping_error_alerts")
