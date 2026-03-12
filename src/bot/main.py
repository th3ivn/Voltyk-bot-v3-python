from __future__ import annotations

import asyncio

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from loguru import logger

from src.bot.handlers.start import router as start_router
from src.core.config import Settings, get_settings
from src.core.logging import setup_logging
from src.db.engine import close_engine, init_engine


def create_bot(settings: Settings) -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(start_router)
    return dp


async def on_startup(bot: Bot, settings: Settings) -> None:
    webhook_url = f"{settings.webhook_url}{settings.webhook_path}"
    await bot.set_webhook(
        url=webhook_url,
        secret_token=settings.webhook_secret or None,
        drop_pending_updates=True,
    )
    logger.info("Webhook set: {}", webhook_url)
    print("Webhook set successfully")


async def on_shutdown(bot: Bot) -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    await close_engine()
    logger.info("Bot shutdown complete")


async def health_handler(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def run_webhook() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    # Init database
    init_engine(settings)

    bot = create_bot(settings)
    dp = create_dispatcher()

    async def _on_startup() -> None:
        await on_startup(bot, settings)

    async def _on_shutdown() -> None:
        await on_shutdown(bot)

    dp.startup.register(_on_startup)
    dp.shutdown.register(_on_shutdown)

    app = web.Application()
    app.router.add_get("/health", health_handler)

    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=settings.webhook_secret or None,
    )
    webhook_handler.register(app, path=settings.webhook_path)

    setup_application(app, dp, bot=bot)

    logger.info("Starting webhook server on port {}", settings.port)
    web.run_app(app, host="0.0.0.0", port=settings.port)


def run_polling() -> None:
    """Polling mode for local development."""
    settings = get_settings()
    setup_logging(settings.log_level)

    init_engine(settings)

    bot = create_bot(settings)
    dp = create_dispatcher()

    async def _run() -> None:
        logger.info("Starting polling mode...")
        try:
            await dp.start_polling(bot, skip_updates=True)
        finally:
            await close_engine()

    asyncio.run(_run())
