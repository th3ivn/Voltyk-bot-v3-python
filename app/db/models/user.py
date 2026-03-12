"""User model — Telegram bot users."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    """Telegram user record.

    Primary key is the Telegram user ID (BigInteger).
    Optimised with indexes on region_id, group_id, and is_blocked
    to support 100k DAU query patterns.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user ID
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    region_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    bot_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    channel_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )

    language: Mapped[str] = mapped_column(String(8), default="uk", server_default="uk")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_users_region_id", "region_id"),
        Index("ix_users_group_id", "group_id"),
        Index("ix_users_is_blocked", "is_blocked"),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r}>"
