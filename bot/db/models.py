from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(255))
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    queue: Mapped[str] = mapped_column(String(16), nullable=False)
    router_ip: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_menu_message_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    notification_settings: Mapped[UserNotificationSettings | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", lazy="noload"
    )
    channel_config: Mapped[UserChannelConfig | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", lazy="noload"
    )
    power_tracking: Mapped[UserPowerTracking | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", lazy="noload"
    )
    message_tracking: Mapped[UserMessageTracking | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", lazy="noload"
    )
    __table_args__ = (
        Index("idx_users_region_queue", "region", "queue"),
        Index("idx_users_active_region", "is_active", "region"),
        Index("idx_users_router_ip_active", "router_ip", "is_active"),
        Index("idx_users_created_at_desc", "created_at"),
    )


class UserNotificationSettings(Base):
    __tablename__ = "user_notification_settings"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)

    notify_schedule_changes: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    notify_remind_off: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    notify_fact_off: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    notify_remind_on: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    notify_fact_on: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    remind_15m: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    remind_30m: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    remind_1h: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    notify_schedule_target: Mapped[str] = mapped_column(String(16), default="bot", server_default="bot")
    notify_remind_target: Mapped[str] = mapped_column(String(16), default="bot", server_default="bot")
    notify_power_target: Mapped[str] = mapped_column(String(16), default="bot", server_default="bot")

    auto_delete_commands: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    auto_delete_bot_messages: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    notify_emergency_off: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    notify_emergency_on: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="notification_settings")


class UserEmergencyConfig(Base):
    """Address config for emergency outage lookups (migration 0007)."""

    __tablename__ = "user_emergency_config"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    city: Mapped[str | None] = mapped_column(String(128))
    street: Mapped[str | None] = mapped_column(String(255))
    house: Mapped[str | None] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserEmergencyState(Base):
    """Cached emergency outage state per user (migration 0007)."""

    __tablename__ = "user_emergency_state"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), server_default="none")
    start_date: Mapped[str | None] = mapped_column(String(32))
    end_date: Mapped[str | None] = mapped_column(String(32))
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserChannelConfig(Base):
    __tablename__ = "user_channel_config"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)

    channel_id: Mapped[str | None] = mapped_column(String(64))
    channel_title: Mapped[str | None] = mapped_column(String(255))
    channel_description: Mapped[str | None] = mapped_column(Text)
    channel_photo_file_id: Mapped[str | None] = mapped_column(String(255))
    channel_user_title: Mapped[str | None] = mapped_column(String(255))
    channel_user_description: Mapped[str | None] = mapped_column(Text)
    channel_status: Mapped[str] = mapped_column(String(32), default="active", server_default="active")
    channel_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    channel_branding_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    channel_guard_warnings: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    last_published_hash: Mapped[str | None] = mapped_column(String(128))
    last_post_id: Mapped[int | None] = mapped_column(Integer)
    last_schedule_message_id: Mapped[int | None] = mapped_column(Integer)
    last_power_message_id: Mapped[int | None] = mapped_column(Integer)

    schedule_caption: Mapped[str | None] = mapped_column(Text)
    period_format: Mapped[str | None] = mapped_column(Text)
    power_off_text: Mapped[str | None] = mapped_column(Text)
    power_on_text: Mapped[str | None] = mapped_column(Text)
    delete_old_message: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    picture_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    ch_notify_schedule: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    ch_notify_remind_off: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    ch_notify_remind_on: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    ch_notify_fact_off: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    ch_notify_fact_on: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    ch_remind_15m: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    ch_remind_30m: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    ch_remind_1h: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="channel_config")

    __table_args__ = (
        Index("idx_ucc_channel_id", "channel_id"),
        Index("idx_ucc_active_channel", "channel_id", "channel_status"),
    )


class UserPowerTracking(Base):
    __tablename__ = "user_power_tracking"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)

    power_state: Mapped[str | None] = mapped_column(String(16))
    power_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pending_power_state: Mapped[str | None] = mapped_column(String(16))
    pending_power_change_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_power_state: Mapped[str | None] = mapped_column(String(16))
    last_power_change: Mapped[int | None] = mapped_column(Integer)
    power_on_duration: Mapped[int | None] = mapped_column(Integer)
    last_alert_off_period: Mapped[str | None] = mapped_column(String(64))
    last_alert_on_period: Mapped[str | None] = mapped_column(String(64))
    alert_off_message_id: Mapped[int | None] = mapped_column(Integer)
    alert_on_message_id: Mapped[int | None] = mapped_column(Integer)

    last_ping_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bot_power_message_id: Mapped[int | None] = mapped_column(BigInteger)
    ch_power_message_id: Mapped[int | None] = mapped_column(BigInteger)
    power_message_type: Mapped[str | None] = mapped_column(String(16))

    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="power_tracking")


class UserMessageTracking(Base):
    __tablename__ = "user_message_tracking"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)

    last_bot_keyboard_message_id: Mapped[int | None] = mapped_column(BigInteger)
    last_reminder_message_id: Mapped[int | None] = mapped_column(BigInteger)
    last_channel_reminder_message_id: Mapped[int | None] = mapped_column(BigInteger)
    last_start_message_id: Mapped[int | None] = mapped_column(Integer)
    last_settings_message_id: Mapped[int | None] = mapped_column(Integer)
    last_timer_message_id: Mapped[int | None] = mapped_column(Integer)
    last_schedule_message_id: Mapped[int | None] = mapped_column(BigInteger)

    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="message_tracking")


class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="feedback", server_default="feedback")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", server_default="open")
    subject: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_by: Mapped[str | None] = mapped_column(String(64))

    messages: Mapped[list[TicketMessage]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", lazy="selectin"
    )


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    sender_type: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_id: Mapped[str] = mapped_column(String(64), nullable=False)
    message_type: Mapped[str] = mapped_column(String(16), nullable=False, default="text", server_default="text")
    content: Mapped[str | None] = mapped_column(Text)
    file_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    ticket: Mapped[Ticket] = relationship(back_populates="messages")


class OutageHistory(Base):
    __tablename__ = "outage_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PowerHistory(Base):
    __tablename__ = "power_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    timestamp: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)


class ScheduleHistory(Base):
    __tablename__ = "schedule_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    queue: Mapped[str] = mapped_column(String(16), nullable=False)
    schedule_data: Mapped[str] = mapped_column(Text, nullable=False)
    hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ScheduleCheck(Base):
    __tablename__ = "schedule_checks"

    region: Mapped[str] = mapped_column(String(50), primary_key=True)
    queue: Mapped[str] = mapped_column(String(10), primary_key=True)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)


class UserState(Base):
    __tablename__ = "user_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[str] = mapped_column(String(64), nullable=False)
    state_type: Mapped[str] = mapped_column(String(64), nullable=False)
    state_data: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("telegram_id", "state_type", name="uq_user_state_type"),)


class PendingChannel(Base):
    __tablename__ = "pending_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    channel_username: Mapped[str | None] = mapped_column(String(255))
    channel_title: Mapped[str | None] = mapped_column(String(255))
    telegram_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PauseLog(Base):
    __tablename__ = "pause_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    pause_type: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AdminRouter(Base):
    __tablename__ = "admin_routers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_telegram_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    router_ip: Mapped[str | None] = mapped_column(String(255))
    router_port: Mapped[int] = mapped_column(Integer, default=80)
    notifications_on: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_state: Mapped[str | None] = mapped_column(String(20))
    last_change_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AdminRouterHistory(Base):
    __tablename__ = "admin_router_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_telegram_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    event_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserPowerState(Base):
    __tablename__ = "user_power_states"

    telegram_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    current_state: Mapped[str | None] = mapped_column(String(16))
    pending_state: Mapped[str | None] = mapped_column(String(16))
    pending_state_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_stable_state: Mapped[str | None] = mapped_column(String(16))
    last_stable_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    instability_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    switch_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_notification_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ScheduleDailySnapshot(Base):
    """Stores a daily snapshot of the schedule for each region/queue.

    Used to compare today's and tomorrow's events across checks and determine
    update_type (todayUpdated, tomorrowAppeared, etc.) and compute 🆕 markers.
    Bot and channel message IDs are tracked separately in UserMessageTracking
    and UserChannelConfig respectively.
    """

    __tablename__ = "schedule_daily_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    queue: Mapped[str] = mapped_column(String(16), nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD in Kyiv TZ
    schedule_data: Mapped[str] = mapped_column(Text, nullable=False)  # JSON-encoded sched dict
    today_hash: Mapped[str | None] = mapped_column(String(128))
    tomorrow_hash: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("region", "queue", "date", name="uq_schedule_daily_snapshot"),
        Index("idx_sds_region_queue_date", "region", "queue", "date"),
    )


class PendingNotification(Base):
    """Queue for schedule notifications during quiet hours (00:00–05:59 Kyiv).

    At 06:00 the flush job processes all pending rows: for each (region, queue)
    the latest pending row is sent to all subscribed users, then all rows are
    marked 'sent'.  If no pending row exists at 06:00, a fresh daily-planned
    message is sent instead.
    """

    __tablename__ = "pending_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    queue: Mapped[str] = mapped_column(String(16), nullable=False)
    schedule_data: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    update_type: Mapped[str | None] = mapped_column(Text)  # JSON
    changes: Mapped[str | None] = mapped_column(Text)  # JSON
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_pn_region_queue_status", "region", "queue", "status"),
    )


class PingErrorAlert(Base):
    """Tracking daily ping-error alerts per user."""

    __tablename__ = "ping_error_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    router_ip: Mapped[str] = mapped_column(String(255), nullable=False)
    last_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("telegram_id", name="uq_ping_error_alert_user"),
    )


class SentReminder(Base):
    """Deduplication log for scheduled reminder notifications.

    Each row records that a specific reminder type was sent to a user for a
    given event anchor (period_key).  Rows older than 48 h are pruned daily by
    the flush job so the table stays small.
    """

    __tablename__ = "sent_reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[str] = mapped_column(String(64), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    queue: Mapped[str] = mapped_column(String(16), nullable=False)
    # ISO-8601 datetime of the event this reminder refers to (e.g. "2026-03-23T14:00:00+02:00")
    period_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # "15m" | "30m" | "1h"
    reminder_type: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("telegram_id", "period_key", "reminder_type", name="uq_sent_reminder"),
        Index("idx_sr_created_at", "created_at"),
    )


class AdminTicketReminder(Base):
    """Admin reminder for unanswered support tickets."""

    __tablename__ = "admin_ticket_reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    admin_telegram_id: Mapped[str] = mapped_column(String(64), nullable=False)
    last_reminder_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


