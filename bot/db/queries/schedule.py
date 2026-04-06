from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import PendingNotification, ScheduleCheck, ScheduleDailySnapshot
from bot.utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "get_schedule_check_time",
    "update_schedule_check_time",
    "get_schedule_hash",
    "get_daily_snapshot",
    "upsert_daily_snapshot",
    "save_pending_notification",
    "get_latest_pending_notification",
    "get_all_pending_region_queue_pairs",
    "mark_pending_notifications_sent",
    "delete_old_pending_notifications",
]


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
    """Atomically create or update the daily snapshot for a given region/queue/date.

    Uses INSERT ... ON CONFLICT DO UPDATE to avoid the race condition where
    two concurrent schedule-checker tasks could both observe 'not found' and
    both attempt an INSERT, violating the uq_schedule_daily_snapshot constraint.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stmt = (
        pg_insert(ScheduleDailySnapshot)
        .values(
            region=region,
            queue=queue,
            date=date,
            schedule_data=schedule_data,
            today_hash=today_hash,
            tomorrow_hash=tomorrow_hash,
        )
        .on_conflict_do_update(
            constraint="uq_schedule_daily_snapshot",
            set_={
                "schedule_data": schedule_data,
                "today_hash": today_hash,
                "tomorrow_hash": tomorrow_hash,
                "updated_at": now,
            },
        )
        .returning(ScheduleDailySnapshot)
    )
    result = await session.execute(stmt)
    await session.flush()
    return result.scalars().one()


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
