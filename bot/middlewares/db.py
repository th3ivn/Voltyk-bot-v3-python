from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.db.session import async_session
from bot.utils.logger import get_logger

logger = get_logger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with async_session() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception as exc:
                try:
                    await session.rollback()
                except Exception as rb_exc:
                    # Log rollback failure but always re-raise the original exception
                    # so callers (and Sentry) see the real error, not a rollback error.
                    logger.error("Session rollback failed: %s (original error: %s)", rb_exc, exc)
                raise
