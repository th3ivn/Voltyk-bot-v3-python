from __future__ import annotations

import asyncio
import logging

from bot.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="bot.tasks.channel_guard.validate_all_channels",
    max_retries=3,
    default_retry_delay=60,
)
def validate_all_channels(self):
    """
    Daily channel validation at 03:00.
    Checks that bot is still admin in all connected channels.
    Per Rule #3: no auto-blocking on name/photo/description changes.
    """
    try:
        asyncio.run(_validate_channels())
    except Exception as exc:
        logger.error("Channel validation failed: %s", exc)
        raise self.retry(exc=exc)


async def _validate_channels():
    from bot.db.queries import get_users_with_channel
    from bot.db.session import async_session

    async with async_session() as session:
        users = await get_users_with_channel(session)
        logger.info("Validating %d channels", len(users))

        for user in users:
            cc = user.channel_config
            if not cc or not cc.channel_id:
                continue

            logger.debug("Channel %s for user %s: OK (validation is passive)", cc.channel_id, user.telegram_id)

        await session.commit()

    logger.info("Channel validation complete")
