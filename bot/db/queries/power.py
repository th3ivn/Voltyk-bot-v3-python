from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import PingErrorAlert, PowerHistory, UserPowerState
from bot.utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "change_power_state_and_get_duration",
    "upsert_user_power_state",
    "batch_upsert_user_power_states",
    "get_user_power_state",
    "get_recent_user_power_states",
    "add_power_history",
    "get_power_history_week",
    "upsert_ping_error_alert",
    "get_active_ping_error_alerts",
    "get_active_ping_error_alerts_cursor",
    "deactivate_ping_error_alert",
    "update_ping_error_alert_time",
]


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


async def batch_upsert_user_power_states(
    session: AsyncSession,
    states: list[dict],
) -> None:
    """Upsert multiple user_power_states rows in a single INSERT ... ON CONFLICT statement.

    Each element of *states* must have a ``telegram_id`` key plus any subset of
    the UserPowerState columns.  If *states* is empty the function returns
    immediately without touching the database.
    """
    if not states:
        return
    stmt = pg_insert(UserPowerState).values(states)
    # Build the SET clause from the union of all column names except the PK.
    update_keys = {k for row in states for k in row if k != "telegram_id"}
    update_cols = {k: stmt.excluded[k] for k in update_keys}
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


async def get_power_history_week(session: AsyncSession, user_id: int) -> list[PowerHistory]:
    """Return PowerHistory records for a user from the last 7 days."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    result = await session.execute(
        select(PowerHistory)
        .where(PowerHistory.user_id == user_id, PowerHistory.timestamp >= int(cutoff.timestamp()))
        .order_by(PowerHistory.timestamp.desc())
    )
    return list(result.scalars().all())


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


async def get_active_ping_error_alerts_cursor(
    session: AsyncSession,
    limit: int = 500,
    after_id: int = 0,
) -> list[PingErrorAlert]:
    """Cursor-based version of get_active_ping_error_alerts.

    Returns active PingErrorAlert rows where id > after_id, ordered by id.
    Pass ``after_id=batch[-1].id`` for the next page.
    """
    result = await session.execute(
        select(PingErrorAlert)
        .where(PingErrorAlert.is_active.is_(True), PingErrorAlert.id > after_id)
        .order_by(PingErrorAlert.id)
        .limit(limit)
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
