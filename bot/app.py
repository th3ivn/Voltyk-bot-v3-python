from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from datetime import datetime

import sentry_sdk
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from alembic.config import Config as AlembicConfig
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from sentry_sdk.integrations.asyncio import AsyncioIntegration

from alembic import command as alembic_command
from bot.config import settings
from bot.db.queries import get_setting
from bot.db.session import async_session, check_db_connectivity, engine
from bot.handlers import register_all_handlers
from bot.middlewares.db import DbSessionMiddleware
from bot.middlewares.maintenance import MaintenanceMiddleware
from bot.middlewares.throttle import ThrottleMiddleware
from bot.services import chart_cache
from bot.services.api import (
    close_http_client,
    init_http_client,
    load_last_commit_sha,
    set_chart_render_mode,
)
from bot.services.power_monitor import (
    daily_ping_error_loop,
    power_monitor_loop,
    save_states_on_shutdown,
    stop_power_monitor,
)
from bot.services.scheduler import (
    daily_flush_loop,
    reminder_checker_loop,
    schedule_checker_loop,
    stop_scheduler,
)
from bot.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)

_bg_tasks: list[asyncio.Task] = []
_health_runner = None


def _track_bg_task(task: asyncio.Task) -> asyncio.Task:
    """Track background task, log unexpected crashes, and auto-remove on completion."""

    def _on_done(done_task: asyncio.Task) -> None:
        # Remove from tracking list so we don't hold a reference to finished tasks.
        with suppress(ValueError):
            _bg_tasks.remove(done_task)
        if done_task.cancelled():
            return
        exc = done_task.exception()
        if exc is not None:
            logger.exception("Background task %s crashed", done_task.get_name(), exc_info=exc)

    task.add_done_callback(_on_done)
    _bg_tasks.append(task)
    return task

async def _run_migrations() -> None:
    """Apply pending Alembic migrations programmatically at startup."""

    def _upgrade() -> None:
        # Resolve alembic.ini relative to this file so the bot can be started
        # from any working directory (e.g. inside a Docker container).
        ini_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini")
        cfg = AlembicConfig(ini_path)
        cfg.set_main_option("sqlalchemy.url", settings.sync_database_url)
        alembic_command.upgrade(cfg, "head")

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _upgrade)
    logger.info("Alembic migrations applied")


async def _health_handler(_request: web.Request) -> web.Response:
    """Shared /health handler used in both polling and webhook modes."""
    from sqlalchemy import text

    db_status = "ok"
    redis_status = "ok"
    healthy = True

    try:
        async def _check_db() -> None:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

        await asyncio.wait_for(_check_db(), timeout=3)
    except Exception as e:
        logger.debug("Health check: DB unreachable: %s", e)
        db_status = "unreachable"
        healthy = False

    try:
        async def _check_redis() -> None:
            if chart_cache._redis is not None:
                await chart_cache._redis.ping()  # type: ignore[misc]

        await asyncio.wait_for(_check_redis(), timeout=3)
    except Exception as e:
        logger.debug("Health check: Redis unreachable: %s", e)
        redis_status = "unreachable"
        healthy = False

    payload = {"status": "ok" if healthy else "degraded", "db": db_status, "redis": redis_status}
    status_code = 200 if healthy else 503
    return web.json_response(payload, status=status_code)


async def _start_health_server() -> None:
    """Start lightweight health endpoint for polling deployments."""
    global _health_runner
    if _health_runner is not None:
        return

    app = web.Application()
    app.router.add_get("/health", _health_handler)

    port = int(os.getenv("PORT", settings.HEALTH_PORT))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    _health_runner = runner
    logger.info("Health server listening on 0.0.0.0:%d", port)


async def _stop_health_server() -> None:
    global _health_runner
    if _health_runner is None:
        return
    with suppress(Exception):
        await _health_runner.cleanup()
    _health_runner = None

def create_bot() -> Bot:
    return Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

def create_dispatcher() -> Dispatcher:
    redis_url = settings.REDIS_URL
    storage: RedisStorage | MemoryStorage
    if not redis_url:
        storage = MemoryStorage()
        logger.warning("⚠️  REDIS_URL not set — MemoryStorage, FSM state буде втрачено при рестарті")
    else:
        try:
            storage = RedisStorage.from_url(redis_url)
            logger.info("✅ Redis FSM storage configured")
        except Exception as e:
            storage = MemoryStorage()
            logger.warning(
                "⚠️  Could not configure Redis FSM storage (%s); falling back to MemoryStorage",
                e,
            )
    dp = Dispatcher(storage=storage)

    dp.message.middleware(MaintenanceMiddleware())
    dp.callback_query.middleware(MaintenanceMiddleware())

    dp.message.middleware(ThrottleMiddleware(rate_limit=0.3))
    dp.callback_query.middleware(ThrottleMiddleware(rate_limit=0.2))

    dp.message.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())
    dp.my_chat_member.middleware(DbSessionMiddleware())

    register_all_handlers(dp)

    return dp

async def on_startup(bot: Bot) -> None:
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
    await check_db_connectivity()
    logger.info("✅ База даних ініційована")

    await init_http_client()
    logger.info("✅ HTTP client ініційований")

    await chart_cache.init()

    await load_last_commit_sha()
    logger.info("✅ Стан коміту відновлено з БД")

    me = await bot.get_me()
    logger.info("✨ Бот @%s успішно запущено!", me.username)

    # Load chart render mode from DB
    async with async_session() as _s:
        _mode = await get_setting(_s, "chart_render_mode") or "on_change"
        set_chart_render_mode(on_demand=(_mode == "on_demand"))
    logger.info("Chart render mode: %s", _mode)

    # Notify admins that bot started
    _now = datetime.now(settings.timezone)
    _startup_text = f"✅ <b>Бот запущено</b>\n🕐 {_now.strftime('%H:%M')} {_now.strftime('%d.%m.%Y')}"
    for _admin_id in settings.all_admin_ids:
        try:
            await bot.send_message(_admin_id, _startup_text)
        except Exception as e:
            logger.warning("Failed to notify admin %s on startup: %s", _admin_id, e)

    _track_bg_task(asyncio.create_task(schedule_checker_loop(bot), name="schedule_checker_loop"))
    _track_bg_task(asyncio.create_task(power_monitor_loop(bot), name="power_monitor_loop"))
    _track_bg_task(asyncio.create_task(daily_ping_error_loop(bot), name="daily_ping_error_loop"))
    _track_bg_task(asyncio.create_task(daily_flush_loop(bot), name="daily_flush_loop"))
    _track_bg_task(asyncio.create_task(reminder_checker_loop(bot), name="reminder_checker_loop"))

async def on_shutdown(bot: Bot) -> None:
    logger.info("Shutting down...")

    # Notify admins that bot is stopping
    _now = datetime.now(settings.timezone)
    _shutdown_text = f"⛔ <b>Бот зупинено</b>\n🕐 {_now.strftime('%H:%M')} {_now.strftime('%d.%m.%Y')}"
    for _admin_id in settings.all_admin_ids:
        try:
            await bot.send_message(_admin_id, _shutdown_text)
        except Exception as e:
            logger.warning("Failed to notify admin %s on shutdown: %s", _admin_id, e)

    await save_states_on_shutdown()

    stop_scheduler()
    stop_power_monitor()

    for task in _bg_tasks:
        task.cancel()
    await asyncio.gather(*_bg_tasks, return_exceptions=True)
    _bg_tasks.clear()

    await close_http_client()
    await _stop_health_server()

    await chart_cache.close()

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
            webhook_url = f"{settings.WEBHOOK_URL}{settings.WEBHOOK_PATH}"
            await bot.set_webhook(
                webhook_url,
                secret_token=settings.WEBHOOK_SECRET or None,
                max_connections=settings.WEBHOOK_MAX_CONNECTIONS,
            )
            logger.info("Webhook set: %s", webhook_url)

            app = web.Application()
            app.router.add_get("/health", _health_handler)

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

            try:
                await asyncio.Event().wait()
            finally:
                await runner.cleanup()
        else:
            await _start_health_server()
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
