from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import BufferedInputFile

from bot.config import settings
from bot.constants.regions import REGIONS
from bot.db.queries import (
    get_active_users_by_region,
    get_active_users_paginated,
    get_all_pending_region_queue_pairs,
    get_daily_snapshot,
    get_latest_pending_notification,
    get_schedule_check_time,
    get_schedule_hash,
    get_user_by_telegram_id,
    mark_pending_notifications_sent,
    save_pending_notification,
    update_schedule_check_time,
    upsert_daily_snapshot,
)
from bot.db.session import async_session
from bot.keyboards.inline import get_reminder_keyboard, get_schedule_view_keyboard
from bot.services.api import (
    calculate_schedule_hash,
    check_source_repo_updated,
    fetch_schedule_data,
    fetch_schedule_image,
    find_next_event,
    parse_schedule_for_queue,
)
from bot.utils.helpers import retry_bot_call
from bot.utils.html_to_entities import append_timestamp, html_to_entities, to_aiogram_entities
from bot.utils.logger import get_logger

logger = get_logger(__name__)

_running = False

DEFAULT_SCHEDULE_CHECK_INTERVAL_S = 60
_DB_SCAN_BATCH_SIZE = 1000  # batch size for scanning active users in background loops
KYIV_TZ = ZoneInfo("Europe/Kyiv")


# ─── Helpers ──────────────────────────────────────────────────────────────


def _is_quiet_hours() -> bool:
    """Return True if the current Kyiv time is in the quiet window 00:00–05:59."""
    return datetime.now(KYIV_TZ).hour < 6


def _kyiv_date_str() -> str:
    """Return today's date string (YYYY-MM-DD) in Kyiv timezone."""
    return datetime.now(KYIV_TZ).strftime("%Y-%m-%d")


def _yesterday_date_str() -> str:
    """Return yesterday's date string (YYYY-MM-DD) in Kyiv timezone."""
    return (datetime.now(KYIV_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")


def _tomorrow_date_str() -> str:
    """Return tomorrow's date string (YYYY-MM-DD) in Kyiv timezone."""
    return (datetime.now(KYIV_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")


def _filter_events_for_date(events: list[dict], date_str: str) -> list[dict]:
    """Return events whose start time falls on the given date (YYYY-MM-DD)."""
    return [ev for ev in events if ev["start"][:10] == date_str]


def _compute_date_hash(events: list[dict], date_str: str) -> str | None:
    """Hash of events for a specific date; returns None if there are no events."""
    day_events = _filter_events_for_date(events, date_str)
    if not day_events:
        return None
    return calculate_schedule_hash(day_events)


def _compute_changes(old_events: list[dict], new_events: list[dict]) -> dict:
    """Return a changes dict with 'added' and 'removed' events."""
    old_keys = {f"{e['start']}_{e['end']}" for e in old_events}
    new_keys = {f"{e['start']}_{e['end']}" for e in new_events}
    added = [e for e in new_events if f"{e['start']}_{e['end']}" not in old_keys]
    removed = [e for e in old_events if f"{e['start']}_{e['end']}" not in new_keys]
    return {"added": added, "removed": removed}


# ─── Interval ─────────────────────────────────────────────────────────────


def _merge_tomorrow_events_into_changes(
    changes: dict, events: list[dict], tomorrow_date: str
) -> None:
    """Add tomorrow's events to changes['added'] if not already present."""
    tomorrow_events = _filter_events_for_date(events, tomorrow_date)
    added_keys = {f"{e['start']}_{e['end']}" for e in changes["added"]}
    for ev in tomorrow_events:
        if f"{ev['start']}_{ev['end']}" not in added_keys:
            changes["added"].append(ev)


# ─── Interval ─────────────────────────────────────────────────────────────


async def _get_schedule_interval() -> int:
    """Read schedule check interval from DB (set via admin panel). Falls back to settings."""
    from bot.db.queries import get_setting

    try:
        async with async_session() as session:
            val = await get_setting(session, "schedule_check_interval")
        if val:
            n = int(val)
            if n > 0:
                return n
    except Exception as e:
        logger.warning("Could not read schedule interval from DB: %s", e)
    return settings.SCHEDULE_CHECK_INTERVAL_S


# ─── Main loop ────────────────────────────────────────────────────────────


async def schedule_checker_loop(bot: Bot) -> None:
    global _running
    _running = True
    logger.info("Schedule checker started")

    while _running:
        interval = await _get_schedule_interval()
        try:
            await _check_all_schedules(bot, interval)
        except Exception as e:
            logger.error("Schedule check error: %s", e)
            import sentry_sdk
            sentry_sdk.capture_exception(e)

        logger.debug("Next schedule check in %ds", interval)
        await asyncio.sleep(interval)


async def _check_all_schedules(
    bot: Bot, interval: int = DEFAULT_SCHEDULE_CHECK_INTERVAL_S
) -> None:
    """Fetch schedule for each unique region/queue pair and notify on changes."""
    has_update = await check_source_repo_updated()
    if not has_update:
        logger.debug("No new commits in source repo, skipping full check")
        return
    logger.info("Source repo updated, checking all schedules")

    region_queue_pairs: set[tuple[str, str]] = set()
    batch_size_inner = _DB_SCAN_BATCH_SIZE
    offset = 0
    while True:
        async with async_session() as session:
            batch = await get_active_users_paginated(session, limit=batch_size_inner, offset=offset)
        if not batch:
            break
        for user in batch:
            region_queue_pairs.add((user.region, user.queue))
        if len(batch) < batch_size_inner:
            break
        offset += batch_size_inner

    for region, queue in region_queue_pairs:
        try:
            await _check_single_queue(bot, region, queue, interval_s=interval)
        except Exception as e:
            logger.error("Error checking schedule for %s/%s: %s", region, queue, e)
            import sentry_sdk
            sentry_sdk.capture_exception(e)


async def _check_single_queue(
    bot: Bot,
    region: str,
    queue: str,
    interval_s: int = DEFAULT_SCHEDULE_CHECK_INTERVAL_S,
) -> None:
    data = await fetch_schedule_data(region, force_refresh=True)
    if not data:
        return

    sched = parse_schedule_for_queue(data, queue)
    events = sched.get("events", [])
    new_all_hash = calculate_schedule_hash(events)

    today_date = _kyiv_date_str()
    yesterday_date = _yesterday_date_str()
    tomorrow_date = _tomorrow_date_str()

    # Single read session — fetch all needed DB state upfront
    async with async_session() as session:
        stored_hash = await get_schedule_hash(session, region, queue)
        snapshot = await get_daily_snapshot(session, region, queue, today_date)
        yesterday_snapshot = await get_daily_snapshot(session, region, queue, yesterday_date)

    if stored_hash is not None and stored_hash == new_all_hash:
        # No change in overall hash — update timestamp and refresh daily snapshot if needed
        async with async_session() as session:
            await update_schedule_check_time(session, region, queue)
            if snapshot is None:
                new_today_hash_check = _compute_date_hash(events, today_date)
                new_tomorrow_hash_check = _compute_date_hash(events, tomorrow_date)
                await upsert_daily_snapshot(
                    session, region, queue, today_date,
                    json.dumps(sched), new_today_hash_check, new_tomorrow_hash_check,
                )
            await session.commit()
        return

    # Hash changed — determine what changed
    logger.info("Schedule changed for region=%s queue=%s", region, queue)

    new_today_hash = _compute_date_hash(events, today_date)
    new_tomorrow_hash = _compute_date_hash(events, tomorrow_date)

    update_type: dict = {}
    changes: dict = {"added": []}

    if snapshot is None:
        # First check of the day — compare today's events with yesterday's tomorrow data
        if yesterday_snapshot is not None:
            try:
                yesterday_sched = json.loads(yesterday_snapshot.schedule_data)
                yesterday_tomorrow_events = _filter_events_for_date(
                    yesterday_sched.get("events", []), today_date
                )
                new_today_events = _filter_events_for_date(events, today_date)
                if yesterday_snapshot.tomorrow_hash != new_today_hash:
                    update_type["todayUpdated"] = True
                    changes = _compute_changes(yesterday_tomorrow_events, new_today_events)
            except Exception as e:
                logger.warning("Failed to compare with yesterday snapshot: %s", e)

        if new_tomorrow_hash is not None:
            update_type["tomorrowAppeared"] = True
            _merge_tomorrow_events_into_changes(changes, events, tomorrow_date)

        if update_type.get("tomorrowAppeared") and not update_type.get("todayUpdated"):
            update_type["todayUnchanged"] = True
    else:
        # Snapshot exists — compare with stored hashes
        if snapshot.today_hash != new_today_hash:
            update_type["todayUpdated"] = True
            try:
                old_sched = json.loads(snapshot.schedule_data)
                old_today_events = _filter_events_for_date(old_sched.get("events", []), today_date)
                new_today_events = _filter_events_for_date(events, today_date)
                changes = _compute_changes(old_today_events, new_today_events)
            except Exception as e:
                logger.warning("Failed to compute today changes: %s", e)

        if snapshot.tomorrow_hash is None and new_tomorrow_hash is not None:
            update_type["tomorrowAppeared"] = True
            _merge_tomorrow_events_into_changes(changes, events, tomorrow_date)
        elif snapshot.tomorrow_hash is not None and new_tomorrow_hash != snapshot.tomorrow_hash:
            if new_tomorrow_hash is None:
                update_type["tomorrowCancelled"] = True
            else:
                update_type["tomorrowUpdated"] = True
            try:
                old_sched = json.loads(snapshot.schedule_data)
                old_tomorrow_events = _filter_events_for_date(old_sched.get("events", []), tomorrow_date)
                new_tomorrow_events = _filter_events_for_date(events, tomorrow_date)
                tomorrow_changes = _compute_changes(old_tomorrow_events, new_tomorrow_events)
                for ev in tomorrow_changes.get("added", []):
                    key = f"{ev['start']}_{ev['end']}"
                    if key not in {f"{e['start']}_{e['end']}" for e in changes["added"]}:
                        changes["added"].append(ev)
                changes.setdefault("removed", []).extend(tomorrow_changes.get("removed", []))
            except Exception as e:
                logger.warning("Failed to compute tomorrow changes: %s", e)

        tomorrow_changed = update_type.get("tomorrowAppeared") or update_type.get("tomorrowUpdated") or update_type.get("tomorrowCancelled")
        if tomorrow_changed and not update_type.get("todayUpdated"):
            update_type["todayUnchanged"] = True

    # Fallback: hash changed but snapshots were absent (e.g. first run) — always notify
    if not update_type:
        update_type["todayUpdated"] = True

    sched_data_json = json.dumps(sched)
    update_type_json = json.dumps(update_type)
    changes_json = json.dumps(changes) if (changes.get("added") or changes.get("removed")) else None

    quiet = _is_quiet_hours()

    # Single write session — update hash, snapshot, and optionally queue notification
    async with async_session() as session:
        await update_schedule_check_time(session, region, queue, last_hash=new_all_hash)
        await upsert_daily_snapshot(
            session, region, queue, today_date,
            sched_data_json, new_today_hash, new_tomorrow_hash,
        )
        if quiet:
            await save_pending_notification(
                session, region, queue, sched_data_json, update_type_json, changes_json
            )
        await session.commit()

    if quiet:
        logger.info("Queued notification for %s/%s (quiet hours)", region, queue)
        return

    # Fetch users and send notifications
    async with async_session() as session:
        users_in_queue = await get_active_users_by_region(session, region, queue=queue)

    await _send_notifications_to_users(
        bot, users_in_queue, sched, update_type, changes, is_daily_planned=False
    )

    # Update existing power notifications to reflect new schedule
    try:
        from bot.services.power_monitor import update_power_notifications_on_schedule_change
        await update_power_notifications_on_schedule_change(bot, region, queue)
    except Exception as e:
        logger.warning("Error updating power notifications on schedule change for %s/%s: %s", region, queue, e)


# ─── 06:00 daily flush ────────────────────────────────────────────────────


async def flush_pending_notifications(bot: Bot) -> None:
    """Send all queued overnight notifications at 06:00.

    For each (region, queue) with pending rows, take the latest and send to
    all subscribed users. For pairs with no pending rows, send a fresh daily
    planned message.
    """
    logger.info("Running 06:00 notification flush")

    async with async_session() as session:
        pending_pairs = await get_all_pending_region_queue_pairs(session)
    pending_set = set(tuple(p) for p in pending_pairs)

    # Collect all active region/queue pairs
    all_pairs: set[tuple[str, str]] = set()
    offset = 0
    batch_size_inner = _DB_SCAN_BATCH_SIZE
    while True:
        async with async_session() as session:
            batch = await get_active_users_paginated(session, limit=batch_size_inner, offset=offset)
        if not batch:
            break
        for user in batch:
            all_pairs.add((user.region, user.queue))
        if len(batch) < batch_size_inner:
            break
        offset += batch_size_inner

    for region, queue in all_pairs:
        try:
            if (region, queue) in pending_set:
                # Fetch users and pending notification in a single session
                async with async_session() as session:
                    users_in_queue = await get_active_users_by_region(session, region, queue=queue)
                    notif = await get_latest_pending_notification(session, region, queue)

                if notif:
                    sched = json.loads(notif.schedule_data)
                    update_type = json.loads(notif.update_type) if notif.update_type else {}
                    changes = json.loads(notif.changes) if notif.changes else {"added": [], "removed": []}

                    await _send_notifications_to_users(
                        bot, users_in_queue, sched, update_type, changes, is_daily_planned=False
                    )

                    async with async_session() as session:
                        await mark_pending_notifications_sent(session, region, queue)
                        await session.commit()
            else:
                # No overnight changes — send daily planned message
                async with async_session() as session:
                    users_in_queue = await get_active_users_by_region(session, region, queue=queue)
                data = await fetch_schedule_data(region, force_refresh=True)
                if not data:
                    continue
                sched = parse_schedule_for_queue(data, queue)

                await _send_notifications_to_users(
                    bot, users_in_queue, sched, {}, {"added": []}, is_daily_planned=True
                )

        except Exception as e:
            logger.error("Error flushing notifications for %s/%s: %s", region, queue, e)

    logger.info("06:00 flush complete")


async def daily_flush_loop(bot: Bot) -> None:
    """Wait until next 06:00 Kyiv time, then flush pending notifications, repeat."""
    logger.info("Daily flush loop started")
    while _running:
        now = datetime.now(KYIV_TZ)
        target = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        logger.debug("Daily flush will run in %.0f seconds", (target - now).total_seconds())
        # Sleep in 60-second chunks, recalculating remaining time each iteration
        # to avoid drift and allow clean shutdown via _running.
        while _running:
            remaining = (target - datetime.now(KYIV_TZ)).total_seconds()
            if remaining <= 0:
                break
            await asyncio.sleep(min(remaining, 60.0))
        if not _running:
            break
        try:
            await flush_pending_notifications(bot)
        except Exception as e:
            logger.error("Daily flush error: %s", e)


# ─── Notification sending ─────────────────────────────────────────────────


async def _send_notifications_to_users(
    bot: Bot,
    users: list,
    sched_data: dict,
    update_type: dict,
    changes: dict,
    is_daily_planned: bool = False,
) -> None:
    """Send schedule notifications to a list of users, respecting their settings."""
    batch_size = settings.SCHEDULER_BATCH_SIZE
    stagger_ms = settings.SCHEDULER_STAGGER_MS

    for i, user in enumerate(users):
        try:
            await _send_schedule_notification(
                bot, user, sched_data, update_type, changes, is_daily_planned
            )
        except Exception as e:
            logger.error("Error sending notification to user %s: %s", user.telegram_id, e)

        # Stagger between sends to respect Telegram API rate limits
        if (i + 1) % batch_size == 0:
            await asyncio.sleep(stagger_ms / 1000)


async def _safe_delete_message(bot: Bot, chat_id: int | str, message_id: int) -> None:
    """Try to delete a message; silently ignore if already gone."""
    try:
        await bot.delete_message(chat_id, message_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        pass
    except Exception as e:
        logger.debug("Could not delete message %s in chat %s: %s", message_id, chat_id, e)


async def _send_schedule_notification(
    bot: Bot,
    user,
    sched_data: dict,
    update_type: dict,
    changes: dict,
    is_daily_planned: bool = False,
) -> None:
    """Send a schedule notification to the user's bot chat and/or channel.

    - Bot   → photo + text + inline keyboard + live timestamp
    - Channel → photo + text only (NO keyboard, NO timestamp)
    """
    from bot.formatter.schedule import format_schedule_message
    from bot.services.api import find_next_event

    try:
        async with async_session() as session:
            fresh_user = await get_user_by_telegram_id(session, str(user.telegram_id))
            if not fresh_user:
                return

            ns = fresh_user.notification_settings
            if ns is not None and not ns.notify_schedule_changes:
                return

            last_check = await get_schedule_check_time(session, fresh_user.region, fresh_user.queue)

        next_event = find_next_event(sched_data)
        html_text = format_schedule_message(
            fresh_user.region,
            fresh_user.queue,
            sched_data,
            next_event,
            changes=changes if changes and changes.get("added") else None,
            update_type=update_type if update_type else None,
            is_daily_planned=is_daily_planned,
        )

        # ── Bot: photo + text + keyboard + live timestamp ───────────────────
        kb = get_schedule_view_keyboard()
        bot_plain_text, raw_bot_entities = append_timestamp(html_text, last_check)
        bot_entities = to_aiogram_entities(raw_bot_entities)

        # ── Channel: photo + text only — NO keyboard, NO timestamp ──────────
        ch_plain_text, raw_ch_entities = html_to_entities(html_text)
        ch_entities = to_aiogram_entities(raw_ch_entities)

        image_bytes = await fetch_schedule_image(fresh_user.region, fresh_user.queue)

        sent_msg = None
        sent_ch_msg = None

        # ── Send to user's bot chat ─────────────────────────────────────────
        if ns is None or ns.notify_schedule_target != "channel":
            try:
                # Delete the previous schedule message; skip for daily planned
                # messages sent at 06:00 (those are the first messages of the day).
                mt = fresh_user.message_tracking
                if not is_daily_planned and mt and mt.last_schedule_message_id:
                    await _safe_delete_message(
                        bot, int(fresh_user.telegram_id), mt.last_schedule_message_id
                    )

                if image_bytes:
                    photo = BufferedInputFile(image_bytes, filename="schedule.png")
                    sent_msg = await retry_bot_call(lambda: bot.send_photo(
                        int(fresh_user.telegram_id),
                        photo=photo,
                        caption=bot_plain_text,
                        caption_entities=bot_entities,
                        reply_markup=kb,
                        parse_mode=None,
                    ))
                else:
                    sent_msg = await retry_bot_call(lambda: bot.send_message(
                        int(fresh_user.telegram_id),
                        bot_plain_text,
                        entities=bot_entities,
                        reply_markup=kb,
                        parse_mode=None,
                    ))

            except TelegramForbiddenError:
                logger.warning(
                    "User %s blocked the bot, skipping schedule notification",
                    fresh_user.telegram_id,
                )
            except Exception as e:
                logger.warning(
                    "Failed to send schedule notification to user %s: %s",
                    fresh_user.telegram_id, e,
                )

        # ── Send to channel ─────────────────────────────────────────────────
        cc = fresh_user.channel_config
        if cc and cc.channel_id and cc.channel_status == "active" and not cc.channel_paused:
            if cc.ch_notify_schedule:
                try:
                    # Delete the previous channel schedule message; skip for
                    # daily planned messages (first message of the day at 06:00).
                    if not is_daily_planned and cc.last_schedule_message_id:
                        await _safe_delete_message(bot, cc.channel_id, cc.last_schedule_message_id)

                    if image_bytes:
                        photo = BufferedInputFile(image_bytes, filename="schedule.png")
                        sent_ch_msg = await retry_bot_call(lambda: bot.send_photo(
                            cc.channel_id,
                            photo=photo,
                            caption=ch_plain_text,
                            caption_entities=ch_entities,
                            parse_mode=None,
                        ))
                    else:
                        sent_ch_msg = await retry_bot_call(lambda: bot.send_message(
                            cc.channel_id,
                            ch_plain_text,
                            entities=ch_entities,
                            parse_mode=None,
                        ))

                except TelegramForbiddenError:
                    logger.warning(
                        "Bot lost access to channel %s, skipping schedule notification",
                        cc.channel_id,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to send schedule notification to channel %s: %s",
                        cc.channel_id, e,
                    )

        # ── Persist sent message IDs (single session for both bot and channel) ──
        if sent_msg is not None or sent_ch_msg is not None:
            async with async_session() as session:
                db_user = await get_user_by_telegram_id(session, str(fresh_user.telegram_id))
                if db_user:
                    if sent_msg is not None and db_user.message_tracking:
                        db_user.message_tracking.last_schedule_message_id = sent_msg.message_id
                    if sent_ch_msg is not None and db_user.channel_config:
                        db_user.channel_config.last_schedule_message_id = sent_ch_msg.message_id
                    await session.commit()

    except Exception as e:
        logger.error(
            "Error in _send_schedule_notification for user %s: %s", user.telegram_id, e
        )


def stop_scheduler() -> None:
    global _running
    _running = False


# ─── Reminder notifications ───────────────────────────────────────────────

# (telegram_id, event_anchor_iso, remind_minutes) — prevents duplicate sends
_sent_reminders: set[tuple[str, str, int]] = set()

# telegram_id -> event_anchor_iso whose reminder should be deleted when it passes
_pending_reminder_cleanup: dict[str, str] = {}

_REMIND_MINUTES = [60, 30, 15]
_REMIND_FIELDS     = {60: "remind_1h",    30: "remind_30m",    15: "remind_15m"}
_CH_REMIND_FIELDS  = {60: "ch_remind_1h", 30: "ch_remind_30m", 15: "ch_remind_15m"}
_REMIND_LABELS     = {60: "1 годину",     30: "30 хвилин",      15: "15 хвилин"}


async def reminder_checker_loop(bot: Bot) -> None:
    """Check every 60 seconds for upcoming events and send/clean up reminders."""
    logger.info("Reminder checker loop started")
    while _running:
        try:
            await _check_and_send_reminders(bot)
        except Exception as e:
            logger.error("Reminder checker error: %s", e)
        await asyncio.sleep(60)


async def _check_and_send_reminders(bot: Bot) -> None:
    if _is_quiet_hours():
        return

    now = datetime.now(KYIV_TZ)

    # ── 1. Cleanup: delete reminders for events that have already passed ──
    for tid, anchor_iso in list(_pending_reminder_cleanup.items()):
        if _event_anchor_passed(anchor_iso, now):
            await _delete_reminder_messages(bot, tid)
            del _pending_reminder_cleanup[tid]

    # ── 2. Expire sent-reminders cache for past events ────────────────
    expired = {k for k in _sent_reminders if _event_anchor_passed(k[1], now)}
    _sent_reminders.difference_update(expired)

    # ── 3. Collect users grouped by (region, queue) ───────────────────
    pairs: dict[tuple[str, str], list] = {}
    offset = 0
    while True:
        async with async_session() as session:
            batch = await get_active_users_paginated(session, limit=1000, offset=offset)
        if not batch:
            break
        for user in batch:
            ns = user.notification_settings
            if not ns:
                continue
            has_any = any(getattr(ns, _REMIND_FIELDS[m], False) for m in _REMIND_MINUTES)
            if not (has_any and (ns.notify_remind_off or ns.notify_remind_on)):
                continue
            if not user.region or not user.queue:
                continue
            pairs.setdefault((user.region, user.queue), []).append(user)
        if len(batch) < 1000:
            break
        offset += 1000

    # ── 4. For each (region, queue) check schedule and fire reminders ──
    for (region, queue), users in pairs.items():
        try:
            raw = await fetch_schedule_data(region)
            if not raw:
                continue
            sched = parse_schedule_for_queue(raw, queue)
            next_event = find_next_event(sched)
            if not next_event:
                continue

            event_type: str    = next_event["type"]   # "power_off" | "power_on"
            anchor_iso: str    = next_event["time"]   # key for dedup
            minutes_until: int = next_event["minutes"]
            is_possible: bool  = next_event.get("isPossible", False)

            for user in users:
                ns = user.notification_settings
                if event_type == "power_off" and not ns.notify_remind_off:
                    continue
                if event_type == "power_on" and not ns.notify_remind_on:
                    continue

                cc = user.channel_config
                for remind_m in _REMIND_MINUTES:
                    if not getattr(ns, _REMIND_FIELDS[remind_m], False):
                        continue
                    rkey = (str(user.telegram_id), anchor_iso, remind_m)
                    if rkey in _sent_reminders:
                        continue
                    if remind_m - 1 <= minutes_until <= remind_m + 1:
                        await _send_reminder(
                            bot, user, next_event, remind_m, sched, region, queue, is_possible, ns, cc
                        )
                        _sent_reminders.add(rkey)
                        _pending_reminder_cleanup[str(user.telegram_id)] = anchor_iso
        except Exception as e:
            logger.error("Reminder check error for %s/%s: %s", region, queue, e)


def _event_anchor_passed(anchor_iso: str, now: datetime) -> bool:
    try:
        dt = datetime.fromisoformat(anchor_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KYIV_TZ)
        return now > dt
    except Exception:
        return True


async def _delete_reminder_messages(bot: Bot, telegram_id: str) -> None:
    """Delete stored reminder messages for a user from bot chat and channel."""
    try:
        async with async_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user or not user.message_tracking:
                return
            mt = user.message_tracking
            cc = user.channel_config

            if mt.last_reminder_message_id:
                try:
                    await bot.delete_message(int(telegram_id), mt.last_reminder_message_id)
                except Exception:
                    pass
                mt.last_reminder_message_id = None

            if mt.last_channel_reminder_message_id and cc and cc.channel_id:
                try:
                    ch_id: int | str
                    try:
                        ch_id = int(cc.channel_id)
                    except (ValueError, TypeError):
                        ch_id = cc.channel_id
                    await bot.delete_message(ch_id, mt.last_channel_reminder_message_id)
                except Exception:
                    pass
                mt.last_channel_reminder_message_id = None

            await session.commit()
    except Exception as e:
        logger.warning("Could not delete reminder messages for user %s: %s", telegram_id, e)


def _build_reminder_text(
    next_event: dict,
    remind_m: int,
    sched: dict,
    region: str,
    queue: str,
    is_possible: bool,
) -> str:
    event_type = next_event["type"]
    label = _REMIND_LABELS[remind_m]

    # Header
    if event_type == "power_off":
        header = f"⚠️ <b>Відключення через {label}</b>"
    else:
        header = f"⚡️ <b>Увімкнення через {label}</b>"

    # Region · Queue
    region_name = REGIONS[region].name if region in REGIONS else region
    region_line = f"🌍 {region_name} · Черга {queue}"

    # Schedule block
    schedule_line = ""
    end_dt = None
    try:
        if event_type == "power_off":
            start_iso = next_event["time"]
            end_iso   = next_event.get("endTime", "")
        else:
            start_iso = next_event.get("startTime", "")
            end_iso   = next_event["time"]

        start_dt = datetime.fromisoformat(start_iso)
        end_dt   = datetime.fromisoformat(end_iso)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=KYIV_TZ)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=KYIV_TZ)

        total_min = int((end_dt - start_dt).total_seconds() / 60)
        dur_h, dur_m = divmod(total_min, 60)
        dur_str = f"{dur_h} год {dur_m} хв" if dur_m else f"{dur_h} год"
        schedule_line = f"📋 {start_dt.strftime('%H:%M')} – {end_dt.strftime('%H:%M')} ({dur_str})"
    except Exception:
        pass

    # Context line
    context_line = ""
    if end_dt:
        next_outage = _find_next_outage_after(sched, end_dt)
        if event_type == "power_off":
            context_line = f"💡 Увімкнення о {end_dt.strftime('%H:%M')}"
            if next_outage:
                ns_start = datetime.fromisoformat(next_outage["start"])
                if ns_start.tzinfo is None:
                    ns_start = ns_start.replace(tzinfo=KYIV_TZ)
                context_line += f"\n⚠️ Наступне відключення о {ns_start.strftime('%H:%M')}"
        else:
            if next_outage:
                ns_start = datetime.fromisoformat(next_outage["start"])
                if ns_start.tzinfo is None:
                    ns_start = ns_start.replace(tzinfo=KYIV_TZ)
                context_line = f"⚠️ Наступне відключення о {ns_start.strftime('%H:%M')}"
            else:
                context_line = "🌙 Більше відключень сьогодні немає"

    if is_possible:
        context_line = "⚠️ Можливе відключення" + (f"\n{context_line}" if context_line else "")

    parts = [header, region_line]
    if schedule_line:
        parts.append(schedule_line)
    if context_line:
        parts.append(context_line)
    return "\n".join(parts)


def _find_next_outage_after(sched: dict, after_dt: datetime) -> dict | None:
    """Return the first scheduled outage that starts after after_dt."""
    for ev in sched.get("events", []):
        try:
            start = datetime.fromisoformat(ev["start"])
            if start.tzinfo is None:
                start = start.replace(tzinfo=KYIV_TZ)
            if start >= after_dt and not ev.get("isPossible"):
                return ev
        except Exception:
            continue
    return None


async def _send_reminder(
    bot: Bot,
    user,
    next_event: dict,
    remind_m: int,
    sched: dict,
    region: str,
    queue: str,
    is_possible: bool,
    ns,
    cc,
) -> None:
    text = _build_reminder_text(next_event, remind_m, sched, region, queue, is_possible)
    kb = get_reminder_keyboard()

    # Delete previous reminder before sending the new one
    await _delete_reminder_messages(bot, str(user.telegram_id))

    send_to_bot = ns.notify_remind_target != "channel"
    send_to_channel = (
        cc is not None
        and cc.channel_id
        and not cc.channel_paused
        and getattr(cc, "ch_notify_remind_off", False)
    )

    bot_msg_id: int | None = None
    ch_msg_id: int | None = None

    if send_to_bot:
        try:
            msg = await retry_bot_call(
                lambda: bot.send_message(int(user.telegram_id), text, parse_mode="HTML", reply_markup=kb)
            )
            bot_msg_id = msg.message_id
            logger.debug("Reminder -%dm sent to user %s", remind_m, user.telegram_id)
        except TelegramForbiddenError:
            logger.debug("User %s blocked bot, skipping reminder", user.telegram_id)
        except Exception as e:
            logger.warning("Failed to send reminder to user %s: %s", user.telegram_id, e)

    if send_to_channel:
        try:
            ch_id: int | str
            try:
                ch_id = int(cc.channel_id)
            except (ValueError, TypeError):
                ch_id = cc.channel_id
            ch_msg = await retry_bot_call(
                lambda: bot.send_message(ch_id, text, parse_mode="HTML")
            )
            ch_msg_id = ch_msg.message_id
            logger.debug("Reminder -%dm sent to channel %s", remind_m, cc.channel_id)
        except TelegramForbiddenError:
            logger.debug("Lost access to channel %s, skipping reminder", cc.channel_id)
        except Exception as e:
            logger.warning("Failed to send reminder to channel %s: %s", cc.channel_id, e)

    if bot_msg_id or ch_msg_id:
        try:
            async with async_session() as session:
                db_user = await get_user_by_telegram_id(session, str(user.telegram_id))
                if db_user and db_user.message_tracking:
                    if bot_msg_id:
                        db_user.message_tracking.last_reminder_message_id = bot_msg_id
                    if ch_msg_id:
                        db_user.message_tracking.last_channel_reminder_message_id = ch_msg_id
                    await session.commit()
        except Exception as e:
            logger.warning("Could not save reminder message IDs for user %s: %s", user.telegram_id, e)
