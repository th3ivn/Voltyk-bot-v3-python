from __future__ import annotations

import asyncio
import logging

from bot.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="bot.tasks.schedule_tasks.check_all_schedules",
    max_retries=5,
    default_retry_delay=30,
)
def check_all_schedules(self):
    try:
        asyncio.get_event_loop().run_until_complete(_check_schedules())
    except Exception as exc:
        logger.error("Schedule check failed: %s", exc)
        raise self.retry(exc=exc)


async def _check_schedules():
    from bot.db.queries import get_all_active_users, update_schedule_check_time
    from bot.db.session import async_session
    from bot.services.api import calculate_schedule_hash, fetch_schedule_data, parse_schedule_for_queue

    async with async_session() as session:
        users = await get_all_active_users(session)
        checked_regions: dict[str, dict] = {}

        for user in users:
            region = user.region
            queue = user.queue
            cache_key = f"{region}_{queue}"

            if cache_key not in checked_regions:
                data = await fetch_schedule_data(region)
                if data:
                    schedule_data = parse_schedule_for_queue(data, queue)
                    new_hash = calculate_schedule_hash(schedule_data.get("events", []))
                    checked_regions[cache_key] = {"data": schedule_data, "hash": new_hash}

            if cache_key in checked_regions:
                new_hash = checked_regions[cache_key]["hash"]
                if user.last_hash != new_hash:
                    user.last_hash = new_hash
                    logger.info("Schedule changed for user %s (%s/%s)", user.telegram_id, region, queue)

        for cache_key in checked_regions:
            region, queue = cache_key.split("_", 1)
            await update_schedule_check_time(session, region, queue)

        await session.commit()

    logger.debug("Schedule check complete for %d users", len(users))


@celery_app.task(
    bind=True,
    name="bot.tasks.schedule_tasks.publish_schedule",
    max_retries=5,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
)
def publish_schedule(self, user_id: int, region: str, queue: str):
    """Publish schedule to user's channel via Celery queue with exponential backoff."""
    try:
        asyncio.get_event_loop().run_until_complete(
            _publish_schedule(user_id, region, queue)
        )
    except Exception as exc:
        logger.error("Schedule publish failed for user %d: %s", user_id, exc)
        raise self.retry(exc=exc)


async def _publish_schedule(user_id: int, region: str, queue: str):
    logger.info("Publishing schedule for user %d (%s/%s)", user_id, region, queue)
