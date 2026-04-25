from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from bot.config import settings
from bot.db.queries import get_due_auto_delete, remove_auto_delete_entries
from bot.db.session import async_session
from bot.utils import heartbeat
from bot.utils.logger import get_logger

logger = get_logger(__name__)

_running = True


async def queue_message_for_delete(
    *,
    user_id: int,
    chat_id: int | str,
    message_id: int,
    source: str,
    delay_minutes: int | None = None,
) -> None:
    from bot.db.queries import enqueue_auto_delete

    delay = delay_minutes if delay_minutes is not None else settings.AUTO_DELETE_DELAY_MINUTES
    delete_at = datetime.now(timezone.utc) + timedelta(minutes=max(delay, 1))

    async with async_session() as session:
        await enqueue_auto_delete(
            session,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            source=source,
            delete_at=delete_at,
        )
        await session.commit()


async def _try_delete(bot: Bot, chat_id: int, message_id: int) -> bool:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        return True
    except TelegramForbiddenError as e:
        logger.info("Auto-cleanup skipped (no permissions) chat=%s msg=%s: %s", chat_id, message_id, e)
        return True
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "message to delete not found" in msg or "message can't be deleted" in msg:
            logger.debug("Auto-cleanup already gone chat=%s msg=%s", chat_id, message_id)
            return True
        logger.debug("Auto-cleanup bad request chat=%s msg=%s: %s", chat_id, message_id, e)
        return False
    except Exception as e:
        logger.warning("Auto-cleanup delete error chat=%s msg=%s: %s", chat_id, message_id, e)
        return False


async def auto_cleanup_loop(bot: Bot) -> None:
    global _running
    _running = True

    while _running:
        heartbeat.beat("auto_cleanup")
        try:
            async with async_session() as session:
                due = await get_due_auto_delete(session, limit=200)
                if not due:
                    await asyncio.sleep(15)
                    continue

                processed_ids: list[int] = []
                for row in due:
                    try:
                        chat_id = int(row.chat_id)
                    except ValueError:
                        processed_ids.append(row.id)
                        continue

                    deleted = await _try_delete(bot, chat_id=chat_id, message_id=row.message_id)
                    if deleted:
                        processed_ids.append(row.id)

                if processed_ids:
                    await remove_auto_delete_entries(session, processed_ids)
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Auto-cleanup loop failed: %s", e)
        await asyncio.sleep(2)


def stop_auto_cleanup() -> None:
    global _running
    _running = False
