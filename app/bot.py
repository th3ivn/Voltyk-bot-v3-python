"""Bot and Dispatcher factory.

Creates the aiogram Bot and Dispatcher instances used throughout the app.
Middlewares and routers are registered here as they are implemented.
"""

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from app.config import settings


def build_bot() -> Bot:
    """Create and return the aiogram Bot instance."""
    return Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_dispatcher() -> Dispatcher:
    """Create Dispatcher with Redis FSM storage, middlewares and routers."""
    storage = RedisStorage.from_url(settings.REDIS_URL)
    dp = Dispatcher(storage=storage)

    # --- Middlewares ---
    from app.db.session import AsyncSessionFactory
    from app.middleware.database import DatabaseMiddleware

    dp.update.middleware(DatabaseMiddleware(AsyncSessionFactory))

    # --- Routers ---
    from app.handlers import register_all_handlers

    register_all_handlers(dp)

    return dp


bot: Bot = build_bot()
dp: Dispatcher = build_dispatcher()
