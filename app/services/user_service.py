"""User CRUD service.

All database operations use async SQLAlchemy sessions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.constants.regions import REGION_CODE_TO_ID
from app.db.models.user import User

if TYPE_CHECKING:
    from aiogram.types import User as TelegramUser
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def get_or_create_user(
    session: AsyncSession,
    telegram_user: TelegramUser,
) -> User:
    """Upsert a user record by Telegram ID.

    Creates the user if they don't exist; otherwise updates
    username / first_name / last_name to the latest values.

    Args:
        session: Active async database session.
        telegram_user: aiogram User object from the incoming update.

    Returns:
        The up-to-date User ORM instance.
    """
    stmt = (
        pg_insert(User)
        .values(
            id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            last_name=telegram_user.last_name,
        )
        .on_conflict_do_update(
            index_elements=[User.id],
            set_={
                "username": telegram_user.username,
                "first_name": telegram_user.first_name,
                "last_name": telegram_user.last_name,
            },
        )
        .returning(User)
    )
    result = await session.execute(stmt)
    await session.commit()
    user: User = result.scalars().one()
    return user


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    """Fetch a user by Telegram ID.

    Args:
        session: Active async database session.
        user_id: Telegram user ID.

    Returns:
        User ORM instance or None if not found.
    """
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalars().first()


async def update_user_region(
    session: AsyncSession,
    user_id: int,
    region_code: str,
    queue_str: str,
) -> None:
    """Persist the chosen region and queue for a user.

    Maps ``region_code`` → integer ``region_id`` and stores the raw
    queue string (e.g. ``"3.2"``) in the ``queue`` column.
    The group number (integer part of queue) is stored in ``group_id``
    for backwards-compatible index queries.

    Args:
        session: Active async database session.
        user_id: Telegram user ID.
        region_code: Region code string, e.g. ``"kyiv"``.
        queue_str: Queue string, e.g. ``"3.2"`` or ``"15.1"``.
    """
    region_id = REGION_CODE_TO_ID.get(region_code)
    if region_id is None:
        logger.warning("Unknown region_code=%r for user_id=%d", region_code, user_id)
        return

    try:
        group_id = int(queue_str.split(".")[0])
    except (ValueError, IndexError):
        logger.warning(
            "Cannot parse group_id from queue_str=%r for user_id=%d", queue_str, user_id
        )
        group_id = None

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if user is None:
        logger.warning("update_user_region: user_id=%d not found", user_id)
        return

    user.region_id = region_id
    user.group_id = group_id
    user.queue = queue_str
    await session.commit()
