from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import settings
from bot.utils.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_MAINTENANCE_MESSAGE = "🔧 Бот тимчасово недоступний. Спробуйте пізніше."


class MaintenanceMiddleware(BaseMiddleware):
    _enabled: bool = False
    _message: str = _DEFAULT_MAINTENANCE_MESSAGE

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not MaintenanceMiddleware._enabled:
            return await handler(event, data)

        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id and settings.is_admin(user_id):
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer(MaintenanceMiddleware._message, show_alert=True)
            return None

        if isinstance(event, Message):
            await event.reply(MaintenanceMiddleware._message)
            return None

        return None


def is_maintenance_mode() -> bool:
    return MaintenanceMiddleware._enabled


def set_maintenance_mode(enabled: bool, message: str | None = None) -> None:
    MaintenanceMiddleware._enabled = enabled
    if message is not None:
        MaintenanceMiddleware._message = message


def get_maintenance_message() -> str:
    return MaintenanceMiddleware._message

