"""ScheduleHistory and ScheduleCheck models."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ScheduleHistory(Base):
    """Historical schedule data per region/group/date.

    Unique constraint on (region_id, group_id, date) prevents duplicates.
    """

    __tablename__ = "schedule_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    region_id: Mapped[int] = mapped_column(Integer)
    group_id: Mapped[int] = mapped_column(Integer)
    schedule_data: Mapped[dict] = mapped_column(JSONB)
    date: Mapped[date] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("region_id", "group_id", "date", name="uq_schedule_region_group_date"),
    )

    def __repr__(self) -> str:
        return f"<ScheduleHistory region={self.region_id} group={self.group_id} date={self.date}>"


class ScheduleCheck(Base):
    """Last-checked metadata per region used for change detection."""

    __tablename__ = "schedule_checks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    region_id: Mapped[int] = mapped_column(Integer, unique=True)
    last_hash: Mapped[str] = mapped_column(String(64))
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    changes_detected: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    def __repr__(self) -> str:
        return f"<ScheduleCheck region={self.region_id} changed={self.changes_detected}>"
