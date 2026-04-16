from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import (
    User,
    UserChannelConfig,
    UserMessageTracking,
    UserNotificationSettings,
    UserPowerTracking,
)
from bot.utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "get_user_by_telegram_id",
    "create_or_update_user",
    "deactivate_user",
    "delete_user_data",
    "get_active_users_by_region",
    "get_active_users_by_region_cursor",
    "get_distinct_region_queue_pairs",
    "get_active_user_ids_paginated",
    "get_active_user_ids_cursor",
    "get_all_active_users",
    "get_active_users_paginated",
    "get_users_with_ip",
    "get_users_with_ip_cursor",
    "get_active_power_users_by_region_queue_cursor",
    "get_users_with_channel",
    "get_user_by_channel_id",
    "count_active_users",
    "count_total_users",
    "get_recent_users",
]

# Module-level constant so SQLAlchemy loader options are not re-created on
# every query call (each selectinload() call allocates a new option object).
_USER_WITH_RELATIONS = (
    selectinload(User.notification_settings),
    selectinload(User.channel_config),
    selectinload(User.power_tracking),
    selectinload(User.message_tracking),
)


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int | str) -> User | None:
    tid = str(telegram_id)
    result = await session.execute(
        select(User).options(*_USER_WITH_RELATIONS).where(User.telegram_id == tid)
    )
    return result.scalars().first()


async def create_or_update_user(
    session: AsyncSession,
    telegram_id: int | str,
    username: str | None,
    region: str,
    queue: str,
) -> User:
    tid = str(telegram_id)
    user = await get_user_by_telegram_id(session, tid)

    if user:
        user.region = region
        user.queue = queue
        user.username = username
        user.is_active = True
        user.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        user = User(
            telegram_id=tid,
            username=username,
            region=region,
            queue=queue,
            is_active=True,
        )
        session.add(user)
        await session.flush()

        ns = UserNotificationSettings(user_id=user.id)
        cc = UserChannelConfig(user_id=user.id)
        pt = UserPowerTracking(user_id=user.id)
        mt = UserMessageTracking(user_id=user.id)
        session.add_all([ns, cc, pt, mt])
        await session.flush()

        user.notification_settings = ns
        user.channel_config = cc
        user.power_tracking = pt
        user.message_tracking = mt

        return user

    if not user.notification_settings:
        ns = UserNotificationSettings(user_id=user.id)
        session.add(ns)
        await session.flush()
        user.notification_settings = ns

    if not user.channel_config:
        cc = UserChannelConfig(user_id=user.id)
        session.add(cc)
        await session.flush()
        user.channel_config = cc

    if not user.power_tracking:
        pt = UserPowerTracking(user_id=user.id)
        session.add(pt)
        await session.flush()
        user.power_tracking = pt

    if not user.message_tracking:
        mt = UserMessageTracking(user_id=user.id)
        session.add(mt)
        await session.flush()
        user.message_tracking = mt

    return user


async def deactivate_user(session: AsyncSession, telegram_id: int | str) -> None:
    tid = str(telegram_id)
    await session.execute(update(User).where(User.telegram_id == tid).values(is_active=False))


async def delete_user_data(session: AsyncSession, telegram_id: int | str) -> None:
    tid = str(telegram_id)
    user = await get_user_by_telegram_id(session, tid)
    if user:
        # DB-level ON DELETE CASCADE (migration 0012) handles outage_history,
        # power_history and schedule_history automatically.
        # ORM cascade="all, delete-orphan" handles notification_settings,
        # channel_config, power_tracking and message_tracking.
        await session.delete(user)


async def get_active_users_by_region(
    session: AsyncSession, region: str, queue: str | None = None
) -> list[User]:
    conditions = [User.is_active.is_(True), User.region == region]
    if queue is not None:
        conditions.append(User.queue == queue)
    result = await session.execute(
        select(User).options(*_USER_WITH_RELATIONS).where(*conditions)
    )
    return list(result.scalars().all())


async def get_active_users_by_region_cursor(
    session: AsyncSession,
    region: str,
    queue: str | None = None,
    limit: int = 1000,
    after_id: int = 0,
) -> list[User]:
    """Cursor-based version of get_active_users_by_region.

    Uses ``WHERE id > after_id`` for O(1) seeks — safe for 100k-scale
    notification blasts.  Pass ``after_id=batch[-1].id`` to get the next page.
    """
    conditions = [User.is_active.is_(True), User.region == region, User.id > after_id]
    if queue is not None:
        conditions.append(User.queue == queue)
    result = await session.execute(
        select(User).options(*_USER_WITH_RELATIONS)
        .where(*conditions)
        .order_by(User.id)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_distinct_region_queue_pairs(session: AsyncSession) -> list[tuple[str, str]]:
    """Return unique (region, queue) pairs for all active users.

    Uses idx_users_region_queue index.  Returns ~50-100 rows instead of
    scanning the entire users table — critical for 100k-scale loops.
    """
    result = await session.execute(
        select(User.region, User.queue)
        .where(
            User.is_active.is_(True),
            User.region.isnot(None),
            User.queue.isnot(None),
        )
        .distinct()
    )
    return list(result.all())  # type: ignore[arg-type]


async def get_active_user_ids_paginated(
    session: AsyncSession, limit: int = 500, offset: int = 0,
) -> list[tuple[int, str]]:
    """Return (id, telegram_id) for active users — no relation loading.

    Designed for broadcast where only telegram_id is needed.
    DEPRECATED: prefer get_active_user_ids_cursor() for 100k-scale.
    """
    result = await session.execute(
        select(User.id, User.telegram_id)
        .where(User.is_active.is_(True))
        .order_by(User.id)
        .limit(limit)
        .offset(offset)
    )
    return list(result.all())  # type: ignore[arg-type]


async def get_active_user_ids_cursor(
    session: AsyncSession, limit: int = 500, after_id: int = 0,
) -> list[tuple[int, str]]:
    """Return (id, telegram_id) for active users using cursor-based pagination.

    Uses ``WHERE id > after_id`` instead of OFFSET — O(1) seek instead of
    O(N) skip, critical for 100k+ users.  Pass ``after_id=last_row.id``
    from previous batch to get the next page.
    """
    result = await session.execute(
        select(User.id, User.telegram_id)
        .where(User.is_active.is_(True), User.id > after_id)
        .order_by(User.id)
        .limit(limit)
    )
    return list(result.all())  # type: ignore[arg-type]


async def get_all_active_users(session: AsyncSession) -> list[User]:
    result = await session.execute(
        select(User).options(*_USER_WITH_RELATIONS).where(User.is_active.is_(True)).order_by(User.id)
    )
    return list(result.scalars().all())


async def get_active_users_paginated(session: AsyncSession, limit: int = 500, offset: int = 0) -> list[User]:
    result = await session.execute(
        select(User)
        .options(*_USER_WITH_RELATIONS)
        .where(User.is_active.is_(True))
        .order_by(User.id)
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def get_users_with_ip(session: AsyncSession) -> list[User]:
    result = await session.execute(
        select(User).options(*_USER_WITH_RELATIONS).where(
            User.is_active.is_(True),
            User.router_ip.isnot(None),
            User.router_ip != "",
        )
    )
    return list(result.scalars().all())


async def get_users_with_ip_cursor(
    session: AsyncSession,
    limit: int = 500,
    after_id: int = 0,
) -> list[User]:
    """Cursor-based version of get_users_with_ip.

    Returns active users with a non-empty router_ip where id > after_id.
    Pass ``after_id=batch[-1].id`` to get the next page.
    """
    result = await session.execute(
        select(User)
        .options(*_USER_WITH_RELATIONS)
        .where(
            User.is_active.is_(True),
            User.router_ip.isnot(None),
            User.router_ip != "",
            User.id > after_id,
        )
        .order_by(User.id)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_active_power_users_by_region_queue_cursor(
    session: AsyncSession,
    region: str,
    queue: str,
    limit: int = 500,
    after_id: int = 0,
) -> list[User]:
    """Cursor-based fetch of active power-monitoring users for a region/queue pair.

    Returns active users who have a non-empty router_ip, belong to *region* and
    *queue*, and whose id > after_id.  Pass ``after_id=batch[-1].id`` for the
    next page.  Loads power_tracking and channel_config eagerly because callers
    need both relationships.
    """
    result = await session.execute(
        select(User)
        .options(
            selectinload(User.power_tracking),
            selectinload(User.channel_config),
        )
        .where(
            User.is_active.is_(True),
            User.region == region,
            User.queue == queue,
            User.router_ip.isnot(None),
            User.id > after_id,
        )
        .order_by(User.id)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_users_with_channel(session: AsyncSession) -> list[User]:
    result = await session.execute(
        select(User)
        .options(*_USER_WITH_RELATIONS)
        .join(UserChannelConfig, User.id == UserChannelConfig.user_id)
        .where(
            User.is_active.is_(True),
            UserChannelConfig.channel_id.isnot(None),
            UserChannelConfig.channel_status == "active",
        )
    )
    return list(result.scalars().all())


async def get_user_by_channel_id(session: AsyncSession, channel_id: str) -> User | None:
    result = await session.execute(
        select(User)
        .options(*_USER_WITH_RELATIONS)
        .join(UserChannelConfig, User.id == UserChannelConfig.user_id)
        .where(UserChannelConfig.channel_id == channel_id)
    )
    return result.scalars().first()


async def count_active_users(session: AsyncSession) -> int:
    result = await session.execute(select(func.count(User.id)).where(User.is_active.is_(True)))
    return result.scalar() or 0


async def count_total_users(session: AsyncSession) -> int:
    result = await session.execute(select(func.count(User.id)))
    return result.scalar() or 0


async def get_recent_users(session: AsyncSession, limit: int = 20) -> list[User]:
    result = await session.execute(
        select(User).options(*_USER_WITH_RELATIONS).order_by(User.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())
