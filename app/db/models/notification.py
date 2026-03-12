"""BotNotification and ChannelNotification models.

These are intentionally separate entities — bot notifications are sent
directly to users, while channel notifications are posted to channels.
Both use Celery queue with retry logic.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BotNotification(Base):
    """Notification queued for delivery to a Telegram user (via bot)."""

    __tablename__ = "bot_notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    message_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending"
    )  # pending / sent / failed
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_bot_notifications_user_id", "user_id"),
        Index("ix_bot_notifications_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<BotNotification id={self.id} type={self.message_type!r} status={self.status!r}>"


class ChannelNotification(Base):
    """Notification queued for posting to a Telegram channel."""

    __tablename__ = "channel_notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("channels.id", ondelete="CASCADE")
    )
    message_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending"
    )  # pending / sent / failed
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_channel_notifications_channel_id", "channel_id"),
        Index("ix_channel_notifications_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<ChannelNotification id={self.id} "
            f"type={self.message_type!r} status={self.status!r}>"
        )
