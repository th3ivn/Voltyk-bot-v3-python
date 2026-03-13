from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.models import User as UserModel
from bot.db.queries import (
    add_power_history,
    change_power_state_and_get_duration,
    deactivate_user,
    get_recent_user_power_states,
    get_setting,
    get_users_with_ip,
    upsert_user_power_state,
)
from bot.db.session import async_session
from bot.services.api import fetch_schedule_data, find_next_event, parse_schedule_for_queue

logger = logging.getLogger(__name__)

KYIV_TZ = ZoneInfo("Europe/Kyiv")

# ─── In-memory state ──────────────────────────────────────────────────────

_user_states: dict[str, dict] = {}
_running = False
_is_checking = False

# Shared aiohttp connector — reused across all router checks
_http_connector: aiohttp.TCPConnector | None = None


def _get_http_connector() -> aiohttp.TCPConnector:
    """Return (or lazily create) the shared TCP connector."""
    global _http_connector
    if _http_connector is None or _http_connector.closed:
        _http_connector = aiohttp.TCPConnector(ssl=False, limit=100)
    return _http_connector


def _get_user_state(telegram_id: str) -> dict:
    """Get or create in-memory state for a user."""
    if telegram_id not in _user_states:
        _user_states[telegram_id] = {
            "current_state": None,
            "last_change_at": None,
            "consecutive_checks": 0,
            "is_first_check": True,
            "pending_state": None,
            "pending_state_time": None,
            "debounce_task": None,
            "instability_start": None,
            "switch_count": 0,
            "last_stable_state": None,
            "last_stable_at": None,
            "last_ping_time": None,
            "last_ping_success": None,
            "last_notification_at": None,
        }
    return _user_states[telegram_id]


# ─── Router check ─────────────────────────────────────────────────────────


async def _check_router_http(router_ip: str | None) -> bool | None:
    """Check if router is reachable via HTTP HEAD request (like the JS bot).

    Returns:
        True  — router responded (power is on).
        False — connection failed (power is likely off).
        None  — no IP configured; monitoring is disabled for this user.
    """
    if not router_ip:
        return None  # Monitoring disabled — no IP configured

    host = router_ip
    port = 80

    m = re.match(r"^(.+):(\d+)$", router_ip)
    if m:
        host = m.group(1)
        port = int(m.group(2))

    timeout_s = settings.POWER_PING_TIMEOUT_MS / 1000
    try:
        async with aiohttp.ClientSession(connector=_get_http_connector(), connector_owner=False) as http_session:
            async with http_session.head(
                f"http://{host}:{port}",
                timeout=aiohttp.ClientTimeout(total=timeout_s),
                allow_redirects=False,
            ):
                return True  # Any response → router is reachable → power is on
    except Exception:
        return False  # Connection failed → power is likely off


# ─── Helpers ──────────────────────────────────────────────────────────────


def _format_exact_duration(total_minutes: float) -> str:
    """Format duration in Ukrainian: 'X год Y хв'."""
    hours = int(total_minutes // 60)
    minutes = int(total_minutes % 60)

    if hours == 0:
        return "менше хвилини" if minutes == 0 else f"{minutes} хв"
    if minutes == 0:
        return f"{hours} год"
    return f"{hours} год {minutes} хв"


def _format_time(iso_str: str) -> str:
    """Format an ISO datetime string as HH:MM."""
    try:
        return datetime.fromisoformat(iso_str).strftime("%H:%M")
    except Exception:
        return "невідомо"


DEFAULT_CHECK_INTERVAL_S = 10
DEFAULT_DEBOUNCE_S = 5 * 60


async def _get_check_interval(session: AsyncSession) -> int:
    """Return check interval in seconds. Default 10s, overridable via admin panel (DB setting)."""
    val = await get_setting(session, "power_check_interval")
    if val:
        try:
            n = int(val)
            if n > 0:
                return n
        except (ValueError, TypeError):
            pass
    return DEFAULT_CHECK_INTERVAL_S


async def _get_debounce_seconds(session: AsyncSession) -> int:
    """Return debounce delay in seconds. Default 5 minutes, overridable via admin panel (DB setting)."""
    val = await get_setting(session, "power_debounce_minutes")
    if val:
        try:
            n = int(val)
            if n >= 0:
                return n * 60
        except (ValueError, TypeError):
            pass
    return DEFAULT_DEBOUNCE_S


# ─── Notification sender ──────────────────────────────────────────────────


async def _handle_power_state_change(
    bot: Bot,
    user,
    new_state: str,
    old_state: str | None,
    user_state: dict,
) -> None:
    """Handle a confirmed power state change: compute duration, format message, send."""
    try:
        now = datetime.now(KYIV_TZ)
        telegram_id = str(user.telegram_id)

        # ── Cooldown check ────────────────────────────────────────────
        should_notify = True
        if user_state["last_notification_at"]:
            try:
                last_notif = datetime.fromisoformat(user_state["last_notification_at"])
                if last_notif.tzinfo is None:
                    last_notif = last_notif.replace(tzinfo=KYIV_TZ)
                elapsed = (now - last_notif).total_seconds()
                if elapsed < settings.POWER_NOTIFICATION_COOLDOWN_S:
                    should_notify = False
                    remaining = int(settings.POWER_NOTIFICATION_COOLDOWN_S - elapsed)
                    logger.debug(
                        "User %s: Skipping notification (cooldown, %ds left)", telegram_id, remaining
                    )
            except Exception:
                pass

        # ── Atomic DB update + duration calculation ───────────────────
        power_result = None
        try:
            async with async_session() as session:
                power_result = await change_power_state_and_get_duration(session, telegram_id, new_state)
                await session.commit()
        except Exception as e:
            logger.error("DB error updating power state for user %s: %s", telegram_id, e)

        changed_at = now
        if power_result and power_result["power_changed_at"]:
            raw = power_result["power_changed_at"]
            if isinstance(raw, str):
                changed_at = datetime.fromisoformat(raw)
            else:
                changed_at = raw
            if changed_at.tzinfo is None:
                changed_at = changed_at.replace(tzinfo=UTC)
            changed_at = changed_at.astimezone(KYIV_TZ)

        # ── Duration text ─────────────────────────────────────────────
        duration_text = ""
        duration_s: int | None = None
        if power_result and power_result["duration_minutes"] is not None:
            total_min = float(power_result["duration_minutes"])
            duration_s = int(total_min * 60)
            duration_text = "менше хвилини" if total_min < 1 else _format_exact_duration(total_min)

        # ── Write to PowerHistory ─────────────────────────────────────
        try:
            async with async_session() as session:
                await add_power_history(
                    session,
                    user_id=user.id,
                    event_type=new_state,
                    timestamp=int(now.timestamp()),
                    duration_seconds=duration_s,
                )
                await session.commit()
        except Exception as e:
            logger.warning("Could not write PowerHistory for user %s: %s", telegram_id, e)

        # ── Schedule look-ahead ───────────────────────────────────────
        next_event = None
        is_scheduled_outage = False
        try:
            schedule_raw = await fetch_schedule_data(user.region)
            parsed = parse_schedule_for_queue(schedule_raw, user.queue)
            next_event = find_next_event(parsed)
            # If find_next_event returns "power_on" → we're currently inside a planned outage
            if next_event and next_event["type"] == "power_on":
                is_scheduled_outage = True
        except Exception as e:
            logger.warning("Schedule fetch error for user %s: %s", telegram_id, e)

        # ── Build schedule text ───────────────────────────────────────
        schedule_text = ""
        if new_state == "off":
            if is_scheduled_outage and next_event:
                schedule_text = f"\n🗓 Світло має з'явитися: <b>{_format_time(next_event['time'])}</b>"
            else:
                schedule_text = "\n⚠️ Позапланове відключення"
        else:
            if next_event and next_event["type"] == "power_off":
                start_str = _format_time(next_event["time"])
                if next_event.get("endTime"):
                    end_str = _format_time(next_event["endTime"])
                    schedule_text = f"\n🗓 Наступне планове: <b>{start_str} - {end_str}</b>"
                else:
                    schedule_text = f"\n🗓 Наступне планове: <b>{start_str}</b>"

        # ── Build message text ────────────────────────────────────────
        time_str = changed_at.strftime("%H:%M")
        if new_state == "off":
            message = f"🔴 <b>{time_str} Світло зникло</b>\n"
            message += f"🕓 Воно було {duration_text or '—'}"
            message += schedule_text
        else:
            message = f"🟢 <b>{time_str} Світло з'явилося</b>\n"
            message += f"🕓 Його не було {duration_text or '—'}"
            message += schedule_text

        # ── Send notifications ────────────────────────────────────────
        if should_notify:
            ns = user.notification_settings
            cc = user.channel_config

            # Send to private chat
            send_to_bot = True
            if ns:
                if new_state == "off" and not ns.notify_fact_off:
                    send_to_bot = False
                elif new_state == "on" and not ns.notify_fact_on:
                    send_to_bot = False

            if send_to_bot:
                try:
                    await bot.send_message(int(telegram_id), message, parse_mode="HTML")
                    logger.info("📱 Power notification sent to user %s (%s)", telegram_id, new_state)
                except TelegramForbiddenError:
                    logger.info("User %s blocked the bot — deactivating", telegram_id)
                    async with async_session() as session:
                        await deactivate_user(session, telegram_id)
                        await session.commit()
                except Exception as e:
                    logger.error("Error sending to user %s: %s", telegram_id, e)

            # Send to channel if configured and different from user's chat
            if cc and cc.channel_id and cc.channel_id != telegram_id:
                send_to_channel = True
                if new_state == "off" and not cc.ch_notify_fact_off:
                    send_to_channel = False
                elif new_state == "on" and not cc.ch_notify_fact_on:
                    send_to_channel = False
                if cc.channel_paused:
                    send_to_channel = False

                if send_to_channel:
                    try:
                        ch_id: int | str
                        try:
                            ch_id = int(cc.channel_id)
                        except (ValueError, TypeError):
                            ch_id = cc.channel_id
                        await bot.send_message(ch_id, message, parse_mode="HTML")
                        logger.info("📢 Power notification sent to channel %s", cc.channel_id)
                    except TelegramForbiddenError:
                        logger.warning("Channel %s is not accessible", cc.channel_id)
                    except Exception as e:
                        logger.error("Error sending to channel %s: %s", cc.channel_id, e)

            user_state["last_notification_at"] = now.isoformat()

        # ── Update stable state bookkeeping ──────────────────────────
        user_state["last_stable_at"] = changed_at.isoformat()
        user_state["last_stable_state"] = new_state
        user_state["instability_start"] = None
        user_state["switch_count"] = 0

    except Exception as e:
        logger.error(
            "Unexpected error in _handle_power_state_change for user %s: %s",
            getattr(user, "telegram_id", "?"),
            e,
        )


# ─── Per-user state machine ───────────────────────────────────────────────


async def _check_user_power(bot: Bot, user) -> None:
    """Run one check cycle for a single user and advance their state machine."""
    try:
        telegram_id = str(user.telegram_id)
        is_available = await _check_router_http(user.router_ip)

        if is_available is None:
            # No IP configured — skip this user silently
            return

        user_state = _get_user_state(telegram_id)
        user_state["last_ping_time"] = datetime.now(KYIV_TZ).isoformat()
        user_state["last_ping_success"] = True

        new_state = "on" if is_available else "off"

        # ── First check: seed from DB without sending notification ────
        if user_state["is_first_check"]:
            pt = user.power_tracking
            if pt and pt.power_state and pt.power_changed_at:
                user_state["current_state"] = pt.power_state
                user_state["last_stable_state"] = pt.power_state
                if not user_state["last_stable_at"]:
                    user_state["last_stable_at"] = (
                        pt.power_changed_at.isoformat() if pt.power_changed_at else None
                    )
                user_state["is_first_check"] = False
                logger.debug("User %s: Restored state from DB: %s", telegram_id, pt.power_state)
            else:
                # No DB record — set current state without notification
                user_state["current_state"] = new_state
                user_state["last_stable_state"] = new_state
                user_state["last_stable_at"] = None
                user_state["is_first_check"] = False
                user_state["consecutive_checks"] = 0
                try:
                    async with async_session() as session:
                        r = await session.execute(
                            select(UserModel).where(UserModel.telegram_id == telegram_id)
                        )
                        db_user = r.scalars().first()
                        if db_user and db_user.power_tracking:
                            db_user.power_tracking.power_state = new_state
                            db_user.power_tracking.power_changed_at = datetime.now(KYIV_TZ)
                            await session.commit()
                except Exception as e:
                    logger.warning("Could not write initial power state for user %s: %s", telegram_id, e)
            return

        # ── State unchanged ───────────────────────────────────────────
        if user_state["current_state"] == new_state:
            user_state["consecutive_checks"] = 0
            # Cancel pending state that contradicts the stable state (flapping)
            if user_state["pending_state"] is not None and user_state["pending_state"] != new_state:
                logger.debug(
                    "User %s: Cancelling pending %s → back to %s",
                    telegram_id, user_state["pending_state"], new_state,
                )
                task = user_state.get("debounce_task")
                if task and not task.done():
                    task.cancel()
                    user_state["debounce_task"] = None

                user_state["switch_count"] += 1
                user_state["pending_state"] = None
                user_state["pending_state_time"] = None

                try:
                    async with async_session() as session:
                        r = await session.execute(
                            select(UserModel).where(UserModel.telegram_id == telegram_id)
                        )
                        db_user = r.scalars().first()
                        if db_user and db_user.power_tracking:
                            db_user.power_tracking.pending_power_state = None
                            db_user.power_tracking.pending_power_change_at = None
                            await session.commit()
                except Exception as e:
                    logger.warning("Could not clear pending state for user %s: %s", telegram_id, e)
            return

        # ── Already waiting for this new state — do nothing ──────────
        if user_state["pending_state"] == new_state:
            return

        # ── New state differs from current and from pending ───────────
        # Cancel the previous debounce timer (if any)
        task = user_state.get("debounce_task")
        if task and not task.done():
            task.cancel()
            user_state["debounce_task"] = None

        if user_state["pending_state"] is None:
            user_state["instability_start"] = datetime.now(KYIV_TZ).isoformat()
            user_state["switch_count"] = 1
            logger.debug(
                "User %s: Instability start, %s → %s",
                telegram_id, user_state["current_state"], new_state,
            )
        else:
            user_state["switch_count"] += 1
            logger.debug("User %s: Switch #%d → %s", telegram_id, user_state["switch_count"], new_state)

        user_state["pending_state"] = new_state
        user_state["pending_state_time"] = datetime.now(KYIV_TZ).isoformat()

        # Persist pending to DB
        try:
            async with async_session() as session:
                r = await session.execute(
                    select(UserModel).where(UserModel.telegram_id == telegram_id)
                )
                db_user = r.scalars().first()
                if db_user and db_user.power_tracking:
                    db_user.power_tracking.pending_power_state = new_state
                    db_user.power_tracking.pending_power_change_at = datetime.now(KYIV_TZ)
                    await session.commit()
        except Exception as e:
            logger.warning("Could not set pending power state for user %s: %s", telegram_id, e)

        # Determine debounce delay from DB (fallback: 5 minutes)
        try:
            async with async_session() as session:
                debounce_s = await _get_debounce_seconds(session)
        except Exception:
            debounce_s = DEFAULT_DEBOUNCE_S
        if debounce_s == 0:
            debounce_s = settings.POWER_MIN_STABILIZATION_S
            logger.debug("User %s: Debounce=0, using %ds min stabilisation", telegram_id, debounce_s)
        else:
            logger.debug("User %s: Waiting %ds for %s to stabilise", telegram_id, debounce_s, new_state)

        old_state = user_state["current_state"]

        # ── Debounce confirm task ─────────────────────────────────────
        # Variables are captured by closure — no default args needed
        async def _confirm_state() -> None:
            try:
                await asyncio.sleep(debounce_s)
                logger.info("User %s: Debounce done — confirming %s", telegram_id, new_state)
                user_state["current_state"] = new_state
                user_state["consecutive_checks"] = 0
                user_state["debounce_task"] = None
                user_state["pending_state"] = None
                user_state["pending_state_time"] = None
                await _handle_power_state_change(bot, user, new_state, old_state, user_state)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.error("Error in debounce confirm for user %s: %s", telegram_id, exc)

        user_state["debounce_task"] = asyncio.create_task(_confirm_state())

    except Exception as e:
        logger.error(
            "Error checking power for user %s: %s",
            getattr(user, "telegram_id", "?"), e,
        )


# ─── Bulk check ───────────────────────────────────────────────────────────


async def _check_all_ips(bot: Bot) -> None:
    """Check all users with a router IP configured, with concurrency limiting."""
    global _is_checking
    if _is_checking:
        logger.debug("_check_all_ips already running, skipping")
        return
    _is_checking = True
    try:
        async with async_session() as session:
            users = await get_users_with_ip(session)

        if not users:
            return

        logger.debug("Checking %d users (max %d concurrent)", len(users), settings.POWER_MAX_CONCURRENT_PINGS)

        semaphore = asyncio.Semaphore(settings.POWER_MAX_CONCURRENT_PINGS)

        async def _with_semaphore(u):
            async with semaphore:
                await _check_user_power(bot, u)

        await asyncio.gather(*[_with_semaphore(u) for u in users])

    except Exception as e:
        logger.error("Error in _check_all_ips: %s", e)
    finally:
        _is_checking = False


# ─── State persistence ────────────────────────────────────────────────────


async def _save_user_state_to_db(telegram_id: str, state: dict) -> None:
    """Persist a single user's in-memory state to user_power_states."""
    try:
        last_notif = state.get("last_notification_at")
        last_notif_dt = None
        if last_notif:
            try:
                last_notif_dt = datetime.fromisoformat(last_notif)
            except Exception:
                pass

        async with async_session() as session:
            await upsert_user_power_state(
                session,
                telegram_id,
                current_state=state.get("current_state"),
                pending_state=state.get("pending_state"),
                pending_state_time=state.get("pending_state_time"),
                last_stable_state=state.get("last_stable_state"),
                last_stable_at=state.get("last_stable_at"),
                instability_start=state.get("instability_start"),
                switch_count=state.get("switch_count") or 0,
                last_notification_at=last_notif_dt,
            )
            await session.commit()
    except Exception as e:
        logger.error("Error saving state for user %s: %s", telegram_id, e)


async def _save_all_user_states() -> None:
    """Save all in-memory user states to DB (called every 5 minutes)."""
    count = 0
    for tid, state in list(_user_states.items()):
        await _save_user_state_to_db(tid, state)
        count += 1
    if count:
        logger.debug("💾 Saved %d user power states", count)


async def _restore_user_states() -> None:
    """Restore user states from DB rows updated in the last hour."""
    try:
        async with async_session() as session:
            rows = await get_recent_user_power_states(session)

        for row in rows:
            tid = str(row.telegram_id)
            last_notif_str = None
            if row.last_notification_at:
                if row.last_notification_at.tzinfo is None:
                    last_notif_str = row.last_notification_at.replace(tzinfo=KYIV_TZ).isoformat()
                else:
                    last_notif_str = row.last_notification_at.isoformat()

            _user_states[tid] = {
                "current_state": row.current_state,
                "last_change_at": None,
                "consecutive_checks": 0,
                "is_first_check": False,  # Already have state from DB
                "pending_state": row.pending_state,
                "pending_state_time": row.pending_state_time,
                "debounce_task": None,  # Timers cannot be restored
                "instability_start": row.instability_start,
                "switch_count": row.switch_count or 0,
                "last_stable_state": row.last_stable_state,
                "last_stable_at": row.last_stable_at,
                "last_ping_time": None,
                "last_ping_success": None,
                "last_notification_at": last_notif_str,
            }

        logger.info("🔄 Restored %d user power states", len(rows))
    except Exception as e:
        logger.error("Error restoring user states: %s", e)


# ─── Main loop ────────────────────────────────────────────────────────────


async def power_monitor_loop(bot: Bot) -> None:
    """Main power monitoring loop. Must receive the Bot instance to send messages."""
    global _running
    _running = True

    logger.info("⚡ Power monitor starting...")

    # Restore persisted states before the first check
    await _restore_user_states()

    logger.info("⚡ Power monitor started (default interval: %ds, admin-overridable via DB)", DEFAULT_CHECK_INTERVAL_S)

    # First check immediately
    await _check_all_ips(bot)

    last_save_at = asyncio.get_event_loop().time()
    save_interval_s = 5 * 60  # 5 minutes

    while _running:
        # Read interval from DB each iteration (admin panel can change it)
        try:
            async with async_session() as session:
                interval = await _get_check_interval(session)
        except Exception:
            interval = DEFAULT_CHECK_INTERVAL_S

        await asyncio.sleep(interval)

        if not _running:
            break

        try:
            await _check_all_ips(bot)
        except Exception as e:
            logger.error("Power monitor check error: %s", e)

        # Periodic state save (every 5 minutes)
        now_t = asyncio.get_event_loop().time()
        if now_t - last_save_at >= save_interval_s:
            await _save_all_user_states()
            last_save_at = now_t


def stop_power_monitor() -> None:
    """Stop the power monitor loop and cancel all pending debounce tasks."""
    global _running
    _running = False
    for state in _user_states.values():
        task = state.get("debounce_task")
        if task and not task.done():
            task.cancel()
    logger.info("⚡ Power monitor stopped")
