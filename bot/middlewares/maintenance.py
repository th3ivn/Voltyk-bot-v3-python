from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import settings

logger = logging.getLogger(__name__)

_maintenance_mode = False
_maintenance_message = "🔧 Бот тимчасово недоступний. Спробуйте пізніше."


def is_maintenance_mode() -> bool:
    return _maintenance_mode


def set_maintenance_mode(enabled: bool, message: str | None = None) -> None:
    global _maintenance_mode, _maintenance_message
    _maintenance_mode = enabled
    if message is not None:
        _maintenance_message = message


def get_maintenance_message() -> str:
    return _maintenance_message


class MaintenanceMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not _maintenance_mode:
            return await handler(event, data)

        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id and settings.is_admin(user_id):
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer(_maintenance_message, show_alert=True)
            return None

        if isinstance(event, Message):
            await event.reply(_maintenance_message)
            return None

        return None
