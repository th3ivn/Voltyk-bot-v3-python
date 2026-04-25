"""Add durable queue for auto-deleting user/bot messages

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-25
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auto_delete_queue",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chat_id", sa.String(length=64), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="bot_reply"),
        sa.Column("delete_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("chat_id", "message_id", name="uq_auto_delete_queue_chat_message"),
    )
    op.create_index("ix_auto_delete_queue_chat_id", "auto_delete_queue", ["chat_id"])
    op.create_index("ix_auto_delete_queue_delete_at", "auto_delete_queue", ["delete_at"])
    op.create_index("idx_auto_delete_queue_due", "auto_delete_queue", ["delete_at", "id"])


def downgrade() -> None:
    op.drop_index("idx_auto_delete_queue_due", table_name="auto_delete_queue")
    op.drop_index("ix_auto_delete_queue_delete_at", table_name="auto_delete_queue")
    op.drop_index("ix_auto_delete_queue_chat_id", table_name="auto_delete_queue")
    op.drop_table("auto_delete_queue")
