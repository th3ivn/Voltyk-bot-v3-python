from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import BufferedInputFile

from bot.config import settings
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
from bot.keyboards.inline import get_schedule_view_keyboard
from bot.services.api import (
    calculate_schedule_hash,
    check_source_repo_updated,
    fetch_schedule_data,
    fetch_schedule_image,
    parse_schedule_for_queue,
)
from bot.utils.html_to_entities import append_timestamp, html_to_entities, to_aiogram_entities
from bot.utils.logger import get_logger

logger = get_logger(__name__)

_running = False

DEFAULT_SCHEDULE_CHECK_INTERVAL_S = 60
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
    """Return a changes dict with 'added' events (in new but not in old)."""
    old_keys = {f"{e['start']}_{e['end']}" for e in old_events}
    added = [e for e in new_events if f"{e['start']}_{e['end']}" not in old_keys]
    return {"added": added}


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
    except Exception:
        pass
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
    batch_size_inner = 1000
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

    async with async_session() as session:
        stored_hash = await get_schedule_hash(session, region, queue)
        if stored_hash is not None and stored_hash == new_all_hash:
            # No change in overall hash — update timestamp only
            await update_schedule_check_time(session, region, queue)
            # Even when the overall hash hasn't changed we may need to create or
            # refresh the daily snapshot (e.g. first check of a new day).  Do this
            # outside the early-return so it always runs.
            today_date_check = _kyiv_date_str()
            existing = await get_daily_snapshot(session, region, queue, today_date_check)
            if existing is None:
                new_today_hash_check = _compute_date_hash(events, today_date_check)
                new_tomorrow_hash_check = _compute_date_hash(events, _tomorrow_date_str())
                await upsert_daily_snapshot(
                    session, region, queue, today_date_check,
                    json.dumps(sched), new_today_hash_check, new_tomorrow_hash_check,
                )
            await session.commit()
            return

    # Hash changed — update check time and hash
    logger.info("Schedule changed for region=%s queue=%s", region, queue)

    # Determine update_type and changes using daily snapshot comparison
    today_date = _kyiv_date_str()
    yesterday_date = _yesterday_date_str()
    tomorrow_date = _tomorrow_date_str()

    new_today_hash = _compute_date_hash(events, today_date)
    new_tomorrow_hash = _compute_date_hash(events, tomorrow_date)

    update_type: dict = {}
    changes: dict = {"added": []}

    async with async_session() as session:
        await update_schedule_check_time(session, region, queue, last_hash=new_all_hash)
        snapshot = await get_daily_snapshot(session, region, queue, today_date)
        yesterday_snapshot = await get_daily_snapshot(session, region, queue, yesterday_date)
        await session.commit()

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

        if update_type.get("tomorrowAppeared") and not update_type.get("todayUpdated"):
            update_type["todayUnchanged"] = True

    # Save updated snapshot
    async with async_session() as session:
        await upsert_daily_snapshot(
            session, region, queue, today_date,
            json.dumps(sched), new_today_hash, new_tomorrow_hash,
        )
        await session.commit()

    # If no meaningful change detected, skip notification
    # Fallback: hash changed but snapshots were absent (e.g. first run) — always notify
    if not update_type:
        update_type["todayUpdated"] = True

    sched_data_json = json.dumps(sched)
    update_type_json = json.dumps(update_type)
    changes_json = json.dumps(changes) if changes.get("added") else None

    if _is_quiet_hours():
        # Queue notification for 06:00 flush
        async with async_session() as session:
            await save_pending_notification(
                session, region, queue, sched_data_json, update_type_json, changes_json
            )
            await session.commit()
        logger.info("Queued notification for %s/%s (quiet hours)", region, queue)
        return

    # Send immediately to all active users in this region/queue
    async with async_session() as session:
        users = await get_active_users_by_region(session, region)

    users_in_queue = [u for u in users if u.queue == queue]
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
    batch_size_inner = 1000
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
            async with async_session() as session:
                users = await get_active_users_by_region(session, region)
            users_in_queue = [u for u in users if u.queue == queue]

            if (region, queue) in pending_set:
                # Send the latest queued notification
                async with async_session() as session:
                    notif = await get_latest_pending_notification(session, region, queue)

                if notif:
                    sched = json.loads(notif.schedule_data)
                    update_type = json.loads(notif.update_type) if notif.update_type else {}
                    changes = json.loads(notif.changes) if notif.changes else {"added": []}

                    await _send_notifications_to_users(
                        bot, users_in_queue, sched, update_type, changes, is_daily_planned=False
                    )

                    async with async_session() as session:
                        await mark_pending_notifications_sent(session, region, queue)
                        await session.commit()
            else:
                # No overnight changes — send daily planned message
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

                sent_msg = None
                if image_bytes:
                    photo = BufferedInputFile(image_bytes, filename="schedule.png")
                    sent_msg = await bot.send_photo(
                        int(fresh_user.telegram_id),
                        photo=photo,
                        caption=bot_plain_text,
                        caption_entities=bot_entities,
                        reply_markup=kb,
                        parse_mode=None,
                    )
                else:
                    sent_msg = await bot.send_message(
                        int(fresh_user.telegram_id),
                        bot_plain_text,
                        entities=bot_entities,
                        reply_markup=kb,
                        parse_mode=None,
                    )

                # Persist new message ID for future deletion
                if sent_msg:
                    async with async_session() as session:
                        db_user = await get_user_by_telegram_id(session, str(fresh_user.telegram_id))
                        if db_user and db_user.message_tracking:
                            db_user.message_tracking.last_schedule_message_id = sent_msg.message_id
                            await session.commit()

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

                    sent_ch_msg = None
                    if image_bytes:
                        photo = BufferedInputFile(image_bytes, filename="schedule.png")
                        sent_ch_msg = await bot.send_photo(
                            cc.channel_id,
                            photo=photo,
                            caption=ch_plain_text,
                            caption_entities=ch_entities,
                            parse_mode=None,
                        )
                    else:
                        sent_ch_msg = await bot.send_message(
                            cc.channel_id,
                            ch_plain_text,
                            entities=ch_entities,
                            parse_mode=None,
                        )

                    # Persist channel message ID for future deletion
                    if sent_ch_msg:
                        async with async_session() as session:
                            db_user = await get_user_by_telegram_id(session, str(fresh_user.telegram_id))
                            if db_user and db_user.channel_config:
                                db_user.channel_config.last_schedule_message_id = sent_ch_msg.message_id
                                await session.commit()

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

    except Exception as e:
        logger.error(
            "Error in _send_schedule_notification for user %s: %s", user.telegram_id, e
        )


def stop_scheduler() -> None:
    global _running
    _running = False
