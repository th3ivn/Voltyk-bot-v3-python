"""Convert message_id columns from Integer to BigInteger

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-18

Telegram message IDs can exceed 2^31-1 in high-traffic channels.
Some columns were already BigInteger; this migration aligns the remaining
message-ID columns for consistency and correctness.

Affected columns:
  users.last_menu_message_id
  user_channel_config.last_post_id
  user_channel_config.last_schedule_message_id
  user_channel_config.last_power_message_id
  user_power_tracking.alert_off_message_id
  user_power_tracking.alert_on_message_id
  user_message_tracking.last_start_message_id
  user_message_tracking.last_settings_message_id
  user_message_tracking.last_timer_message_id
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("users", "last_menu_message_id",
                    existing_type=sa.Integer(), type_=sa.BigInteger(), nullable=True)

    op.alter_column("user_channel_config", "last_post_id",
                    existing_type=sa.Integer(), type_=sa.BigInteger(), nullable=True)
    op.alter_column("user_channel_config", "last_schedule_message_id",
                    existing_type=sa.Integer(), type_=sa.BigInteger(), nullable=True)
    op.alter_column("user_channel_config", "last_power_message_id",
                    existing_type=sa.Integer(), type_=sa.BigInteger(), nullable=True)

    op.alter_column("user_power_tracking", "alert_off_message_id",
                    existing_type=sa.Integer(), type_=sa.BigInteger(), nullable=True)
    op.alter_column("user_power_tracking", "alert_on_message_id",
                    existing_type=sa.Integer(), type_=sa.BigInteger(), nullable=True)

    op.alter_column("user_message_tracking", "last_start_message_id",
                    existing_type=sa.Integer(), type_=sa.BigInteger(), nullable=True)
    op.alter_column("user_message_tracking", "last_settings_message_id",
                    existing_type=sa.Integer(), type_=sa.BigInteger(), nullable=True)
    op.alter_column("user_message_tracking", "last_timer_message_id",
                    existing_type=sa.Integer(), type_=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    op.alter_column("user_message_tracking", "last_timer_message_id",
                    existing_type=sa.BigInteger(), type_=sa.Integer(), nullable=True)
    op.alter_column("user_message_tracking", "last_settings_message_id",
                    existing_type=sa.BigInteger(), type_=sa.Integer(), nullable=True)
    op.alter_column("user_message_tracking", "last_start_message_id",
                    existing_type=sa.BigInteger(), type_=sa.Integer(), nullable=True)

    op.alter_column("user_power_tracking", "alert_on_message_id",
                    existing_type=sa.BigInteger(), type_=sa.Integer(), nullable=True)
    op.alter_column("user_power_tracking", "alert_off_message_id",
                    existing_type=sa.BigInteger(), type_=sa.Integer(), nullable=True)

    op.alter_column("user_channel_config", "last_power_message_id",
                    existing_type=sa.BigInteger(), type_=sa.Integer(), nullable=True)
    op.alter_column("user_channel_config", "last_schedule_message_id",
                    existing_type=sa.BigInteger(), type_=sa.Integer(), nullable=True)
    op.alter_column("user_channel_config", "last_post_id",
                    existing_type=sa.BigInteger(), type_=sa.Integer(), nullable=True)

    op.alter_column("users", "last_menu_message_id",
                    existing_type=sa.BigInteger(), type_=sa.Integer(), nullable=True)
