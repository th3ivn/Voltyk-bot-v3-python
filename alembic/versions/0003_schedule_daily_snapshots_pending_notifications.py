"""Add schedule_daily_snapshots, pending_notifications tables; add last_schedule_message_id

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-14
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

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_daily_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("region", sa.String(64), nullable=False),
        sa.Column("queue", sa.String(16), nullable=False),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("schedule_data", sa.Text(), nullable=False),
        sa.Column("today_hash", sa.String(128), nullable=True),
        sa.Column("tomorrow_hash", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("region", "queue", "date", name="uq_schedule_daily_snapshot"),
    )
    op.create_index(
        "idx_sds_region_queue_date",
        "schedule_daily_snapshots",
        ["region", "queue", "date"],
    )

    op.create_table(
        "pending_notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("region", sa.String(64), nullable=False),
        sa.Column("queue", sa.String(16), nullable=False),
        sa.Column("schedule_data", sa.Text(), nullable=False),
        sa.Column("update_type", sa.Text(), nullable=True),
        sa.Column("changes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_pn_region_queue_status",
        "pending_notifications",
        ["region", "queue", "status"],
    )

    if _table_exists("user_message_tracking"):
        op.add_column(
            "user_message_tracking",
            sa.Column("last_schedule_message_id", sa.BigInteger(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("user_message_tracking", "last_schedule_message_id")
    op.drop_index("idx_pn_region_queue_status", table_name="pending_notifications")
    op.drop_table("pending_notifications")
    op.drop_index("idx_sds_region_queue_date", table_name="schedule_daily_snapshots")
    op.drop_table("schedule_daily_snapshots")
