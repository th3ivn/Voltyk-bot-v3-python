"""DailyMetrics model — aggregated daily statistics."""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DailyMetrics(Base):
    """Aggregated daily metrics snapshot for monitoring and analytics."""

    __tablename__ = "daily_metrics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    date: Mapped[date] = mapped_column(Date)

    total_users: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    active_users: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    new_users: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_channels: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    notifications_sent: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("date", name="uq_daily_metrics_date"),)

    def __repr__(self) -> str:
        return f"<DailyMetrics date={self.date} active_users={self.active_users}>"
