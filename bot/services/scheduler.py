from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from bot.config import settings
from bot.db.queries import get_active_users_paginated, get_user_by_telegram_id, update_schedule_check_time
from bot.db.session import async_session
from bot.services.api import calculate_schedule_hash, fetch_schedule_data, parse_schedule_for_queue

logger = logging.getLogger(__name__)

_running = False


async def schedule_checker_loop(bot: Bot) -> None:
    global _running
    _running = True
    logger.info("Schedule checker started (interval: %ds)", settings.SCHEDULE_CHECK_INTERVAL_S)

    while _running:
        try:
            await _check_all_schedules(bot)
        except Exception as e:
            logger.error("Schedule check error: %s", e)
        await asyncio.sleep(settings.SCHEDULE_CHECK_INTERVAL_S)


async def _check_all_schedules(bot: Bot) -> None:
    BATCH_SIZE = 1000
    # Store (hash, schedule_data) per region/queue key
    checked: dict[str, tuple[str, dict[str, object]]] = {}

    # First pass: collect unique region/queue hashes across all users
    async with async_session() as session:
        sample = await get_active_users_paginated(session, limit=BATCH_SIZE, offset=0)
    for user in sample:
        key = f"{user.region}_{user.queue}"
        if key not in checked:
            data = await fetch_schedule_data(user.region)
            if data:
                sched = parse_schedule_for_queue(data, user.queue)
                h = calculate_schedule_hash(sched.get("events", []))
                checked[key] = (h, sched)

    # If there are more users beyond the first batch, collect remaining region/queue keys
    if len(sample) == BATCH_SIZE:
        offset = BATCH_SIZE
        while True:
            async with async_session() as session:
                batch = await get_active_users_paginated(session, limit=BATCH_SIZE, offset=offset)
            if not batch:
                break
            for user in batch:
                key = f"{user.region}_{user.queue}"
                if key not in checked:
                    data = await fetch_schedule_data(user.region)
                    if data:
                        sched = parse_schedule_for_queue(data, user.queue)
                        h = calculate_schedule_hash(sched.get("events", []))
                        checked[key] = (h, sched)
            offset += BATCH_SIZE

    # Second pass: update last_hash for users whose schedule changed, committing per batch
    offset = 0
    while True:
        async with async_session() as session:
            batch = await get_active_users_paginated(session, limit=BATCH_SIZE, offset=offset)
            if not batch:
                break

            changed_users: list[tuple] = []
            for user in batch:
                key = f"{user.region}_{user.queue}"
                entry = checked.get(key)
                if entry:
                    new_hash, sched_data = entry
                    if user.last_hash != new_hash:
                        user.last_hash = new_hash
                        changed_users.append((user, sched_data))
                        logger.info(
                            "Schedule changed: user=%s region=%s queue=%s",
                            user.telegram_id,
                            user.region,
                            user.queue,
                        )

            await session.commit()

        for user, sched_data in changed_users:
            await _send_schedule_notification(bot, user, sched_data)

        offset += BATCH_SIZE

    # Update check timestamps for all visited region/queue pairs
    async with async_session() as session:
        for key in checked:
            region, queue = key.split("_", 1)
            await update_schedule_check_time(session, region, queue)
        await session.commit()


async def _send_schedule_notification(bot: Bot, user, sched_data: dict) -> None:
    """Send a schedule-change notification to the user's chat and/or channel."""
    from bot.formatter.schedule import format_schedule_message
    from bot.services.api import find_next_event
    from bot.utils.html_to_entities import html_to_entities

    try:
        async with async_session() as session:
            fresh_user = await get_user_by_telegram_id(session, str(user.telegram_id))

        if not fresh_user:
            return

        ns = fresh_user.notification_settings
        if ns is not None and not ns.notify_schedule_changes:
            return

        next_event = find_next_event(sched_data)
        html_text = format_schedule_message(fresh_user.region, fresh_user.queue, sched_data, next_event)
        plain_text, _ = html_to_entities(html_text)
        text = f"📅 Графік змінився!\n\n{plain_text}"

        # Send to user's bot chat
        if ns is None or ns.notify_schedule_target != "channel":
            try:
                await bot.send_message(int(fresh_user.telegram_id), text)
            except TelegramForbiddenError:
                logger.warning("User %s blocked the bot, skipping schedule notification", fresh_user.telegram_id)
            except Exception as e:
                logger.warning("Failed to send schedule notification to user %s: %s", fresh_user.telegram_id, e)

        # Send to channel if configured and enabled
        cc = fresh_user.channel_config
        if cc and cc.channel_id and cc.channel_status == "active" and not cc.channel_paused:
            if cc.ch_notify_schedule:
                try:
                    await bot.send_message(cc.channel_id, text)
                except TelegramForbiddenError:
                    logger.warning("Bot lost access to channel %s, skipping schedule notification", cc.channel_id)
                except Exception as e:
                    logger.warning("Failed to send schedule notification to channel %s: %s", cc.channel_id, e)

    except Exception as e:
        logger.error("Error in _send_schedule_notification for user %s: %s", user.telegram_id, e)


def stop_scheduler():
    global _running
    _running = False
