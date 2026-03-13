from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import (
    AdminRouter,
    PauseLog,
    PendingChannel,
    PowerHistory,
    ScheduleCheck,
    Setting,
    Ticket,
    TicketMessage,
    User,
    UserChannelConfig,
    UserMessageTracking,
    UserNotificationSettings,
    UserPowerState,
    UserPowerTracking,
)

logger = logging.getLogger(__name__)


def _user_with_relations():
    """Standard eager-load options for User queries."""
    return (
        selectinload(User.notification_settings),
        selectinload(User.channel_config),
        selectinload(User.power_tracking),
        selectinload(User.message_tracking),
    )


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int | str) -> User | None:
    tid = str(telegram_id)
    result = await session.execute(
        select(User).options(*_user_with_relations()).where(User.telegram_id == tid)
    )
    return result.scalars().first()


async def get_user_full(session: AsyncSession, telegram_id: int | str) -> User | None:
    return await get_user_by_telegram_id(session, telegram_id)


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
        user.updated_at = datetime.utcnow()
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
        await session.delete(user)


async def get_active_users_by_region(session: AsyncSession, region: str) -> list[User]:
    result = await session.execute(
        select(User).options(*_user_with_relations()).where(User.is_active.is_(True), User.region == region)
    )
    return list(result.scalars().all())


async def get_all_active_users(session: AsyncSession) -> list[User]:
    result = await session.execute(
        select(User).options(*_user_with_relations()).where(User.is_active.is_(True)).order_by(User.id)
    )
    return list(result.scalars().all())


async def get_active_users_paginated(session: AsyncSession, limit: int = 500, offset: int = 0) -> list[User]:
    result = await session.execute(
        select(User)
        .options(*_user_with_relations())
        .where(User.is_active.is_(True))
        .order_by(User.id)
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def get_users_with_ip(session: AsyncSession) -> list[User]:
    result = await session.execute(
        select(User).options(*_user_with_relations()).where(
            User.is_active.is_(True),
            User.router_ip.isnot(None),
            User.router_ip != "",
        )
    )
    return list(result.scalars().all())


async def get_users_with_channel(session: AsyncSession) -> list[User]:
    result = await session.execute(
        select(User)
        .options(*_user_with_relations())
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
        .options(*_user_with_relations())
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
        select(User).options(*_user_with_relations()).order_by(User.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


# ─── Settings ──────────────────────────────────────────────────────────────


async def get_setting(session: AsyncSession, key: str) -> str | None:
    result = await session.execute(select(Setting).where(Setting.key == key))
    setting = result.scalars().first()
    return setting.value if setting else None


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    result = await session.execute(select(Setting).where(Setting.key == key))
    setting = result.scalars().first()
    if setting:
        setting.value = value
    else:
        session.add(Setting(key=key, value=value))


# ─── Tickets ───────────────────────────────────────────────────────────────


async def create_ticket(
    session: AsyncSession,
    telegram_id: int | str,
    ticket_type: str,
    subject: str | None = None,
) -> Ticket:
    ticket = Ticket(telegram_id=str(telegram_id), type=ticket_type, subject=subject)
    session.add(ticket)
    await session.flush()
    return ticket


async def add_ticket_message(
    session: AsyncSession,
    ticket_id: int,
    sender_type: str,
    sender_id: int | str,
    content: str | None = None,
    file_id: str | None = None,
    message_type: str = "text",
) -> TicketMessage:
    msg = TicketMessage(
        ticket_id=ticket_id,
        sender_type=sender_type,
        sender_id=str(sender_id),
        message_type=message_type,
        content=content,
        file_id=file_id,
    )
    session.add(msg)
    await session.flush()
    return msg


async def get_open_tickets(session: AsyncSession) -> list[Ticket]:
    result = await session.execute(
        select(Ticket).where(Ticket.status == "open").order_by(Ticket.created_at.desc())
    )
    return list(result.scalars().all())


async def get_all_tickets(session: AsyncSession) -> list[Ticket]:
    result = await session.execute(select(Ticket).order_by(Ticket.created_at.desc()))
    return list(result.scalars().all())


async def get_ticket_by_id(session: AsyncSession, ticket_id: int) -> Ticket | None:
    result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
    return result.scalars().first()


async def close_ticket(session: AsyncSession, ticket_id: int, closed_by: str) -> None:
    await session.execute(
        update(Ticket)
        .where(Ticket.id == ticket_id)
        .values(status="closed", closed_at=datetime.utcnow(), closed_by=closed_by)
    )


async def reopen_ticket(session: AsyncSession, ticket_id: int) -> None:
    await session.execute(
        update(Ticket).where(Ticket.id == ticket_id).values(status="open", closed_at=None, closed_by=None)
    )


async def count_open_tickets(session: AsyncSession) -> int:
    result = await session.execute(select(func.count(Ticket.id)).where(Ticket.status == "open"))
    return result.scalar() or 0


# ─── Pending Channels ─────────────────────────────────────────────────────


async def save_pending_channel(
    session: AsyncSession,
    channel_id: str,
    telegram_id: int | str,
    channel_username: str | None = None,
    channel_title: str | None = None,
) -> PendingChannel:
    existing = await session.execute(
        select(PendingChannel).where(PendingChannel.channel_id == channel_id)
    )
    pc = existing.scalars().first()
    if pc:
        pc.telegram_id = str(telegram_id)
        pc.channel_username = channel_username
        pc.channel_title = channel_title
    else:
        pc = PendingChannel(
            channel_id=channel_id,
            telegram_id=str(telegram_id),
            channel_username=channel_username,
            channel_title=channel_title,
        )
        session.add(pc)
    await session.flush()
    return pc


async def get_pending_channel_by_telegram_id(session: AsyncSession, telegram_id: int | str) -> PendingChannel | None:
    result = await session.execute(
        select(PendingChannel).where(PendingChannel.telegram_id == str(telegram_id))
    )
    return result.scalars().first()


async def delete_pending_channel(session: AsyncSession, channel_id: str) -> None:
    await session.execute(delete(PendingChannel).where(PendingChannel.channel_id == channel_id))


async def delete_pending_channel_by_telegram_id(session: AsyncSession, telegram_id: int | str) -> None:
    await session.execute(delete(PendingChannel).where(PendingChannel.telegram_id == str(telegram_id)))


# ─── Pause Log ─────────────────────────────────────────────────────────────


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


# ─── Admin Router ──────────────────────────────────────────────────────────


async def get_admin_router(session: AsyncSession, admin_telegram_id: int | str) -> AdminRouter | None:
    result = await session.execute(
        select(AdminRouter).where(AdminRouter.admin_telegram_id == str(admin_telegram_id))
    )
    return result.scalars().first()


async def upsert_admin_router(
    session: AsyncSession, admin_telegram_id: int | str, **kwargs
) -> AdminRouter:
    tid = str(admin_telegram_id)
    router = await get_admin_router(session, tid)
    if router:
        for k, v in kwargs.items():
            setattr(router, k, v)
    else:
        router = AdminRouter(admin_telegram_id=tid, **kwargs)
        session.add(router)
    await session.flush()
    return router


# ─── Schedule Checks ──────────────────────────────────────────────────────


async def get_schedule_check_time(session: AsyncSession, region: str, queue: str) -> int:
    """Return the unix timestamp of the last schedule check for the given region/queue.

    Falls back to the current time if no record exists yet.
    """
    result = await session.execute(
        select(ScheduleCheck).where(ScheduleCheck.region == region, ScheduleCheck.queue == queue)
    )
    check = result.scalars().first()
    if check and check.last_checked_at:
        dt = check.last_checked_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp())
    return int(time.time())


async def update_schedule_check_time(session: AsyncSession, region: str, queue: str) -> None:
    """Upsert last_checked_at = now() for the given region/queue in schedule_checks."""
    result = await session.execute(
        select(ScheduleCheck).where(ScheduleCheck.region == region, ScheduleCheck.queue == queue)
    )
    check = result.scalars().first()
    if check:
        check.last_checked_at = datetime.now(UTC)
    else:
        session.add(ScheduleCheck(region=region, queue=queue, last_checked_at=datetime.now(UTC)))
    await session.flush()


# ─── Power Monitor ────────────────────────────────────────────────────────


async def change_power_state_and_get_duration(
    session: AsyncSession, telegram_id: int | str, new_state: str
) -> dict | None:
    """Atomically update power_state in user_power_tracking and return duration_minutes + power_changed_at."""
    tid = str(telegram_id)
    result = await session.execute(
        text("""
            WITH old AS (
                SELECT
                    upt.user_id,
                    upt.power_changed_at AS old_changed_at,
                    COALESCE(upt.pending_power_change_at, NOW()) AS new_changed_at
                FROM user_power_tracking upt
                JOIN users u ON u.id = upt.user_id
                WHERE u.telegram_id = :tid
            ),
            upd AS (
                UPDATE user_power_tracking upt
                SET
                    power_state = :new_state,
                    power_changed_at = old.new_changed_at,
                    pending_power_state = NULL,
                    pending_power_change_at = NULL
                FROM old
                WHERE upt.user_id = old.user_id
                RETURNING upt.power_changed_at
            )
            SELECT
                upd.power_changed_at,
                EXTRACT(EPOCH FROM (upd.power_changed_at - old.old_changed_at)) / 60 AS duration_minutes
            FROM upd
            CROSS JOIN old
        """),
        {"tid": tid, "new_state": new_state},
    )
    row = result.fetchone()
    if row:
        return {"power_changed_at": row[0], "duration_minutes": row[1]}
    return None


async def upsert_user_power_state(
    session: AsyncSession, telegram_id: int | str, **kwargs
) -> None:
    """Upsert a row in user_power_states."""
    tid = str(telegram_id)
    stmt = pg_insert(UserPowerState).values(telegram_id=tid, **kwargs)
    update_cols = {k: stmt.excluded[k] for k in kwargs}
    stmt = stmt.on_conflict_do_update(index_elements=["telegram_id"], set_=update_cols)
    await session.execute(stmt)


async def get_recent_user_power_states(
    session: AsyncSession,
) -> list[UserPowerState]:
    """Return UserPowerState rows updated within the last hour."""
    from datetime import timedelta
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    result = await session.execute(
        select(UserPowerState).where(UserPowerState.updated_at > cutoff)
    )
    return list(result.scalars().all())


async def add_power_history(
    session: AsyncSession,
    user_id: int,
    event_type: str,
    timestamp: int,
    duration_seconds: int | None,
) -> None:
    """Insert a record into power_history."""
    session.add(PowerHistory(
        user_id=user_id,
        event_type=event_type,
        timestamp=timestamp,
        duration_seconds=duration_seconds,
    ))
    await session.flush()
