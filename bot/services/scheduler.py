from __future__ import annotations

import asyncio
import logging

from bot.config import settings
from bot.db.queries import get_active_users_paginated, update_schedule_check_time
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
    BATCH_SIZE = 1000
    checked: dict[str, str] = {}

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
                checked[key] = h

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
                        checked[key] = h
            offset += BATCH_SIZE

    # Second pass: update last_hash for users whose schedule changed, committing per batch
    offset = 0
    while True:
        async with async_session() as session:
            batch = await get_active_users_paginated(session, limit=BATCH_SIZE, offset=offset)
            if not batch:
                break

            for user in batch:
                key = f"{user.region}_{user.queue}"
                new_hash = checked.get(key)
                if new_hash and user.last_hash != new_hash:
                    user.last_hash = new_hash
                    logger.info(
                        "Schedule changed: user=%s region=%s queue=%s",
                        user.telegram_id,
                        user.region,
                        user.queue,
                    )

            await session.commit()

        offset += BATCH_SIZE

    # Update check timestamps for all visited region/queue pairs
    async with async_session() as session:
        for key in checked:
            region, queue = key.split("_", 1)
            await update_schedule_check_time(session, region, queue)
        await session.commit()


def stop_scheduler():
    global _running
    _running = False
