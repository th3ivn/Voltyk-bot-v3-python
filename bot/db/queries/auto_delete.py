from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import AutoDeleteQueue

__all__ = [
    "enqueue_auto_delete",
    "get_due_auto_delete",
    "remove_auto_delete_entries",
]


async def enqueue_auto_delete(
    session: AsyncSession,
    *,
    user_id: int,
    chat_id: int | str,
    message_id: int,
    source: str,
    delete_at: datetime,
) -> None:
    # Idempotent insert: if the same message is already queued, keep the
    # earliest delete_at and update source for easier diagnostics.
    stmt = insert(AutoDeleteQueue).values(
        user_id=user_id,
        chat_id=str(chat_id),
        message_id=message_id,
        source=source,
        delete_at=delete_at,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_auto_delete_queue_chat_message",
        set_={
            "delete_at": stmt.excluded.delete_at,
            "source": stmt.excluded.source,
        },
    )
    await session.execute(stmt)


async def get_due_auto_delete(session: AsyncSession, limit: int = 200) -> list[AutoDeleteQueue]:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(AutoDeleteQueue)
        .where(AutoDeleteQueue.delete_at <= now)
        .order_by(AutoDeleteQueue.delete_at.asc(), AutoDeleteQueue.id.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def remove_auto_delete_entries(session: AsyncSession, ids: list[int]) -> int:
    if not ids:
        return 0
    res = await session.execute(delete(AutoDeleteQueue).where(AutoDeleteQueue.id.in_(ids)))
    return int(res.rowcount or 0)
