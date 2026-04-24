from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Setting
from bot.utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "delete_setting",
    "get_setting",
    "set_setting",
]


async def get_setting(session: AsyncSession, key: str) -> str | None:
    result = await session.execute(select(Setting).where(Setting.key == key))
    setting = result.scalars().first()
    return setting.value if setting else None


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    """Atomically insert or update a setting row (upsert).

    The previous SELECT-then-INSERT/UPDATE pattern was a race condition: two
    concurrent callers could both observe "not found" and both try to INSERT,
    causing a unique-constraint violation.  Using PostgreSQL's
    ``INSERT … ON CONFLICT DO UPDATE`` makes this a single atomic statement.
    """
    stmt = (
        pg_insert(Setting)
        .values(key=key, value=value)
        .on_conflict_do_update(index_elements=["key"], set_={"value": value})
    )
    await session.execute(stmt)


async def delete_setting(session: AsyncSession, key: str) -> None:
    """Remove a setting row.  No-op if the key does not exist."""
    await session.execute(delete(Setting).where(Setting.key == key))
