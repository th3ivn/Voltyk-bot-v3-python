from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import settings
from bot.db.session import engine, init_db
from bot.handlers import register_all_handlers
from bot.middlewares.db import DbSessionMiddleware
from bot.middlewares.maintenance import MaintenanceMiddleware
from bot.middlewares.throttle import ThrottleMiddleware

logger = logging.getLogger(__name__)

_bg_tasks: list[asyncio.Task] = []


def create_bot() -> Bot:
    return Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())
    dp.my_chat_member.middleware(DbSessionMiddleware())

    dp.message.middleware(MaintenanceMiddleware())
    dp.callback_query.middleware(MaintenanceMiddleware())

    dp.message.middleware(ThrottleMiddleware(rate_limit=0.3))

    register_all_handlers(dp)

    return dp


async def on_startup(bot: Bot) -> None:
    logger.info("🚀 Запуск СвітлоБот v4...")
    await init_db()
    logger.info("✅ База даних ініціалізована")

    me = await bot.get_me()
    logger.info("✨ Бот @%s успішно запущено!", me.username)

    from bot.services.power_monitor import power_monitor_loop
    from bot.services.scheduler import schedule_checker_loop

    _bg_tasks.extend([
        asyncio.create_task(schedule_checker_loop()),
        asyncio.create_task(power_monitor_loop()),
    ])


async def on_shutdown(bot: Bot) -> None:
    logger.info("Shutting down...")
    from bot.services.power_monitor import stop_power_monitor
    from bot.services.scheduler import stop_scheduler

    stop_scheduler()
    stop_power_monitor()

    for task in _bg_tasks:
        task.cancel()
    _bg_tasks.clear()

    await engine.dispose()
    logger.info("Bye!")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    bot = create_bot()
    dp = create_dispatcher()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    try:
        if settings.USE_WEBHOOK:
            from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
            from aiohttp import web

            webhook_url = f"{settings.WEBHOOK_URL}{settings.WEBHOOK_PATH}"
            await bot.set_webhook(
                webhook_url,
                secret_token=settings.WEBHOOK_SECRET or None,
                max_connections=settings.WEBHOOK_MAX_CONNECTIONS,
            )
            logger.info("Webhook set: %s", webhook_url)

            app = web.Application()
            handler = SimpleRequestHandler(
                dispatcher=dp, bot=bot, secret_token=settings.WEBHOOK_SECRET or None,
            )
            handler.register(app, path=settings.WEBHOOK_PATH)
            setup_application(app, dp, bot=bot)

            port = int(os.getenv("PORT", settings.WEBHOOK_PORT))
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", port)
            await site.start()
            logger.info("Webhook server listening on 0.0.0.0:%d", port)

            await asyncio.Event().wait()
        else:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
