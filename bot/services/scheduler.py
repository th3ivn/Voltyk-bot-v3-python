from __future__ import annotations

import asyncio
from bot.utils.logger import get_logger

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import BufferedInputFile

from bot.config import settings

from bot.db.queries import (
    get_active_users_by_region,
    get_active_users_paginated,
    get_schedule_check_time,
    get_schedule_hash,
    get_user_by_telegram_id,
    update_schedule_check_time,
)
from bot.db.session import async_session
from bot.keyboards.inline import get_schedule_view_keyboard
from bot.services.api import calculate_schedule_hash, fetch_schedule_data, fetch_schedule_image, parse_schedule_for_queue
from bot.utils.html_to_entities import append_timestamp, to_aiogram_entities

logger = get_logger(__name__)

_running = False

DEFAULT_SCHEDULE_CHECK_INTERVAL_S = 60


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

        logger.debug("Next schedule check in %ds", interval)
        await asyncio.sleep(interval)


async def _check_all_schedules(bot: Bot, interval: int = DEFAULT_SCHEDULE_CHECK_INTERVAL_S) -> None:
    """
    Fetch schedule for each unique region/queue pair.
    If the hash changed since last check → notify all users of that queue.
    Hash is stored in schedule_checks.last_hash (one row per region/queue).
    """
    # Collect unique region/queue pairs from active users
    region_queue_pairs: set[tuple[str, str]] = set()
    BATCH_SIZE = 1000
    offset = 0
    while True:
        async with async_session() as session:
            batch = await get_active_users_paginated(session, limit=BATCH_SIZE, offset=offset)
        if not batch:
            break
        for user in batch:
            region_queue_pairs.add((user.region, user.queue))
        if len(batch) < BATCH_SIZE:
            break
        offset += BATCH_SIZE

    # For each unique pair: fetch, hash, compare, notify if changed
    for region, queue in region_queue_pairs:
        try:
            await _check_single_queue(bot, region, queue, interval_s=interval)
        except Exception as e:
            logger.error("Error checking schedule for %s/%s: %s", region, queue, e)


async def _check_single_queue(bot: Bot, region: str, queue: str, interval_s: int = DEFAULT_SCHEDULE_CHECK_INTERVAL_S) -> None:
    data = await fetch_schedule_data(region, cache_ttl_s=interval_s)
    if not data:
        return

    sched = parse_schedule_for_queue(data, queue)
    new_hash = calculate_schedule_hash(sched.get("events", []))

    async with async_session() as session:
        stored_hash = await get_schedule_hash(session, region, queue)

        if stored_hash == new_hash:
            # No change — just update timestamp
            await update_schedule_check_time(session, region, queue)
            await session.commit()
            return

        # Hash changed — update and notify
        logger.info("Schedule changed for region=%s queue=%s", region, queue)
        await update_schedule_check_time(session, region, queue, last_hash=new_hash)
        await session.commit()

    # Notify all active users in this region/queue
    async with async_session() as session:
        users = await get_active_users_by_region(session, region)

    for user in users:
        if user.queue != queue:
            continue
        await _send_schedule_notification(bot, user, sched)


async def _send_schedule_notification(bot: Bot, user, sched_data: dict) -> None:
    """Send a schedule-change notification to the user's chat and/or channel."""
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
        html_text = format_schedule_message(fresh_user.region, fresh_user.queue, sched_data, next_event)
        kb = get_schedule_view_keyboard()

        plain_text, raw_entities = append_timestamp(html_text, last_check)
        entities = to_aiogram_entities(raw_entities)

        image_bytes = await fetch_schedule_image(fresh_user.region, fresh_user.queue)

        async def _send_to_bot(chat_id) -> None:
            if image_bytes:
                photo = BufferedInputFile(image_bytes, filename="schedule.png")
                await bot.send_photo(
                    chat_id, photo=photo, caption=plain_text, caption_entities=entities,
                    reply_markup=kb, parse_mode=None,
                )
            else:
                await bot.send_message(
                    chat_id, plain_text, entities=entities, reply_markup=kb, parse_mode=None,
                )

        async def _send_to_channel(chat_id) -> None:
            if image_bytes:
                photo = BufferedInputFile(image_bytes, filename="schedule.png")
                await bot.send_photo(
                    chat_id, photo=photo, caption=html_text, parse_mode="HTML",
                )
            else:
                await bot.send_message(
                    chat_id, html_text, parse_mode="HTML",
                )

        # Send to user's bot chat
        if ns is None or ns.notify_schedule_target != "channel":
            try:
                await _send_to_bot(int(fresh_user.telegram_id))
            except TelegramForbiddenError:
                logger.warning("User %s blocked the bot, skipping schedule notification", fresh_user.telegram_id)
            except Exception as e:
                logger.warning("Failed to send schedule notification to user %s: %s", fresh_user.telegram_id, e)

        # Send to channel if configured and enabled
        cc = fresh_user.channel_config
        if cc and cc.channel_id and cc.channel_status == "active" and not cc.channel_paused:
            if cc.ch_notify_schedule:
                try:
                    await _send_to_channel(cc.channel_id)
                except TelegramForbiddenError:
                    logger.warning("Bot lost access to channel %s, skipping schedule notification", cc.channel_id)
                except Exception as e:
                    logger.warning("Failed to send schedule notification to channel %s: %s", cc.channel_id, e)

    except Exception as e:
        logger.error("Error in _send_schedule_notification for user %s: %s", user.telegram_id, e)


def stop_scheduler() -> None:
    global _running
    _running = False
