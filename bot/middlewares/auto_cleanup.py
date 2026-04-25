from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import DeleteMessage, TelegramMethod
from aiogram.types import Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_user_by_telegram_id
from bot.services.auto_cleanup import queue_message_for_delete
from bot.utils.logger import get_logger

logger = get_logger(__name__)


class AutoCleanupCommandMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        result = await handler(event, data)

        if not isinstance(event, Message) or not event.text or not event.text.startswith("/"):
            return result

        session = data.get("session")
        if not isinstance(session, AsyncSession):
            return result

        user = await get_user_by_telegram_id(session, event.from_user.id if event.from_user else 0)
        if not user or not user.notification_settings or not user.notification_settings.auto_delete_commands:
            return result

        try:
            await queue_message_for_delete(
                user_id=user.id,
                chat_id=event.chat.id,
                message_id=event.message_id,
                source="command",
            )
        except Exception as e:
            logger.debug("Failed to queue command cleanup for user %s: %s", user.id, e)

        return result


class AutoCleanupResponseMiddleware(BaseRequestMiddleware):
    async def __call__(
        self,
        make_request: Callable[[Any, TelegramMethod[Any]], Awaitable[Any]],
        bot: Any,
        method: TelegramMethod[Any],
    ) -> Any:
        result = await make_request(bot, method)

        if isinstance(method, DeleteMessage):
            return result

        chat_id_raw = getattr(method, "chat_id", None)
        chat_id = _as_private_chat_id(chat_id_raw)
        if chat_id is None:
            return result

        message_ids = _extract_message_ids(result)
        if not message_ids:
            return result

        try:
            await _queue_bot_messages(chat_id, message_ids)
        except Exception as e:
            logger.debug("Failed to queue bot message cleanup chat=%s: %s", chat_id, e)

        return result


def _as_private_chat_id(chat_id: Any) -> int | None:
    if isinstance(chat_id, int):
        return chat_id if chat_id > 0 else None
    if isinstance(chat_id, str) and chat_id.isdigit():
        value = int(chat_id)
        return value if value > 0 else None
    return None


def _extract_message_ids(result: Any) -> list[int]:
    if isinstance(result, Message):
        return [result.message_id]
    if isinstance(result, list):
        ids = [item.message_id for item in result if isinstance(item, Message)]
        return ids
    return []


async def _queue_bot_messages(chat_id: int, message_ids: list[int]) -> None:
    from bot.db.session import async_session

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, chat_id)
        if not user or not user.notification_settings or not user.notification_settings.auto_delete_bot_messages:
            return

        for message_id in message_ids:
            await queue_message_for_delete(
                user_id=user.id,
                chat_id=chat_id,
                message_id=message_id,
                source="bot_reply",
            )
