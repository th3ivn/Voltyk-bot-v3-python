from __future__ import annotations

import asyncio
import logging

from bot.config import settings
from bot.db.queries import get_all_active_users, update_schedule_check_time
from bot.db.session import async_session
from bot.services.api import calculate_schedule_hash, fetch_schedule_data, parse_schedule_for_queue

logger = logging.getLogger(__name__)

_running = False


async def schedule_checker_loop():
    global _running
    _running = True
    logger.info("Schedule checker started (interval: %ds)", settings.SCHEDULE_CHECK_INTERVAL_S)

    while _running:
        try:
            await _check_all_schedules()
        except Exception as e:
            logger.error("Schedule check error: %s", e)
        await asyncio.sleep(settings.SCHEDULE_CHECK_INTERVAL_S)


async def _check_all_schedules():
    async with async_session() as session:
        users = await get_all_active_users(session)
        checked: dict[str, str] = {}

        for user in users:
            key = f"{user.region}_{user.queue}"
            if key not in checked:
                data = await fetch_schedule_data(user.region)
                if data:
                    sched = parse_schedule_for_queue(data, user.queue)
                    h = calculate_schedule_hash(sched.get("events", []))
                    checked[key] = h

            new_hash = checked.get(key)
            if new_hash and user.last_hash != new_hash:
                user.last_hash = new_hash
                logger.info("Schedule changed: user=%s region=%s queue=%s", user.telegram_id, user.region, user.queue)

        for key in checked:
            region, queue = key.split("_", 1)
            await update_schedule_check_time(session, region, queue)

        await session.commit()


def stop_scheduler():
    global _running
    _running = False
