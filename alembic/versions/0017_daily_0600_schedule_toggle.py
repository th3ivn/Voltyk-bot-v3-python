"""add dedicated 06:00 daily schedule notification toggles

Revision ID: 0017_daily_0600_schedule_toggle
Revises: 0016_auto_delete_queue
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0017_daily_0600_schedule_toggle"
down_revision = "0016_auto_delete_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_notification_settings",
        sa.Column("notify_daily_schedule_0600", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "user_channel_config",
        sa.Column("ch_notify_daily_schedule_0600", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("user_channel_config", "ch_notify_daily_schedule_0600")
    op.drop_column("user_notification_settings", "notify_daily_schedule_0600")
