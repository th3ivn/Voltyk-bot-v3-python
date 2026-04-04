from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import (
    AdminRouter,
    AdminTicketReminder,
    OutageHistory,
    PauseLog,
    PendingChannel,
    PendingNotification,
    PingErrorAlert,
    PowerHistory,
    ScheduleCheck,
    ScheduleDailySnapshot,
    ScheduleHistory,
    SentReminder,
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
from bot.utils.logger import get_logger

logger = get_logger(__name__)


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
        # Explicitly remove rows in tables whose FKs to users.id lack ON DELETE CASCADE
        # so that the subsequent session.delete(user) does not raise a constraint error.
        # (OutageHistory, PowerHistory, ScheduleHistory reference users.id without CASCADE.)
        await session.execute(delete(OutageHistory).where(OutageHistory.user_id == user.id))
        await session.execute(delete(PowerHistory).where(PowerHistory.user_id == user.id))
        await session.execute(delete(ScheduleHistory).where(ScheduleHistory.user_id == user.id))
        # ORM delete cascades to notification_settings, channel_config, power_tracking,
        # message_tracking (all configured with cascade="all, delete-orphan").
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


# ─── Settings ──────────────────────────────────────────────────────────────


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
        .values(status="closed", closed_at=datetime.now(timezone.utc).replace(tzinfo=None), closed_by=closed_by)
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
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    return int(time.time())


async def update_schedule_check_time(
    session: AsyncSession, region: str, queue: str, last_hash: str | None = None
) -> None:
    """Upsert last_checked_at = now() (and optionally last_hash) for the given region/queue.

    Uses ``INSERT … ON CONFLICT DO UPDATE`` to avoid the SELECT-then-INSERT
    race condition where two concurrent schedule-checker tasks for the same
    region/queue could both observe "not found" and both try to INSERT,
    causing a composite-primary-key violation.
    """
    now = datetime.now(timezone.utc)
    values: dict = {"region": region, "queue": queue, "last_checked_at": now}
    if last_hash is not None:
        values["last_hash"] = last_hash

    set_cols: dict = {"last_checked_at": now}
    if last_hash is not None:
        set_cols["last_hash"] = last_hash

    stmt = (
        pg_insert(ScheduleCheck)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["region", "queue"],
            set_=set_cols,
        )
    )
    await session.execute(stmt)
    await session.flush()


async def get_schedule_hash(session: AsyncSession, region: str, queue: str) -> str | None:
    """Return the stored last_hash for the given region/queue, or None."""
    result = await session.execute(
        select(ScheduleCheck.last_hash).where(
            ScheduleCheck.region == region, ScheduleCheck.queue == queue
        )
    )
    return result.scalar_one_or_none()


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


async def get_user_power_state(
    session: AsyncSession, telegram_id: int | str
) -> UserPowerState | None:
    """Return the UserPowerState row for a given telegram_id, or None."""
    tid = str(telegram_id)
    return await session.scalar(select(UserPowerState).where(UserPowerState.telegram_id == tid))


async def get_recent_user_power_states(
    session: AsyncSession,
) -> list[UserPowerState]:
    """Return UserPowerState rows updated within the last hour.

    Uses a tz-aware cutoff because ``updated_at`` is TIMESTAMPTZ — comparing
    with a naive datetime would let PostgreSQL interpret it as local time and
    return incorrect results when the DB server TZ differs from UTC.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
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


# ─── Schedule Daily Snapshots ─────────────────────────────────────────────


async def get_daily_snapshot(
    session: AsyncSession, region: str, queue: str, date: str
) -> ScheduleDailySnapshot | None:
    """Return the daily snapshot for a given region/queue/date (YYYY-MM-DD), or None."""
    result = await session.execute(
        select(ScheduleDailySnapshot).where(
            ScheduleDailySnapshot.region == region,
            ScheduleDailySnapshot.queue == queue,
            ScheduleDailySnapshot.date == date,
        )
    )
    return result.scalars().first()


async def upsert_daily_snapshot(
    session: AsyncSession,
    region: str,
    queue: str,
    date: str,
    schedule_data: str,
    today_hash: str | None,
    tomorrow_hash: str | None,
) -> ScheduleDailySnapshot:
    """Create or update the daily snapshot for a given region/queue/date."""
    snapshot = await get_daily_snapshot(session, region, queue, date)
    if snapshot:
        snapshot.schedule_data = schedule_data
        snapshot.today_hash = today_hash
        snapshot.tomorrow_hash = tomorrow_hash
        snapshot.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        snapshot = ScheduleDailySnapshot(
            region=region,
            queue=queue,
            date=date,
            schedule_data=schedule_data,
            today_hash=today_hash,
            tomorrow_hash=tomorrow_hash,
        )
        session.add(snapshot)
    await session.flush()
    return snapshot


# ─── Pending Notifications ────────────────────────────────────────────────


async def save_pending_notification(
    session: AsyncSession,
    region: str,
    queue: str,
    schedule_data: str,
    update_type: str | None,
    changes: str | None,
) -> PendingNotification:
    """Queue a schedule notification for the 06:00 flush."""
    notif = PendingNotification(
        region=region,
        queue=queue,
        schedule_data=schedule_data,
        update_type=update_type,
        changes=changes,
        status="pending",
    )
    session.add(notif)
    await session.flush()
    return notif


async def get_latest_pending_notification(
    session: AsyncSession, region: str, queue: str
) -> PendingNotification | None:
    """Return the most recently queued pending notification for a region/queue."""
    result = await session.execute(
        select(PendingNotification)
        .where(
            PendingNotification.region == region,
            PendingNotification.queue == queue,
            PendingNotification.status == "pending",
        )
        .order_by(PendingNotification.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def get_all_pending_region_queue_pairs(session: AsyncSession) -> list[tuple[str, str]]:
    """Return distinct (region, queue) pairs that have pending notifications."""
    result = await session.execute(
        select(PendingNotification.region, PendingNotification.queue)
        .where(PendingNotification.status == "pending")
        .distinct()
    )
    return list(result.all())  # type: ignore[arg-type]


async def mark_pending_notifications_sent(session: AsyncSession, region: str, queue: str) -> None:
    """Mark all pending notifications for a region/queue as sent."""
    await session.execute(
        update(PendingNotification)
        .where(
            PendingNotification.region == region,
            PendingNotification.queue == queue,
            PendingNotification.status == "pending",
        )
        .values(status="sent")
    )


async def delete_old_pending_notifications(session: AsyncSession, older_than_hours: int = 48) -> int:
    """Delete sent notifications and stuck pending notifications older than specified hours.

    Returns number of deleted rows.
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=older_than_hours)
    result = await session.execute(
        delete(PendingNotification).where(PendingNotification.created_at < cutoff)
    )
    return result.rowcount  # type: ignore[attr-defined]


# ─── Ping Error Alerts ────────────────────────────────────────────────────


async def upsert_ping_error_alert(
    session: AsyncSession, telegram_id: str, router_ip: str
) -> None:
    """Create or update a ping-error alert record for a user."""
    stmt = pg_insert(PingErrorAlert).values(
        telegram_id=telegram_id,
        router_ip=router_ip,
        is_active=True,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_ping_error_alert_user",
        set_={"router_ip": stmt.excluded.router_ip, "is_active": True},
    )
    await session.execute(stmt)


async def get_active_ping_error_alerts(session: AsyncSession) -> list[PingErrorAlert]:
    """Return all active ping-error alert records."""
    result = await session.execute(
        select(PingErrorAlert).where(PingErrorAlert.is_active.is_(True))
    )
    return list(result.scalars().all())


async def deactivate_ping_error_alert(session: AsyncSession, telegram_id: str) -> None:
    """Deactivate ping-error alert (when IP is deleted or ping succeeds)."""
    await session.execute(
        update(PingErrorAlert)
        .where(PingErrorAlert.telegram_id == telegram_id)
        .values(is_active=False)
    )


async def update_ping_error_alert_time(
    session: AsyncSession, telegram_id: str
) -> None:
    """Update last_alert_at to now for a user."""
    await session.execute(
        update(PingErrorAlert)
        .where(PingErrorAlert.telegram_id == telegram_id)
        .values(last_alert_at=datetime.now(timezone.utc))
    )


async def get_power_history_week(session: AsyncSession, user_id: int) -> list[PowerHistory]:
    """Return PowerHistory records for a user from the last 7 days."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    result = await session.execute(
        select(PowerHistory)
        .where(PowerHistory.user_id == user_id, PowerHistory.timestamp >= int(cutoff.timestamp()))
        .order_by(PowerHistory.timestamp.desc())
    )
    return list(result.scalars().all())


# ─── Admin Ticket Reminders ───────────────────────────────────────────────


async def create_admin_ticket_reminder(
    session: AsyncSession, ticket_id: int, admin_telegram_id: str
) -> AdminTicketReminder:
    """Create an admin reminder for a support ticket."""
    reminder = AdminTicketReminder(
        ticket_id=ticket_id,
        admin_telegram_id=admin_telegram_id,
    )
    session.add(reminder)
    await session.flush()
    return reminder


async def get_pending_admin_reminders(
    session: AsyncSession,
) -> list[AdminTicketReminder]:
    """Return unresolved reminders where last_reminder_at is older than 24 hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    result = await session.execute(
        select(AdminTicketReminder).where(
            AdminTicketReminder.is_resolved.is_(False),
            AdminTicketReminder.last_reminder_at <= cutoff,
        )
    )
    return list(result.scalars().all())


async def resolve_admin_ticket_reminder(
    session: AsyncSession, ticket_id: int
) -> None:
    """Mark all reminders for a ticket as resolved."""
    await session.execute(
        update(AdminTicketReminder)
        .where(AdminTicketReminder.ticket_id == ticket_id)
        .values(is_resolved=True)
    )


# ─── Sent Reminders ───────────────────────────────────────────────────────


async def check_reminder_sent(
    session: AsyncSession,
    telegram_id: str,
    period_key: str,
    reminder_type: str,
) -> bool:
    """Return True if this reminder was already sent for the given event anchor."""
    result = await session.execute(
        select(SentReminder.id).where(
            SentReminder.telegram_id == telegram_id,
            SentReminder.period_key == period_key,
            SentReminder.reminder_type == reminder_type,
        ).limit(1)
    )
    return result.scalar() is not None


async def mark_reminder_sent(
    session: AsyncSession,
    telegram_id: str,
    region: str,
    queue: str,
    period_key: str,
    reminder_type: str,
) -> None:
    """Record that a reminder was sent.  Uses INSERT … ON CONFLICT DO NOTHING for idempotency."""
    stmt = pg_insert(SentReminder).values(
        telegram_id=telegram_id,
        region=region,
        queue=queue,
        period_key=period_key,
        reminder_type=reminder_type,
    ).on_conflict_do_nothing(constraint="uq_sent_reminder")
    await session.execute(stmt)


async def cleanup_old_reminders(session: AsyncSession, older_than_hours: int = 48) -> int:
    """Delete sent-reminder rows older than *older_than_hours*.

    Returns the number of deleted rows.
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=older_than_hours)
    result = await session.execute(
        delete(SentReminder).where(SentReminder.created_at < cutoff)
    )
    return result.rowcount  # type: ignore[attr-defined]


async def get_active_reminder_anchors(
    session: AsyncSession,
    within_hours: int = 48,
) -> list[tuple[str, str]]:
    """Return the latest ``(telegram_id, period_key)`` per user for recent reminders.

    Uses ``DISTINCT ON`` (PostgreSQL-specific) so deduplication happens at the
    database level rather than in Python.  Used to reconstruct pending-cleanup
    state after a bot restart: callers should check whether each ``period_key``
    represents a past event and, if so, delete the reminder message from Telegram.
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=within_hours)
    result = await session.execute(
        select(SentReminder.telegram_id, SentReminder.period_key)
        .where(SentReminder.created_at > cutoff)
        .distinct(SentReminder.telegram_id)
        .order_by(SentReminder.telegram_id, SentReminder.created_at.desc())
    )
    return [(row.telegram_id, row.period_key) for row in result]


