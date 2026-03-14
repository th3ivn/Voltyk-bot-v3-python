from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot

from bot.config import settings
from bot.db.queries import get_all_active_users, update_schedule_check_time
from bot.db.session import async_session
from bot.services.api import calculate_schedule_hash, fetch_schedule_data, parse_schedule_for_queue

logger = logging.getLogger(__name__)

_running = False


async def schedule_checker_loop(bot: Bot):
    global _running
    _running = True
    logger.info("Schedule checker started (interval: %ds)", settings.SCHEDULE_CHECK_INTERVAL_S)

    while _running:
        try:
            await _check_all_schedules(bot)
        except Exception as e:
            logger.error("Schedule check error: %s", e)
        await asyncio.sleep(settings.SCHEDULE_CHECK_INTERVAL_S)


async def _check_all_schedules(bot: Bot):
    async with async_session() as session:
        users = await get_all_active_users(session)
        checked: dict[str, tuple[str, dict]] = {}

        for user in users:
            key = f"{user.region}_{user.queue}"
            if key not in checked:
                data = await fetch_schedule_data(user.region)
                if data:
                    sched = parse_schedule_for_queue(data, user.queue)
                    h = calculate_schedule_hash(sched.get("events", []))
                    checked[key] = (h, sched)

            if key in checked:
                new_hash, sched_data = checked[key]
                if new_hash and user.last_hash != new_hash:
                    user.last_hash = new_hash
                    logger.info("Schedule changed: user=%s region=%s queue=%s", user.telegram_id, user.region, user.queue)
                    asyncio.create_task(_send_schedule_notification(bot, user, sched_data))

        for key in checked:
            region, queue = key.split("_", 1)
            await update_schedule_check_time(session, region, queue)

        await session.commit()


async def _send_schedule_notification(bot: Bot, user, schedule_data: dict) -> None:
    """Send schedule change notification to bot chat and/or channel."""
    from aiogram.exceptions import TelegramForbiddenError
    from aiogram.types import BufferedInputFile, MessageEntity

    from bot.db.queries import deactivate_user, get_user_by_telegram_id
    from bot.db.session import async_session
    from bot.formatter.schedule import format_schedule_for_channel, format_schedule_message
    from bot.keyboards.inline import get_schedule_view_keyboard
    from bot.services.api import fetch_schedule_image, find_next_event
    from bot.utils.html_to_entities import append_timestamp

    try:
        telegram_id = str(user.telegram_id)

        async with async_session() as session:
            fresh_user = await get_user_by_telegram_id(session, telegram_id)
        if not fresh_user:
            return

        ns = fresh_user.notification_settings
        cc = fresh_user.channel_config

        next_event = find_next_event(schedule_data)

        # ── Send to bot chat ──────────────────────────────────────────
        if ns and ns.notify_schedule_changes:
            try:
                html_text = format_schedule_message(fresh_user.region, fresh_user.queue, schedule_data, next_event)
                now_unix = int(time.time())
                plain_text, raw_entities = append_timestamp(html_text, now_unix)

                entities = []
                for e in raw_entities:
                    params = {"type": e["type"], "offset": e["offset"], "length": e["length"]}
                    for key in ("url", "custom_emoji_id", "unix_time", "date_time_format"):
                        if key in e:
                            params[key] = e[key]
                    entities.append(MessageEntity(**params))

                kb = get_schedule_view_keyboard()
                image_bytes = await fetch_schedule_image(fresh_user.region, fresh_user.queue)

                if image_bytes:
                    photo = BufferedInputFile(image_bytes, filename="schedule.png")
                    await bot.send_photo(
                        int(telegram_id),
                        photo=photo,
                        caption=plain_text,
                        caption_entities=entities,
                        reply_markup=kb,
                    )
                else:
                    await bot.send_message(
                        int(telegram_id),
                        plain_text,
                        entities=entities,
                        reply_markup=kb,
                    )
                logger.info("📅 Schedule notification sent to user %s", telegram_id)
            except TelegramForbiddenError:
                logger.info("User %s blocked the bot — deactivating", telegram_id)
                async with async_session() as session:
                    await deactivate_user(session, telegram_id)
                    await session.commit()
            except Exception as e:
                logger.error("Error sending schedule notification to user %s: %s", telegram_id, e)

        # ── Send to channel ───────────────────────────────────────────
        if cc and cc.channel_id and str(cc.channel_id) != telegram_id:
            if cc.channel_paused:
                return
            if not cc.ch_notify_schedule:
                return

            try:
                channel_text = format_schedule_for_channel(fresh_user.region, fresh_user.queue, schedule_data)
                image_bytes = await fetch_schedule_image(fresh_user.region, fresh_user.queue)
                try:
                    ch_id: int | str = int(cc.channel_id)
                except (ValueError, TypeError):
                    ch_id = cc.channel_id

                if image_bytes:
                    photo = BufferedInputFile(image_bytes, filename="schedule.png")
                    await bot.send_photo(ch_id, photo=photo, caption=channel_text, parse_mode="HTML")
                else:
                    await bot.send_message(ch_id, channel_text, parse_mode="HTML")
                logger.info("📢 Schedule notification sent to channel %s", cc.channel_id)
            except TelegramForbiddenError:
                logger.warning("Channel %s is not accessible", cc.channel_id)
            except Exception as e:
                logger.error("Error sending schedule to channel %s: %s", cc.channel_id, e)

    except Exception as e:
        logger.error("Unexpected error in _send_schedule_notification for user %s: %s", getattr(user, "telegram_id", "?"), e)


def stop_scheduler():
    global _running
    _running = False
