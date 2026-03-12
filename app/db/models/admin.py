"""AdminRouter and Settings models."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AdminRouter(Base):
    """Router configuration managed by an admin for power monitoring."""

    __tablename__ = "admin_routers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    admin_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    router_host: Mapped[str] = mapped_column(String(256))
    router_port: Mapped[int] = mapped_column(Integer, default=80, server_default="80")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<AdminRouter host={self.router_host!r} active={self.is_active}>"


class Settings(Base):
    """Global bot settings stored as key-value pairs."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(String(1024))

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Settings key={self.key!r}>"
