from __future__ import annotations

import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from bot.config import settings
from bot.db.session import engine, init_db
from bot.handlers import register_all_handlers
from bot.middlewares.db import DbSessionMiddleware
from bot.middlewares.maintenance import MaintenanceMiddleware
from bot.middlewares.throttle import ThrottleMiddleware
from bot.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)

_bg_tasks: list[asyncio.Task] = []

async def _run_migrations() -> None:
    """Apply pending Alembic migrations programmatically at startup."""
    from alembic.config import Config

    from alembic import command

    def _upgrade() -> None:
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
        command.upgrade(cfg, "head")

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _upgrade)
    logger.info("Alembic migrations applied")

def create_bot() -> Bot:
    return Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

def create_dispatcher() -> Dispatcher:
    redis_url = settings.REDIS_URL
    if redis_url and "localhost" not in redis_url:
        storage = RedisStorage.from_url(redis_url)
        logger.info("✅ Redis FSM storage (%s)", redis_url.split("@")[-1])
    else:
        storage = MemoryStorage()
        logger.warning("⚠️  MemoryStorage — FSM state буде втрачено при рестарті")
    dp = Dispatcher(storage=storage)

    dp.message.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())
    dp.my_chat_member.middleware(DbSessionMiddleware())

    dp.message.middleware(MaintenanceMiddleware())
    dp.callback_query.middleware(MaintenanceMiddleware())

    dp.message.middleware(ThrottleMiddleware(rate_limit=0.3))

    register_all_handlers(dp)

    return dp

async def on_startup(bot: Bot) -> None:
    import sentry_sdk
    from sentry_sdk.integrations.aiohttp import AioHttpIntegration
    from sentry_sdk.integrations.asyncio import AsyncioIntegration

    if settings.SENTRY_DSN:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            traces_sample_rate=0.1,
            environment=settings.ENVIRONMENT,
            integrations=[
                AsyncioIntegration(),
                AioHttpIntegration(),
            ],
        )
        logger.info("✅ Sentry ініційований (environment=%s)", settings.ENVIRONMENT)
    logger.info("🚀 Запуск Вольтик v4...")
    await _run_migrations()
    await init_db()
    logger.info("✅ База даних ініційована")

    from bot.services.api import init_http_client
    await init_http_client()
    logger.info("✅ HTTP client ініційований")

    me = await bot.get_me()
    logger.info("✨ Бот @%s успішно запущено!", me.username)

    from bot.services.power_monitor import daily_ping_error_loop, power_monitor_loop
    from bot.services.scheduler import daily_flush_loop, reminder_checker_loop, schedule_checker_loop

    _bg_tasks.extend([
        asyncio.create_task(schedule_checker_loop(bot)),
        asyncio.create_task(power_monitor_loop(bot)),
        asyncio.create_task(daily_ping_error_loop(bot)),
        asyncio.create_task(daily_flush_loop(bot)),
        asyncio.create_task(reminder_checker_loop(bot)),
    ])

async def on_shutdown(bot: Bot) -> None:
    logger.info("Shutting down...")
    from bot.services.api import close_http_client
    from bot.services.power_monitor import stop_power_monitor
    from bot.services.scheduler import stop_scheduler

    stop_scheduler()
    stop_power_monitor()

    for task in _bg_tasks:
        task.cancel()
    await asyncio.gather(*_bg_tasks, return_exceptions=True)
    _bg_tasks.clear()

    await close_http_client()
    await engine.dispose()
    logger.info("Bye!")

async def main() -> None:
    setup_logging()

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

            async def health_handler(_request: web.Request) -> web.Response:
                return web.json_response({"status": "ok"})

            app.router.add_get("/health", health_handler)

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
