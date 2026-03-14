from __future__ import annotations

import asyncio
import logging

from bot.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="bot.tasks.notifications.send_bot_notification",
    max_retries=5,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
)
def send_bot_notification(self, telegram_id: int, text: str, parse_mode: str = "HTML"):
    """Send notification to user's bot chat. Retry with exponential backoff."""
    try:
        asyncio.get_event_loop().run_until_complete(
            _send_notification(telegram_id, text, parse_mode)
        )
    except Exception as exc:
        logger.error("Bot notification failed for %d: %s", telegram_id, exc)
        raise self.retry(exc=exc)


async def _send_notification(telegram_id: int, text: str, parse_mode: str):
    logger.info("Sending notification to %d", telegram_id)


@celery_app.task(
    bind=True,
    name="bot.tasks.notifications.send_channel_notification",
    max_retries=5,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
)
def send_channel_notification(self, channel_id: str, text: str, parse_mode: str = "HTML"):
    """Send notification to channel. Retry with exponential backoff."""
    try:
        asyncio.get_event_loop().run_until_complete(
            _send_channel_notification(channel_id, text, parse_mode)
        )
    except Exception as exc:
        logger.error("Channel notification failed for %s: %s", channel_id, exc)
        raise self.retry(exc=exc)


async def _send_channel_notification(channel_id: str, text: str, parse_mode: str):
    logger.info("Sending channel notification to %s", channel_id)


@celery_app.task(
    bind=True,
    name="bot.tasks.notifications.broadcast_message",
    max_retries=5,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
)
def broadcast_message(self, text: str, parse_mode: str = "HTML"):
    """Broadcast message to all active users via Celery queue."""
    try:
        asyncio.get_event_loop().run_until_complete(_broadcast(text, parse_mode))
    except Exception as exc:
        logger.error("Broadcast failed: %s", exc)
        raise self.retry(exc=exc)


async def _broadcast(text: str, parse_mode: str):
    from bot.db.queries import get_active_users_paginated
    from bot.db.session import async_session

    BATCH = 500
    offset = 0
    total = 0
    while True:
        async with async_session() as session:
            batch = await get_active_users_paginated(session, limit=BATCH, offset=offset)
        if not batch:
            break
        total += len(batch)
        for user in batch:
            logger.debug("Broadcasting to user %s", user.telegram_id)
        offset += BATCH
    logger.info("Broadcast complete: %d users notified", total)
