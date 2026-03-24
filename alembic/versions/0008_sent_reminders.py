"""Add sent_reminders table for reminder deduplication persistence

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-23

Replaces the in-memory ``_sent_reminders`` set in scheduler.py with a
PostgreSQL-backed table so that reminder deduplication survives bot restarts.
Old rows are pruned daily (>48 h) by the 06:00 flush job.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sent_reminders",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.String(64), nullable=False),
        sa.Column("region", sa.String(64), nullable=False),
        sa.Column("queue", sa.String(16), nullable=False),
        sa.Column("period_key", sa.String(64), nullable=False),
        sa.Column("reminder_type", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("telegram_id", "period_key", "reminder_type", name="uq_sent_reminder"),
    )
    op.create_index("idx_sr_created_at", "sent_reminders", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_sr_created_at", table_name="sent_reminders")
    op.drop_table("sent_reminders")
