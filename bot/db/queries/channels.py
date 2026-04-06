from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import PendingChannel
from bot.utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "save_pending_channel",
    "get_pending_channel_by_telegram_id",
    "get_pending_channel",
    "delete_pending_channel",
    "delete_pending_channel_by_telegram_id",
]


async def save_pending_channel(
    session: AsyncSession,
    channel_id: str,
    telegram_id: int | str,
    channel_username: str | None = None,
    channel_title: str | None = None,
) -> PendingChannel:
    """Upsert a pending-channel row atomically.

    Uses ``INSERT … ON CONFLICT DO UPDATE`` to avoid the SELECT-then-INSERT
    race condition where two concurrent calls could both observe "not found"
    and both attempt an INSERT, causing a unique-constraint violation.
    """
    tid = str(telegram_id)
    stmt = (
        pg_insert(PendingChannel)
        .values(
            channel_id=channel_id,
            telegram_id=tid,
            channel_username=channel_username,
            channel_title=channel_title,
        )
        .on_conflict_do_update(
            index_elements=["channel_id"],
            set_={
                "telegram_id": tid,
                "channel_username": channel_username,
                "channel_title": channel_title,
            },
        )
        .returning(PendingChannel)
    )
    result = await session.execute(stmt)
    await session.flush()
    return result.scalars().one()


async def get_pending_channel_by_telegram_id(session: AsyncSession, telegram_id: int | str) -> PendingChannel | None:
    result = await session.execute(
        select(PendingChannel).where(PendingChannel.telegram_id == str(telegram_id))
    )
    return result.scalars().first()


async def get_pending_channel(
    session: AsyncSession,
    telegram_id: int | str,
    channel_id: str,
) -> PendingChannel | None:
    """Return the pending channel row matching both the user and the specific channel_id.

    Prefer this over get_pending_channel_by_telegram_id() when the callback already
    carries the channel_id — avoids ambiguity when a user has multiple pending rows.
    """
    result = await session.execute(
        select(PendingChannel).where(
            PendingChannel.telegram_id == str(telegram_id),
            PendingChannel.channel_id == channel_id,
        )
    )
    return result.scalars().first()


async def delete_pending_channel(session: AsyncSession, channel_id: str) -> None:
    await session.execute(delete(PendingChannel).where(PendingChannel.channel_id == channel_id))


async def delete_pending_channel_by_telegram_id(session: AsyncSession, telegram_id: int | str) -> None:
    await session.execute(delete(PendingChannel).where(PendingChannel.telegram_id == str(telegram_id)))
