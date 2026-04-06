from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import AdminRouter, PauseLog
from bot.utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "get_admin_router",
    "upsert_admin_router",
    "add_pause_log",
    "get_pause_logs",
]


async def get_admin_router(session: AsyncSession, admin_telegram_id: int | str) -> AdminRouter | None:
    result = await session.execute(
        select(AdminRouter).where(AdminRouter.admin_telegram_id == str(admin_telegram_id))
    )
    return result.scalars().first()


async def upsert_admin_router(
    session: AsyncSession, admin_telegram_id: int | str, **kwargs
) -> AdminRouter:
    """Upsert an AdminRouter row atomically.

    Uses ``INSERT … ON CONFLICT DO UPDATE`` to avoid the SELECT-then-INSERT
    race condition that could cause a unique-constraint violation when two
    concurrent callers both observe "not found" and both attempt an INSERT.
    """
    tid = str(admin_telegram_id)
    stmt = (
        pg_insert(AdminRouter)
        .values(admin_telegram_id=tid, **kwargs)
        .on_conflict_do_update(
            index_elements=["admin_telegram_id"],
            set_=kwargs,
        )
        .returning(AdminRouter)
    )
    result = await session.execute(stmt)
    await session.flush()
    return result.scalars().one()


async def add_pause_log(
    session: AsyncSession,
    admin_id: int | str,
    event_type: str,
    pause_type: str | None = None,
    message: str | None = None,
    reason: str | None = None,
) -> None:
    session.add(
        PauseLog(
            admin_id=str(admin_id),
            event_type=event_type,
            pause_type=pause_type,
            message=message,
            reason=reason,
        )
    )


async def get_pause_logs(session: AsyncSession, limit: int = 20) -> list[PauseLog]:
    result = await session.execute(select(PauseLog).order_by(PauseLog.created_at.desc()).limit(limit))
    return list(result.scalars().all())
