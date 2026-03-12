"""Application entry point.

Starts the bot in polling mode (default) or webhook mode
depending on whether WEBHOOK_URL is configured.
"""

import asyncio
import logging

from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from app.bot import bot, dp
from app.config import settings
from app.db.engine import engine


def configure_logging() -> None:
    """Configure root logger level from settings."""
    logging.basicConfig(
        level=settings.LOG_LEVEL.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


# ---------------------------------------------------------------------------
# Database migration helper
# ---------------------------------------------------------------------------


async def run_migrations() -> None:
    """Run Alembic migrations programmatically on startup."""
    import asyncio as _asyncio  # noqa: I001
    from alembic import command
    from alembic.config import Config

    log = logging.getLogger(__name__)
    log.info("Running database migrations...")

    def _run_sync() -> None:
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")

    loop = _asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_sync)
    log.info("Database migrations complete.")


# ---------------------------------------------------------------------------
# Startup / shutdown hooks
# ---------------------------------------------------------------------------


async def on_startup() -> None:
    """Run on application startup."""
    logging.getLogger(__name__).info("Starting Voltyk Bot...")
    await run_migrations()
    if settings.WEBHOOK_URL:
        await bot.set_webhook(
            url=settings.WEBHOOK_URL,
            secret_token=settings.WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
        logging.getLogger(__name__).info("Webhook set: %s", settings.WEBHOOK_URL)


async def on_shutdown() -> None:
    """Run on application shutdown — close DB engine and bot session."""
    logging.getLogger(__name__).info("Shutting down Voltyk Bot...")
    await engine.dispose()
    await bot.session.close()
    if settings.WEBHOOK_URL:
        await bot.delete_webhook()


# ---------------------------------------------------------------------------
# Run modes
# ---------------------------------------------------------------------------


async def run_polling() -> None:
    """Start the bot in long-polling mode."""
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


def run_webhook() -> None:
    """Start the bot in webhook mode using aiohttp."""
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=settings.WEBHOOK_SECRET).register(
        app, path="/webhook"
    )
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=settings.PORT)  # noqa: S104


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Choose polling or webhook mode and start the bot."""
    configure_logging()
    if settings.WEBHOOK_URL:
        run_webhook()
    else:
        asyncio.run(run_polling())


if __name__ == "__main__":
    main()
