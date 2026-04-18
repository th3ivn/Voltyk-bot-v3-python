from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.db.session import async_session
from bot.utils.logger import get_logger
from bot.utils.metrics import ACTIVE_DB_SESSIONS, DB_SESSION_DURATION_SECONDS

logger = get_logger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        ACTIVE_DB_SESSIONS.inc()
        t0 = time.perf_counter()
        try:
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
                        # Log rollback failure with full traceback but always re-raise the
                        # original exception so callers (and Sentry) see the real error.
                        logger.error(
                            "Session rollback failed (original error: %s)",
                            exc,
                            exc_info=rb_exc,
                        )
                    raise
        finally:
            DB_SESSION_DURATION_SECONDS.observe(time.perf_counter() - t0)
            ACTIVE_DB_SESSIONS.dec()
