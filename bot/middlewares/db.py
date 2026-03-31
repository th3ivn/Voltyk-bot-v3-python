from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from bot.db.session import async_session
from bot.utils.logger import get_logger

logger = get_logger(__name__)

_DB_UNAVAILABLE_MSG = "⚠️ Сервіс тимчасово недоступний. Спробуйте через кілька хвилин."


class DbSessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            async with async_session() as session:
                data["session"] = session
                try:
                    result = await handler(event, data)
                    await session.commit()
                    return result
                except (OperationalError, SQLAlchemyError) as exc:
                    await session.rollback()
                    logger.error("DB error in handler: %s", exc)
                    await _reply_db_error(event)
                    return None
                except Exception:
                    await session.rollback()
                    raise
        except (OperationalError, SQLAlchemyError) as exc:
            # DB connection could not be established at all (e.g. quota exceeded)
            logger.error("DB connection failed in middleware: %s", exc)
            await _reply_db_error(event)
            return None


async def _reply_db_error(event: TelegramObject) -> None:
    """Send a graceful error message when the DB is unreachable."""
    try:
        if isinstance(event, Message):
            await event.reply(_DB_UNAVAILABLE_MSG)
        elif isinstance(event, CallbackQuery):
            await event.answer(_DB_UNAVAILABLE_MSG, show_alert=True)
    except Exception:
        pass
