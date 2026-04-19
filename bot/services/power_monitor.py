from __future__ import annotations

import asyncio
import ipaddress
import re
from datetime import datetime, timezone

import aiohttp
import sentry_sdk
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.config import settings
from bot.db.models import User as UserModel
from bot.db.queries import (
    add_power_history,
    batch_upsert_user_power_states,
    change_power_state_and_get_duration,
    deactivate_ping_error_alert,
    deactivate_user,
    get_active_ping_error_alerts_cursor,
    get_active_power_users_by_region_queue_cursor,
    get_recent_user_power_states,
    get_setting,
    get_user_by_telegram_id,
    get_users_with_ip_cursor,
    update_ping_error_alert_time,
    upsert_user_power_state,
)
from bot.db.session import async_session
from bot.keyboards.inline import get_ip_ping_error_keyboard
from bot.services.api import fetch_schedule_data, find_next_event, parse_schedule_for_queue
from bot.utils.helpers import SSRF_BLOCKED_NETWORKS, retry_bot_call
from bot.utils.logger import get_logger
from bot.utils.metrics import DIRTY_STATES_COUNT, POWER_NOTIFICATIONS_SENT, USER_STATES_IN_MEMORY

logger = get_logger(__name__)

KYIV_TZ = settings.timezone

# ─── In-memory state ──────────────────────────────────────────────────────

# Hard cap on _user_states entries.  For 100k+ DAU with churn this protects
# against pathological growth (crashed eviction, orphan accounts, etc.).
# Excess entries are evicted LRU-style by last_change_at.
USER_STATES_MAX: int = 200_000
# Entries older than this are considered stale and evicted even if they fit
# under USER_STATES_MAX.  7 days matches the typical notification window.
USER_STATES_STALE_AFTER_S: int = 7 * 24 * 3600

_user_states: dict[str, dict] = {}
_user_states_lock: asyncio.Lock = asyncio.Lock()
# Tracks telegram_ids whose state changed since last DB flush.
# Must be modified only while _user_states_lock is held.
_dirty_states: set[str] = set()
_running = False
# Mutex that prevents concurrent _check_all_ips invocations.
# A bare boolean + timestamp was previously used, which had a TOCTOU race: two
# coroutines could both observe _is_checking=False before either set it True.
# asyncio.Lock() is FIFO and safe under asyncio's cooperative multitasking.
_check_all_ips_lock: asyncio.Lock = asyncio.Lock()

# Shared aiohttp connector — reused across all router checks
_http_connector: aiohttp.TCPConnector | None = None


def _get_http_connector() -> aiohttp.TCPConnector:
    """Return (or lazily create) the shared TCP connector."""
    global _http_connector
    if _http_connector is None or _http_connector.closed:
        _http_connector = aiohttp.TCPConnector(ssl=False, limit=settings.POWER_MAX_CONCURRENT_PINGS * 2)
    return _http_connector


def _get_user_state(telegram_id: str) -> dict:
    """Get or create in-memory state for a user.

    Must be called while *_user_states_lock* is held.  Newly created entries
    are automatically marked dirty so they are persisted on the next flush.
    """
    if telegram_id not in _user_states:
        _user_states[telegram_id] = {
            "current_state": None,
            "last_change_at": None,
            "consecutive_checks": 0,
            "is_first_check": True,
            "pending_state": None,
            "pending_state_time": None,
            "original_change_time": None,
            "debounce_task": None,
            "instability_start": None,
            "switch_count": 0,
            "last_stable_state": None,
            "last_stable_at": None,
            "last_ping_time": None,
            "last_ping_success": None,
            "last_notification_at": None,
        }
        _dirty_states.add(telegram_id)
    return _user_states[telegram_id]


def _state_last_touch_ts(state: dict) -> float:
    """Return a comparable timestamp for LRU eviction.

    Prefers ``last_change_at`` (actual state change) and falls back to
    ``last_ping_time``.  States with no timestamp sort to the top (evicted
    first) to clear orphans quickly.
    """
    for key in ("last_change_at", "last_ping_time"):
        raw = state.get(key)
        if not raw:
            continue
        if isinstance(raw, datetime):
            return raw.timestamp()
        try:
            return datetime.fromisoformat(raw).timestamp()
        except (TypeError, ValueError):
            continue
    return 0.0


async def _evict_stale_entries() -> None:
    """Enforce ``USER_STATES_MAX`` cap and drop entries older than TTL.

    Intended to run periodically from ``_check_all_ips``.  Must not be called
    while ``_user_states_lock`` is already held by the caller — it takes the
    lock itself.
    """
    now_ts = datetime.now(timezone.utc).timestamp()
    ttl_threshold = now_ts - USER_STATES_STALE_AFTER_S
    evicted_states: list[dict] = []

    async with _user_states_lock:
        # TTL eviction first — cheap linear scan.
        stale = [
            tid for tid, st in _user_states.items()
            if _state_last_touch_ts(st) and _state_last_touch_ts(st) < ttl_threshold
        ]
        for tid in stale:
            evicted_states.append(_user_states.pop(tid))
            _dirty_states.discard(tid)

        # Cap enforcement — LRU by last_touch_ts.
        overflow = len(_user_states) - USER_STATES_MAX
        if overflow > 0:
            sortable = sorted(
                _user_states.items(),
                key=lambda kv: _state_last_touch_ts(kv[1]),
            )
            for tid, _ in sortable[:overflow]:
                evicted_states.append(_user_states.pop(tid))
                _dirty_states.discard(tid)

    for state in evicted_states:
        task = state.get("debounce_task")
        if task and not task.done():
            task.cancel()
    if evicted_states:
        logger.info(
            "Evicted %d _user_states entries (cap=%d, ttl=%ds); remaining=%d",
            len(evicted_states), USER_STATES_MAX, USER_STATES_STALE_AFTER_S,
            len(_user_states),
        )


def _mark_dirty(telegram_id: str) -> None:
    """Mark a user state as needing DB persistence.

    Must be called while *_user_states_lock* is held.
    """
    _dirty_states.add(telegram_id)


# ─── Router check ─────────────────────────────────────────────────────────

# SSRF_BLOCKED_NETWORKS imported from bot.utils.helpers at the top of the file.
# RFC-1918 private ranges are intentionally ALLOWED — most home routers
# live on those subnets.


def _is_ssrf_blocked(host: str) -> bool:
    """Return True if *host* is in a blocked SSRF range.

    Only blocks loopback, link-local/cloud-metadata, broadcast, and reserved
    ranges.  RFC-1918 private ranges (192.168.x.x, 10.x.x.x, 172.16-31.x.x)
    are intentionally ALLOWED because most home routers use those addresses.
    """
    try:
        addr = ipaddress.IPv4Address(host)
    except (ValueError, ipaddress.AddressValueError):
        # Not a bare IPv4 address (e.g. a hostname) — let it through;
        # hostname-based SSRF is a separate concern handled at DNS level.
        return False
    return any(addr in net for net in SSRF_BLOCKED_NETWORKS)


async def check_router_http(router_ip: str | None) -> bool | None:
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

    if _is_ssrf_blocked(host):
        logger.warning("SSRF blocked: router IP %s is in a blocked network range", host)
        return False

    timeout_s = settings.POWER_PING_TIMEOUT_MS / 1000
    try:
        async with aiohttp.ClientSession(connector=_get_http_connector(), connector_owner=False) as http_session:
            async with http_session.head(
                f"http://{host}:{port}",
                timeout=aiohttp.ClientTimeout(total=timeout_s),
                allow_redirects=False,
            ):
                return True  # Any response → router is reachable → power is on
    except Exception as e:
        logger.debug("HTTP ping failed for %s:%s — %s", host, port, e)
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
    original_change_time: datetime | None = None,
) -> None:
    """Handle a confirmed power state change: compute duration, format message, send."""
    try:
        now = datetime.now(KYIV_TZ)
        telegram_id = str(user.telegram_id)

        # ── Session 1: Reload user + atomic state update + power history ──
        fresh_user = None
        power_result = None
        duration_s: int | None = None
        try:
            async with async_session() as session:
                fresh_user = await get_user_by_telegram_id(session, telegram_id)
                if not fresh_user:
                    logger.warning("User %s not found in DB, skipping notification", telegram_id)
                    return
                power_result = await change_power_state_and_get_duration(session, telegram_id, new_state)
                if power_result and power_result["duration_minutes"] is not None:
                    duration_s = int(float(power_result["duration_minutes"]) * 60)
                await add_power_history(
                    session,
                    user_id=fresh_user.id,
                    event_type=new_state,
                    timestamp=int(now.timestamp()),
                    duration_seconds=duration_s,
                )
                await session.commit()
        except Exception as e:
            logger.error("DB error processing power state change for user %s: %s", telegram_id, e, exc_info=True)
            if fresh_user is None:
                return

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
            except Exception as e:
                logger.debug("User %s: Cooldown calculation error: %s", telegram_id, e)

        # Time for the notification header — always use the real detection time
        event_time = original_change_time or now
        time_str = event_time.strftime("%H:%M")

        # changed_at — used only for bookkeeping (last_stable_at etc.)
        changed_at = original_change_time or now
        if power_result and power_result["power_changed_at"]:
            raw = power_result["power_changed_at"]
            if isinstance(raw, str):
                changed_at = datetime.fromisoformat(raw)
            else:
                changed_at = raw
            if changed_at.tzinfo is None:
                changed_at = changed_at.replace(tzinfo=timezone.utc)
            changed_at = changed_at.astimezone(KYIV_TZ)

        # ── Duration text ─────────────────────────────────────────────
        duration_text = ""
        if power_result and power_result["duration_minutes"] is not None:
            total_min = float(power_result["duration_minutes"])
            duration_text = "менше хвилини" if total_min < 1 else _format_exact_duration(total_min)

        # ── Schedule look-ahead ───────────────────────────────────────
        next_event = None
        is_scheduled_outage = False
        try:
            schedule_raw = await fetch_schedule_data(fresh_user.region)
            parsed = parse_schedule_for_queue(schedule_raw, fresh_user.queue)
            next_event = find_next_event(parsed)
            # If find_next_event returns "power_on" → we're currently inside a planned outage
            if next_event and next_event["type"] == "power_on":
                is_scheduled_outage = True
        except Exception as e:
            logger.warning("Schedule fetch error for user %s: %s", telegram_id, e)

        # ── Build schedule text ───────────────────────────────────────
        schedule_text = ""
        if new_state == "off":
            if is_scheduled_outage and next_event and next_event.get("time"):
                schedule_text = f"\n🗓 Світло має з'явитися: <b>{_format_time(next_event['time'])}</b>"
            else:
                schedule_text = "\n🔍 Графік не передбачав це відключення"
        else:
            if next_event and next_event["type"] == "power_off":
                start_str = _format_time(next_event["time"])
                if next_event.get("endTime"):
                    end_str = _format_time(next_event["endTime"])
                    schedule_text = f"\n🗓 Наступне планове: <b>{start_str} - {end_str}</b>"
                else:
                    schedule_text = f"\n🗓 Наступне планове: <b>{start_str}</b>"

        # ── Determine power_message_type ──────────────────────────────
        if new_state == "off":
            power_msg_type = "off_scheduled" if is_scheduled_outage else "off_unscheduled"
        else:
            power_msg_type = "on_with_next" if (next_event and next_event["type"] == "power_off") else "on_no_next"

        # ── Build message text ────────────────────────────────────────
        if new_state == "off":
            message = f"🔴 <b>{time_str} Світло зникло</b>\n"
            message += f"🕓 Воно було {duration_text or '—'}"
            message += schedule_text
        else:
            message = f"🟢 <b>{time_str} Світло з'явилося</b>\n"
            message += f"🕓 Його не було {duration_text or '—'}"
            message += schedule_text

        # ── Send notifications ────────────────────────────────────────
        bot_msg_id: int | None = None
        ch_msg_id: int | None = None
        user_deactivated = False
        if should_notify:
            ns = fresh_user.notification_settings
            cc = fresh_user.channel_config

            # Send to private chat
            send_to_bot = True
            if ns:
                if new_state == "off" and not ns.notify_fact_off:
                    send_to_bot = False
                elif new_state == "on" and not ns.notify_fact_on:
                    send_to_bot = False

            if send_to_bot:
                try:
                    sent = await retry_bot_call(lambda: bot.send_message(int(telegram_id), message, parse_mode="HTML"))
                    bot_msg_id = sent.message_id
                    POWER_NOTIFICATIONS_SENT.labels(state=new_state).inc()
                    logger.info("📱 Power notification sent to user %s (%s)", telegram_id, new_state)
                except TelegramForbiddenError:
                    logger.info("User %s blocked the bot — deactivating", telegram_id)
                    async with async_session() as session:
                        await deactivate_user(session, telegram_id)
                        await session.commit()
                    user_deactivated = True
                except Exception as e:
                    logger.error("Error sending to user %s: %s", telegram_id, e, exc_info=True)

            # Send to channel if configured and different from user's chat
            if not user_deactivated and cc and cc.channel_id and cc.channel_id != telegram_id:
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
                        ch_sent = await retry_bot_call(lambda: bot.send_message(ch_id, message, parse_mode="HTML"))
                        ch_msg_id = ch_sent.message_id
                        logger.info("📢 Power notification sent to channel %s", cc.channel_id)
                    except TelegramForbiddenError:
                        logger.warning("Channel %s is not accessible", cc.channel_id)
                    except Exception as e:
                        logger.error("Error sending to channel %s: %s", cc.channel_id, e, exc_info=True)

            user_state["last_notification_at"] = now.isoformat()
            _mark_dirty(telegram_id)

        # ── Session 2: Persist message IDs + deactivate ping alert ───
        if not user_deactivated and (bot_msg_id or ch_msg_id or new_state == "on"):
            try:
                async with async_session() as session:
                    if bot_msg_id or ch_msg_id:
                        r = await session.execute(
                            select(UserModel)
                            .options(
                                selectinload(UserModel.power_tracking),
                                selectinload(UserModel.channel_config),
                            )
                            .where(UserModel.telegram_id == telegram_id)
                        )
                        db_user = r.scalars().first()
                        if db_user and db_user.power_tracking:
                            if bot_msg_id:
                                if new_state == "off":
                                    db_user.power_tracking.alert_off_message_id = bot_msg_id
                                else:
                                    db_user.power_tracking.alert_on_message_id = bot_msg_id
                                db_user.power_tracking.bot_power_message_id = bot_msg_id
                                db_user.power_tracking.power_message_type = power_msg_type
                            if ch_msg_id:
                                db_user.power_tracking.ch_power_message_id = ch_msg_id
                        if db_user and db_user.channel_config and ch_msg_id:
                            db_user.channel_config.last_power_message_id = ch_msg_id
                    if new_state == "on":
                        await deactivate_ping_error_alert(session, telegram_id)
                    await session.commit()
            except Exception as e:
                logger.warning("Could not persist message IDs for user %s: %s", telegram_id, e)

        # ── Update stable state bookkeeping ──────────────────────────
        user_state["last_stable_at"] = changed_at
        user_state["last_stable_state"] = new_state
        user_state["instability_start"] = None
        user_state["switch_count"] = 0
        _mark_dirty(telegram_id)

    except Exception as e:
        logger.error(
            "Unexpected error in _handle_power_state_change for user %s: %s",
            getattr(user, "telegram_id", "?"),
            e,
            exc_info=True,
        )


# ─── Per-user state machine ───────────────────────────────────────────────


async def _check_user_power(bot: Bot, user, *, is_available: bool | None = None) -> None:
    """Run one check cycle for a single user and advance their state machine.

    If *is_available* is provided the HTTP ping is skipped — used when
    multiple users share the same router IP and the ping was already done.
    """
    try:
        telegram_id = str(user.telegram_id)
        if is_available is None:
            is_available = await check_router_http(user.router_ip)

        if is_available is None:
            # No IP configured — skip this user silently
            return

        async with _user_states_lock:
            user_state = _get_user_state(telegram_id)
            user_state["last_ping_time"] = datetime.now(KYIV_TZ).isoformat()
            user_state["last_ping_success"] = is_available
            _mark_dirty(telegram_id)

        new_state = "on" if is_available else "off"

        # ── First check: seed from DB without sending notification ────
        if user_state["is_first_check"]:
            pt = user.power_tracking
            if pt and pt.power_state and pt.power_changed_at:
                user_state["current_state"] = pt.power_state
                user_state["last_stable_state"] = pt.power_state
                if not user_state["last_stable_at"]:
                    user_state["last_stable_at"] = pt.power_changed_at
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
                user_state["original_change_time"] = None
                _mark_dirty(telegram_id)

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
            user_state["instability_start"] = datetime.now(KYIV_TZ)
            user_state["switch_count"] = 1
            logger.debug(
                "User %s: Instability start, %s → %s",
                telegram_id, user_state["current_state"], new_state,
            )
        else:
            user_state["switch_count"] += 1
            logger.debug("User %s: Switch #%d → %s", telegram_id, user_state["switch_count"], new_state)

        user_state["pending_state"] = new_state
        original_change_time = datetime.now(KYIV_TZ)
        user_state["pending_state_time"] = original_change_time
        user_state["original_change_time"] = original_change_time
        _mark_dirty(telegram_id)

        # Persist pending to DB
        try:
            async with async_session() as session:
                r = await session.execute(
                    select(UserModel).where(UserModel.telegram_id == telegram_id)
                )
                db_user = r.scalars().first()
                if db_user and db_user.power_tracking:
                    db_user.power_tracking.pending_power_state = new_state
                    db_user.power_tracking.pending_power_change_at = original_change_time
                    await session.commit()
        except Exception as e:
            logger.warning("Could not set pending power state for user %s: %s", telegram_id, e)

        # Determine debounce delay from DB (fallback: 5 minutes)
        try:
            async with async_session() as session:
                debounce_s = await _get_debounce_seconds(session)
        except Exception as e:
            logger.warning("Could not fetch debounce seconds, using default %ds: %s", DEFAULT_DEBOUNCE_S, e)
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

                async with _user_states_lock:
                    orig_dt = user_state.get("original_change_time")
                    user_state["current_state"] = new_state
                    user_state["consecutive_checks"] = 0
                    user_state["debounce_task"] = None
                    user_state["pending_state"] = None
                    user_state["pending_state_time"] = None
                    user_state["original_change_time"] = None
                    _mark_dirty(telegram_id)
                try:
                    await asyncio.wait_for(
                        _handle_power_state_change(bot, user, new_state, old_state, user_state, orig_dt),
                        timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    logger.error(
                        "Power state change handler timed out for user %s (%s→%s)",
                        telegram_id, old_state, new_state,
                    )
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.error("Error in debounce confirm for user %s: %s", telegram_id, exc, exc_info=True)

        async with _user_states_lock:
            user_state["debounce_task"] = asyncio.create_task(_confirm_state())

    except Exception as e:
        logger.error(
            "Error checking power for user %s: %s",
            getattr(user, "telegram_id", "?"), e,
            exc_info=True,
        )


# ─── Bulk check ───────────────────────────────────────────────────────────


async def _check_all_ips(bot: Bot) -> None:
    """Check all users with a router IP configured, with concurrency limiting.

    Uses an asyncio.Lock to prevent concurrent invocations.  The ``locked()``
    check and ``async with`` happen without an intermediate ``await``, which is
    safe under asyncio's cooperative multitasking — no TOCTOU race possible.
    """
    if _check_all_ips_lock.locked():
        logger.debug("_check_all_ips already running, skipping")
        return

    async with _check_all_ips_lock:
        try:
            # Cursor-based pagination: load users in batches to avoid loading
            # the entire table into memory at once.
            _BATCH = 500
            active_ids: set[str] = set()
            ip_groups: dict[str, list] = {}
            total_users = 0
            after_id = 0

            while True:
                try:
                    async with async_session() as session:
                        batch = await asyncio.wait_for(
                            get_users_with_ip_cursor(session, limit=_BATCH, after_id=after_id),
                            timeout=15.0,
                        )
                except asyncio.TimeoutError:
                    logger.error("User cursor query timed out at after_id=%d — aborting ping cycle", after_id)
                    return
                except Exception as e:
                    if "InvalidCachedStatementError" in type(e).__name__ or "cached statement" in str(e).lower():
                        logger.warning("Cached statement invalidated, retrying once: %s", e)
                        try:
                            async with async_session() as session:
                                batch = await asyncio.wait_for(
                                    get_users_with_ip_cursor(session, limit=_BATCH, after_id=after_id),
                                    timeout=15.0,
                                )
                        except Exception as retry_exc:
                            logger.error(
                                "Retry after InvalidCachedStatementError failed at after_id=%d: %s",
                                after_id, retry_exc, exc_info=True,
                            )
                            return
                    else:
                        raise
                if not batch:
                    break
                for user in batch:
                    active_ids.add(str(user.telegram_id))
                    ip_groups.setdefault(user.router_ip, []).append(user)  # type: ignore[arg-type]
                total_users += len(batch)
                if len(batch) < _BATCH:
                    break
                after_id = batch[-1].id

            if not ip_groups:
                return

            # Evict _user_states entries for users no longer in the active set.
            async with _user_states_lock:
                stale_ids = [tid for tid in _user_states if tid not in active_ids]
                evicted_states = []
                for tid in stale_ids:
                    evicted_states.append(_user_states.pop(tid))
                    _dirty_states.discard(tid)
            for state in evicted_states:
                task = state.get("debounce_task")
                if task and not task.done():
                    task.cancel()
            if stale_ids:
                logger.debug("Evicted %d stale _user_states entries", len(stale_ids))

            # Defense-in-depth: enforce hard cap + TTL in case active_ids-based
            # eviction misses (cursor iteration may skip concurrent inserts).
            await _evict_stale_entries()

            # Group users by router IP so each unique IP is pinged only once.
            logger.debug(
                "Checking %d unique IPs (%d users, max %d concurrent)",
                len(ip_groups), total_users, settings.POWER_MAX_CONCURRENT_PINGS,
            )

            semaphore = asyncio.Semaphore(settings.POWER_MAX_CONCURRENT_PINGS)

            async def _check_ip_group(ip: str, group_users: list) -> None:
                async with semaphore:
                    ping_result = await check_router_http(ip)
                for u in group_users:
                    await _check_user_power(bot, u, is_available=ping_result)

            await asyncio.gather(*[
                _check_ip_group(ip, group_users)
                for ip, group_users in ip_groups.items()
            ])

        except Exception as e:
            logger.error("Error in _check_all_ips: %s", e, exc_info=True)
            sentry_sdk.capture_exception(e)


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
        logger.error("Error saving state for user %s: %s", telegram_id, e, exc_info=True)


async def _save_all_user_states() -> None:
    """Persist only dirty (changed) user states to DB in a single batch upsert.

    Uses a snapshot of *_dirty_states* taken under the lock.  Entries added to
    *_dirty_states* after the snapshot is taken are preserved and will be saved
    on the next flush cycle — no changes are silently dropped.
    """
    async with _user_states_lock:
        if not _dirty_states:
            return
        save_ids: frozenset[str] = frozenset(_dirty_states)
        snapshot = [(tid, dict(_user_states[tid])) for tid in save_ids if tid in _user_states]

    if not snapshot:
        return

    rows: list[dict] = []
    for tid, state in snapshot:
        last_notif = state.get("last_notification_at")
        last_notif_dt = None
        if last_notif:
            try:
                last_notif_dt = datetime.fromisoformat(last_notif)
            except Exception:
                pass
        rows.append({
            "telegram_id": tid,
            "current_state": state.get("current_state"),
            "pending_state": state.get("pending_state"),
            "pending_state_time": state.get("pending_state_time"),
            "last_stable_state": state.get("last_stable_state"),
            "last_stable_at": state.get("last_stable_at"),
            "instability_start": state.get("instability_start"),
            "switch_count": state.get("switch_count") or 0,
            "last_notification_at": last_notif_dt,
        })

    try:
        async with async_session() as session:
            await batch_upsert_user_power_states(session, rows)
            await session.commit()
        # Remove only the IDs we successfully saved — new dirty entries are kept.
        # Use .difference_update() (in-place) to avoid Python treating it as a
        # local variable assignment (augmented -= would trigger UnboundLocalError).
        async with _user_states_lock:
            _dirty_states.difference_update(save_ids)
        logger.debug("💾 Saved %d dirty user power states", len(rows))
    except Exception as e:
        logger.error("Error batch-saving user power states: %s", e, exc_info=True)
        # _dirty_states is not cleared on failure — will retry next cycle


async def _restore_user_states() -> None:
    """Restore user states from DB rows updated in the last hour."""
    try:
        async with async_session() as session:
            rows = await get_recent_user_power_states(session)

        async with _user_states_lock:
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
                    "original_change_time": row.pending_state_time,  # Restored from pending_state_time
                    "debounce_task": None,  # Timers cannot be restored
                    "instability_start": row.instability_start,
                    "switch_count": row.switch_count or 0,
                    "last_stable_state": row.last_stable_state,
                    "last_stable_at": row.last_stable_at,
                    "last_ping_time": None,
                    "last_ping_success": None,
                    "last_notification_at": last_notif_str,
                }
                # Restored states are already in DB — do not mark as dirty
                _dirty_states.discard(tid)

        logger.info("🔄 Restored %d user power states", len(rows))
    except Exception as e:
        logger.error("Error restoring user states: %s", e, exc_info=True)


# ─── Main loop ────────────────────────────────────────────────────────────


async def _restart_pending_debounce_tasks(bot: Bot) -> None:
    """After restore, restart debounce tasks for users with pending state."""
    now = datetime.now(KYIV_TZ)
    try:
        async with async_session() as session:
            debounce_s = await _get_debounce_seconds(session)
    except Exception as e:
        logger.warning("Could not fetch debounce seconds on restart, using default: %s", e)
        debounce_s = DEFAULT_DEBOUNCE_S

    count = 0
    async with _user_states_lock:
        states_snapshot = list(_user_states.items())

    for telegram_id, user_state in states_snapshot:
        if user_state.get("pending_state") and user_state.get("debounce_task") is None:
            pending_state_time = user_state.get("pending_state_time")
            remaining_s: float = debounce_s

            if isinstance(pending_state_time, datetime):
                pending_at = pending_state_time
                if pending_at.tzinfo is None:
                    pending_at = pending_at.replace(tzinfo=KYIV_TZ)
                elapsed = (now - pending_at).total_seconds()
                remaining_s = max(0, debounce_s - elapsed)

            new_state = user_state["pending_state"]
            old_state = user_state.get("current_state")

            orig_dt = user_state.get("original_change_time") or pending_state_time

            logger.info(
                "User %s: Restarting pending debounce for %s (%.0fs remaining)",
                telegram_id, new_state, remaining_s,
            )

            async def _confirm_restored(
                tid=telegram_id, ns=new_state, os=old_state,
                rs=remaining_s, orig_dt=orig_dt,
            ) -> None:
                try:
                    await asyncio.sleep(rs)
                    async with _user_states_lock:
                        us = _user_states.get(tid)
                        if us is None or us.get("pending_state") != ns:
                            return
                        logger.info("User %s: Restored debounce done — confirming %s", tid, ns)
                        us["current_state"] = ns
                        us["consecutive_checks"] = 0
                        us["debounce_task"] = None
                        us["pending_state"] = None
                        us["pending_state_time"] = None
                        us["original_change_time"] = None
                        _mark_dirty(tid)
                    async with async_session() as session:
                        fresh_user = await get_user_by_telegram_id(session, tid)
                    if fresh_user:
                        await _handle_power_state_change(bot, fresh_user, ns, os, us, orig_dt)
                    else:
                        logger.warning("User %s not found in DB, skipping restored debounce notification", tid)
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    logger.error("Error in restored debounce confirm for user %s: %s", tid, exc, exc_info=True)

            user_state["debounce_task"] = asyncio.create_task(_confirm_restored())
            count += 1

    if count:
        logger.info("🔄 Restarted %d pending debounce tasks", count)


async def power_monitor_loop(bot: Bot) -> None:
    """Main power monitoring loop. Must receive the Bot instance to send messages."""
    global _running
    _running = True

    logger.info("⚡ Power monitor starting...")

    # Restore persisted states before the first check
    await _restore_user_states()

    # Restart debounce tasks for any pending states recovered from DB
    await _restart_pending_debounce_tasks(bot)

    logger.info("⚡ Power monitor started (default interval: %ds, admin-overridable via DB)", DEFAULT_CHECK_INTERVAL_S)

    # First check immediately
    try:
        await asyncio.wait_for(_check_all_ips(bot), timeout=300)
    except asyncio.TimeoutError:
        logger.error("Initial power monitor check timed out after 300s")
    except Exception as e:
        logger.error("Initial power monitor check error: %s", e, exc_info=True)

    last_save_at = asyncio.get_running_loop().time()
    save_interval_s = 60  # 1 minute — minimize data loss on crash

    while _running:
        # Read interval from DB each iteration (admin panel can change it)
        try:
            async with async_session() as session:
                interval = await _get_check_interval(session)
        except Exception as e:
            logger.warning("Could not read check interval from DB, using default: %s", e)
            interval = DEFAULT_CHECK_INTERVAL_S

        await asyncio.sleep(interval)

        if not _running:
            break

        try:
            await asyncio.wait_for(_check_all_ips(bot), timeout=300)
        except asyncio.TimeoutError:
            logger.error("Power monitor check timed out after 300s")
        except Exception as e:
            logger.error("Power monitor check error: %s", e, exc_info=True)
            sentry_sdk.capture_exception(e)

        # Periodic state save + metrics update
        now_t = asyncio.get_running_loop().time()
        if now_t - last_save_at >= save_interval_s:
            USER_STATES_IN_MEMORY.set(len(_user_states))
            DIRTY_STATES_COUNT.set(len(_dirty_states))
            await _save_all_user_states()
            last_save_at = now_t




def stop_power_monitor() -> None:
    """Stop the power monitor loop and cancel all pending debounce tasks."""
    global _running
    _running = False
    for state in list(_user_states.values()):
        task = state.get("debounce_task")
        if task and not task.done():
            task.cancel()
    logger.info("⚡ Power monitor stopped")


async def save_states_on_shutdown() -> None:
    """Persist all in-memory user states to DB on graceful shutdown."""
    global _http_connector
    await _save_all_user_states()
    # Close the shared TCP connector to release file descriptors.
    connector = _http_connector
    _http_connector = None
    if connector is not None and not connector.closed:
        close_task = asyncio.create_task(connector.close())
        try:
            await asyncio.shield(close_task)
        except asyncio.CancelledError:
            if not close_task.done():
                try:
                    await asyncio.wait_for(close_task, timeout=5.0)
                except (asyncio.TimeoutError, Exception) as e:
                    logger.debug("HTTP connector close timed out or failed on shutdown: %s", e)
            else:
                # Task already finished — retrieve result/exception to prevent
                # "Task exception was never retrieved" warning from asyncio.
                try:
                    await close_task
                except Exception as e:
                    logger.debug("HTTP connector close failed during shutdown: %s", e)
            raise
        except Exception as e:
            logger.debug("Error closing HTTP connector: %s", e)


# ─── Daily ping-error alerts ──────────────────────────────────────────────


async def daily_ping_error_loop(bot: Bot) -> None:
    """Щодня надсилає повідомлення про помилку пінгу користувачам де пінг не проходить."""
    global _running
    while _running:
        try:
            await asyncio.sleep(3600)
            if not _running:
                break
            await _send_daily_ping_error_alerts(bot)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("daily_ping_error_loop error: %s", e, exc_info=True)
            await asyncio.sleep(60)


async def _send_daily_ping_error_alerts(bot: Bot) -> None:
    """Send daily ping-error messages to users whose router hasn't responded in 24h."""
    support_url = settings.SUPPORT_CHANNEL_URL or None

    # Cursor-based pagination: avoid loading the entire alerts table into memory.
    _BATCH = 500
    after_id = 0
    now = datetime.now(timezone.utc)
    while True:
        try:
            async with async_session() as session:
                alerts = await get_active_ping_error_alerts_cursor(
                    session, limit=_BATCH, after_id=after_id
                )
        except Exception as e:
            logger.error("Could not fetch ping error alerts: %s", e, exc_info=True)
            return
        if not alerts:
            break
        for alert in alerts:
            try:
                last_at = alert.last_alert_at
                if last_at is not None:
                    if last_at.tzinfo is None:
                        last_at = last_at.replace(tzinfo=timezone.utc)
                    if (now - last_at).total_seconds() < 86400:
                        continue

                is_alive = await check_router_http(alert.router_ip)
                if is_alive:
                    async with async_session() as session:
                        await deactivate_ping_error_alert(session, alert.telegram_id)
                        await session.commit()
                    logger.info("Ping restored for user %s — deactivating alert", alert.telegram_id)
                    continue

                text = (
                    '<tg-emoji emoji-id="5312438206539536342">⚠️</tg-emoji> Моніторинг світла не працює\n\n'
                    "Протягом 24 годин бот не зміг з'єднатися з вашим\n"
                    f"роутером за адресою {alert.router_ip}\n\n"
                    "Можливі причини:\n"
                    "• Введена адреса неправильна\n"
                    "• IP-адреса не є статичною (білою)\n"
                    "• Роутер не налаштований на зовнішні підключення\n\n"
                    "Що можна зробити:\n"
                    "• Перевірити доступність IP або DDNS:\n"
                    '  <a href="https://2ip.ua/ua/services/ip-service/ping-traceroute">'
                    "https://2ip.ua/ua/services/ip-service/ping-traceroute</a>\n"
                    "• Увімкнути \"пінг через WAN-порт\" в налаштуваннях роутера\n"
                    "• Якщо використовуєте Port Forwarding — перевірити\n"
                    "  доступність порту:\n"
                    '  <a href="https://2ip.ua/ua/services/ip-service/port-check">'
                    "https://2ip.ua/ua/services/ip-service/port-check</a>\n\n"
                    "Якщо все налаштовано правильно — можливо, просто\n"
                    'не було світла весь цей час <tg-emoji emoji-id="5312230866993322219">🕯</tg-emoji>\n\n'
                    "Якщо проблема залишається — зверніться до підтримки,\n"
                    "адміністратор допоможе вам розібратися."
                )
                try:
                    await retry_bot_call(lambda: bot.send_message(
                        int(alert.telegram_id),
                        text,
                        reply_markup=get_ip_ping_error_keyboard(support_url=support_url),
                        parse_mode="HTML",
                    ))
                    async with async_session() as session:
                        await update_ping_error_alert_time(session, alert.telegram_id)
                        await session.commit()
                    logger.info("📡 Ping error alert sent to user %s", alert.telegram_id)
                except TelegramForbiddenError:
                    logger.info("User %s blocked the bot — deactivating user & ping alert", alert.telegram_id)
                    async with async_session() as session:
                        await deactivate_user(session, alert.telegram_id)
                        await deactivate_ping_error_alert(session, alert.telegram_id)
                        await session.commit()
                except Exception as e:
                    logger.error("Error sending ping error alert to user %s: %s", alert.telegram_id, e, exc_info=True)
            except Exception as e:
                logger.error("Error processing ping error alert for user %s: %s", alert.telegram_id, e, exc_info=True)
        if len(alerts) < _BATCH:
            break
        after_id = alerts[-1].id


# ─── Schedule change notification update ─────────────────────────────────


async def update_power_notifications_on_schedule_change(
    bot: Bot, region: str, queue: str
) -> None:
    """Update existing power notifications when the schedule changes for a region/queue.

    Edits the last power-off or power-on message for each affected user,
    replacing the schedule line to reflect the updated timetable.
    """
    try:
        schedule_raw = await fetch_schedule_data(region)
        if not schedule_raw:
            return
        parsed = parse_schedule_for_queue(schedule_raw, queue)
        next_event = find_next_event(parsed)
    except Exception as e:
        logger.warning("Could not fetch schedule for %s/%s: %s", region, queue, e)
        return

    # Cursor-based pagination: avoid loading the entire region/queue into memory.
    _BATCH = 500
    after_id = 0
    while True:
        try:
            async with async_session() as session:
                users = await get_active_power_users_by_region_queue_cursor(
                    session, region, queue, limit=_BATCH, after_id=after_id,
                )
        except Exception as e:
            logger.error("Error fetching users for schedule update %s/%s: %s", region, queue, e, exc_info=True)
            return
        if not users:
            break
        for user in users:
            telegram_id = str(user.telegram_id)
            pt = user.power_tracking
            cc = user.channel_config

            if not pt:
                continue

            current_state = pt.power_state
            # Prefer the new consolidated field; fall back to per-state legacy fields
            bot_msg_id = pt.bot_power_message_id
            if bot_msg_id is None:
                if current_state == "off":
                    bot_msg_id = pt.alert_off_message_id
                elif current_state == "on":
                    bot_msg_id = pt.alert_on_message_id
            if current_state not in ("off", "on"):
                continue

            if next_event and next_event["type"] == "power_off" and current_state == "on":
                start_str = _format_time(next_event["time"])
                if next_event.get("endTime"):
                    end_str = _format_time(next_event["endTime"])
                    new_schedule_line = f"\n🗓 Наступне планове: <b>{start_str} - {end_str}</b>"
                else:
                    new_schedule_line = f"\n🗓 Наступне планове: <b>{start_str}</b>"
            elif next_event and next_event["type"] == "power_on" and current_state == "off":
                new_schedule_line = (
                    f"\n🗓 Світло має з'явитися: <b>{_format_time(next_event['time'])}</b>"
                )
            else:
                new_schedule_line = None

            if bot_msg_id and new_schedule_line is not None:
                try:
                    duration_text = "—"
                    time_str = ""
                    if pt.power_changed_at:
                        try:
                            changed = pt.power_changed_at
                            if changed.tzinfo is None:
                                changed = changed.replace(tzinfo=timezone.utc)
                            elapsed_min = (datetime.now(timezone.utc) - changed).total_seconds() / 60
                            duration_text = _format_exact_duration(elapsed_min)
                            time_str = changed.astimezone(KYIV_TZ).strftime("%H:%M") + " "
                        except Exception:
                            pass
                    if current_state == "off":
                        base = (
                            f"🔴 <b>{time_str}Світло зникло</b>\n"
                            f"🕓 Воно було {duration_text or '—'}"
                            f"{new_schedule_line}"
                        )
                    else:
                        base = (
                            f"🟢 <b>{time_str}Світло з'явилося</b>\n"
                            f"🕓 Його не було {duration_text or '—'}"
                            f"{new_schedule_line}"
                        )

                    await bot.edit_message_text(
                        text=base,
                        chat_id=int(telegram_id),
                        message_id=bot_msg_id,
                        parse_mode="HTML",
                    )
                except TelegramBadRequest as e:
                    if "message is not modified" in str(e):
                        pass
                    elif "message to edit not found" in str(e):
                        try:
                            async with async_session() as session:
                                r = await session.execute(
                                    select(UserModel).where(UserModel.telegram_id == telegram_id)
                                )
                                db_user = r.scalars().first()
                                if db_user and db_user.power_tracking:
                                    if current_state == "off":
                                        db_user.power_tracking.alert_off_message_id = None
                                    else:
                                        db_user.power_tracking.alert_on_message_id = None
                                    db_user.power_tracking.bot_power_message_id = None
                                    await session.commit()
                        except Exception as clear_exc:
                            logger.warning(
                                "Could not clear stale bot message ID for user %s: %s",
                                telegram_id, clear_exc,
                                exc_info=clear_exc,
                            )
                    else:
                        logger.debug(
                            "Could not edit power message for user %s: %s", telegram_id, e
                        )
                except Exception as e:
                    logger.debug("Error updating power message for user %s: %s", telegram_id, e)

            ch_msg_id = (pt.ch_power_message_id if pt.ch_power_message_id is not None
                         else (cc.last_power_message_id if cc else None))
            if cc and cc.channel_id and ch_msg_id and new_schedule_line is not None:
                try:
                    ch_id: int | str
                    try:
                        ch_id = int(cc.channel_id)
                    except (ValueError, TypeError):
                        ch_id = cc.channel_id

                    duration_text = "—"
                    time_str = ""
                    if pt.power_changed_at:
                        try:
                            changed = pt.power_changed_at
                            if changed.tzinfo is None:
                                changed = changed.replace(tzinfo=timezone.utc)
                            elapsed_min = (datetime.now(timezone.utc) - changed).total_seconds() / 60
                            duration_text = _format_exact_duration(elapsed_min)
                            time_str = changed.astimezone(KYIV_TZ).strftime("%H:%M") + " "
                        except Exception:
                            pass
                    if current_state == "off":
                        base_ch = (
                            f"🔴 <b>{time_str}Світло зникло</b>\n"
                            f"🕓 Воно було {duration_text}"
                            f"{new_schedule_line}"
                        )
                    else:
                        base_ch = (
                            f"🟢 <b>{time_str}Світло з'явилося</b>\n"
                            f"🕓 Його не було {duration_text}"
                            f"{new_schedule_line}"
                        )

                    await bot.edit_message_text(
                        text=base_ch,
                        chat_id=ch_id,
                        message_id=ch_msg_id,
                        parse_mode="HTML",
                    )
                except TelegramBadRequest as e:
                    if "message is not modified" in str(e):
                        pass
                    elif "message to edit not found" in str(e):
                        try:
                            async with async_session() as session:
                                r = await session.execute(
                                    select(UserModel).where(UserModel.telegram_id == telegram_id)
                                )
                                db_user = r.scalars().first()
                                if db_user and db_user.channel_config:
                                    db_user.channel_config.last_power_message_id = None
                                if db_user and db_user.power_tracking:
                                    db_user.power_tracking.ch_power_message_id = None
                                await session.commit()
                        except Exception as clear_exc:
                            logger.warning(
                                "Could not clear stale channel message ID for user %s: %s",
                                telegram_id, clear_exc,
                                exc_info=clear_exc,
                            )
                    else:
                        logger.debug(
                            "Could not edit channel power message for user %s: %s", telegram_id, e
                        )
                except Exception as e:
                    logger.debug(
                        "Error updating channel power message for user %s: %s", telegram_id, e
                    )
        if len(users) < _BATCH:
            break
        after_id = users[-1].id
