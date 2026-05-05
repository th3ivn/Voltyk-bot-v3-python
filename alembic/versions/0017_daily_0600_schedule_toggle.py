"""add dedicated 06:00 daily schedule notification toggles

Revision ID: 0017_daily_0600_schedule_toggle
Revises: 0016
Create Date: 2026-05-04
"""
import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import context, op

# revision identifiers, used by Alembic.
revision = "0017_daily_0600_schedule_toggle"
down_revision = "0016"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return bool(inspect(bind).has_table(name))


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    columns = inspect(bind).get_columns(table_name)
    return any(col.get("name") == column_name for col in columns)


def upgrade() -> None:
    if not context.is_offline_mode():
        if _table_exists("user_notification_settings") and not _column_exists(
            "user_notification_settings", "notify_daily_schedule_0600"
        ):
            op.add_column(
                "user_notification_settings",
                sa.Column("notify_daily_schedule_0600", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            )
        if _table_exists("user_channel_config") and not _column_exists(
            "user_channel_config", "ch_notify_daily_schedule_0600"
        ):
            op.add_column(
                "user_channel_config",
                sa.Column("ch_notify_daily_schedule_0600", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            )
        return

    op.add_column(
        "user_notification_settings",
        sa.Column("notify_daily_schedule_0600", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "user_channel_config",
        sa.Column("ch_notify_daily_schedule_0600", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    if not context.is_offline_mode():
        if _table_exists("user_channel_config") and _column_exists("user_channel_config", "ch_notify_daily_schedule_0600"):
            op.drop_column("user_channel_config", "ch_notify_daily_schedule_0600")
        if _table_exists("user_notification_settings") and _column_exists("user_notification_settings", "notify_daily_schedule_0600"):
            op.drop_column("user_notification_settings", "notify_daily_schedule_0600")
        return

    op.drop_column("user_channel_config", "ch_notify_daily_schedule_0600")
    op.drop_column("user_notification_settings", "notify_daily_schedule_0600")
