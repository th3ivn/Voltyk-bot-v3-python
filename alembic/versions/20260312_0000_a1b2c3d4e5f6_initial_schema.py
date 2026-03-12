"""Initial schema — create all tables.

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-03-12 00:00:00.000000+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------ users
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=True),
        sa.Column("last_name", sa.String(length=128), nullable=True),
        sa.Column("region_id", sa.Integer(), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("queue", sa.String(length=8), nullable=True),
        sa.Column("is_blocked", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "bot_notifications_enabled", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column(
            "channel_notifications_enabled", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column("language", sa.String(length=8), server_default="uk", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_group_id", "users", ["group_id"])
    op.create_index("ix_users_is_blocked", "users", ["is_blocked"])
    op.create_index("ix_users_region_id", "users", ["region_id"])

    # --------------------------------------------------------------- channels
    op.create_table(
        "channels",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "owner_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_channels_is_active", "channels", ["is_active"])
    op.create_index("ix_channels_owner_id", "channels", ["owner_id"])
    op.create_index("ix_channels_region_group", "channels", ["region_id", "group_id"])

    # -------------------------------------------------------- pending_channels
    op.create_table(
        "pending_channels",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # --------------------------------------------------------- admin_routers
    op.create_table(
        "admin_routers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "admin_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("router_host", sa.String(length=256), nullable=False),
        sa.Column("router_port", sa.Integer(), server_default="80", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_status", sa.String(length=32), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # ---------------------------------------------------------------- settings
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.String(length=1024), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )

    # --------------------------------------------------------- bot_notifications
    op.create_table(
        "bot_notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bot_notifications_status", "bot_notifications", ["status"])
    op.create_index("ix_bot_notifications_user_id", "bot_notifications", ["user_id"])

    # ----------------------------------------------------- channel_notifications
    op.create_table(
        "channel_notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "channel_id",
            sa.BigInteger(),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_channel_notifications_channel_id", "channel_notifications", ["channel_id"]
    )
    op.create_index("ix_channel_notifications_status", "channel_notifications", ["status"])

    # ------------------------------------------------------------- power_history
    op.create_table(
        "power_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # --------------------------------------------------------- schedule_history
    op.create_table(
        "schedule_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("schedule_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("region_id", "group_id", "date", name="uq_schedule_region_group_date"),
    )

    # ---------------------------------------------------------- schedule_checks
    op.create_table(
        "schedule_checks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("region_id", sa.Integer(), unique=True, nullable=False),
        sa.Column("last_hash", sa.String(length=64), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("changes_detected", sa.Boolean(), server_default="false", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("region_id"),
    )

    # --------------------------------------------------------------- tickets
    op.create_table(
        "tickets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "admin_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subject", sa.String(length=256), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------ pause_logs
    op.create_table(
        "pause_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "paused_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=256), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # --------------------------------------------------------- daily_metrics
    op.create_table(
        "daily_metrics",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("total_users", sa.Integer(), server_default="0", nullable=False),
        sa.Column("active_users", sa.Integer(), server_default="0", nullable=False),
        sa.Column("new_users", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_channels", sa.Integer(), server_default="0", nullable=False),
        sa.Column("notifications_sent", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", name="uq_daily_metrics_date"),
    )


def downgrade() -> None:
    op.drop_table("daily_metrics")
    op.drop_table("pause_logs")
    op.drop_table("tickets")
    op.drop_index("ix_channel_notifications_status", table_name="channel_notifications")
    op.drop_index("ix_channel_notifications_channel_id", table_name="channel_notifications")
    op.drop_table("channel_notifications")
    op.drop_index("ix_bot_notifications_user_id", table_name="bot_notifications")
    op.drop_index("ix_bot_notifications_status", table_name="bot_notifications")
    op.drop_table("bot_notifications")
    op.drop_table("schedule_checks")
    op.drop_table("schedule_history")
    op.drop_table("power_history")
    op.drop_table("settings")
    op.drop_table("admin_routers")
    op.drop_table("pending_channels")
    op.drop_index("ix_channels_region_group", table_name="channels")
    op.drop_index("ix_channels_owner_id", table_name="channels")
    op.drop_index("ix_channels_is_active", table_name="channels")
    op.drop_table("channels")
    op.drop_index("ix_users_region_id", table_name="users")
    op.drop_index("ix_users_is_blocked", table_name="users")
    op.drop_index("ix_users_group_id", table_name="users")
    op.drop_table("users")
