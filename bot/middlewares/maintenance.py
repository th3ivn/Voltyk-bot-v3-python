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
        if not type(self)._enabled:
            return await handler(event, data)

        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id and settings.is_admin(user_id):
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer(type(self)._message, show_alert=True)
            return None

        if isinstance(event, Message):
            await event.reply(type(self)._message)
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


async def persist_maintenance_mode(enabled: bool, message: str | None = None) -> None:
    """Persist maintenance state to DB so it survives bot restarts."""
    from bot.db.queries import set_setting
    from bot.db.session import async_session

    set_maintenance_mode(enabled, message)
    try:
        async with async_session() as session:
            await set_setting(session, "maintenance_enabled", "1" if enabled else "0")
            await set_setting(session, "maintenance_message", message or "")
            await session.commit()
        logger.info("Maintenance mode persisted: enabled=%s", enabled)
    except Exception as e:
        logger.warning("Could not persist maintenance mode to DB: %s", e)


async def load_maintenance_mode() -> None:
    """Load maintenance state from DB on startup."""
    from bot.db.queries import get_setting
    from bot.db.session import async_session

    try:
        async with async_session() as session:
            enabled_raw = await get_setting(session, "maintenance_enabled")
            message_raw = await get_setting(session, "maintenance_message")
        enabled = enabled_raw == "1"
        message = message_raw or None
        set_maintenance_mode(enabled, message)
        if enabled:
            logger.warning("Maintenance mode restored from DB: enabled=True, message=%r", message)
    except Exception as e:
        logger.warning("Could not load maintenance mode from DB: %s", e)
