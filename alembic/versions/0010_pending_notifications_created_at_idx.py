"""Add index on pending_notifications.created_at for efficient cleanup queries

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-04

The delete_old_pending_notifications() query filters by created_at < cutoff.
Without an index the DB must scan the whole table on every cleanup run.
The table stays small in normal operation (rows live ≤ 48 h), but adding the
index protects against pathological growth and keeps EXPLAIN output clean.
"""

from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_pn_created_at",
        "pending_notifications",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_pn_created_at", table_name="pending_notifications")
