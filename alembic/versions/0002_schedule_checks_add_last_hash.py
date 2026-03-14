"""schedule_checks: add last_hash column

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "schedule_checks",
        sa.Column("last_hash", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("schedule_checks", "last_hash")
