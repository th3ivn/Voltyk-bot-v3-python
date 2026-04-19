from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from datetime import datetime

import alembic.command as alembic_command
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

from bot.config import settings
from bot.db.queries import get_setting
from bot.db.session import async_session, check_db_connectivity, engine
from bot.handlers import register_all_handlers
from bot.middlewares.db import DbSessionMiddleware
from bot.middlewares.maintenance import MaintenanceMiddleware, load_maintenance_mode
from bot.middlewares.throttle import ThrottleMiddleware
from bot.services import chart_cache
from bot.services.api import (
    close_http_client,
    init_http_client,
    load_last_commit_sha,
    set_chart_render_mode,
)
from bot.services.chart_generator import shutdown_chart_executor
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
_bg_restart_enabled: bool = True


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
            sentry_sdk.capture_exception(exc)

    task.add_done_callback(_on_done)
    _bg_tasks.append(task)
    return task


async def _restart_with_backoff(
    coro_factory,  # callable that returns a new coroutine
    name: str,
    max_retries: int = 5,
    base_delay: float = 5.0,
) -> None:
    """Run coro_factory(), restart with exponential backoff on crash."""
    retries = 0
    while _bg_restart_enabled:
        try:
            await coro_factory()
            return  # clean exit (stop flag set) — don't restart
        except asyncio.CancelledError:
            return  # graceful shutdown
        except Exception as exc:
            retries += 1
            if retries > max_retries:
                logger.critical(
                    "Background task '%s' crashed %d times, giving up: %s",
                    name, retries, exc, exc_info=True,
                )
                return
            delay = min(base_delay * (2 ** (retries - 1)), 300.0)  # max 5 min
            logger.error(
                "Background task '%s' crashed (attempt %d/%d), restarting in %.0fs: %s",
                name, retries, max_retries, delay, exc,
            )
            await asyncio.sleep(delay)


def _bg(coro_factory, name: str) -> asyncio.Task:
    task = asyncio.create_task(
        _restart_with_backoff(coro_factory, name),
        name=name,
    )
    _track_bg_task(task)
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
            if chart_cache.is_usable():
                await chart_cache.ping()

        await asyncio.wait_for(_check_redis(), timeout=3)
    except Exception as e:
        logger.debug("Health check: Redis unreachable: %s", e)
        redis_status = "unreachable"
        healthy = False

    # ── Extended diagnostics (non-blocking) ──────────────────────────────
    memory_mb: int | None = None
    try:
        import resource
        mem = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        memory_mb = mem // 1024 if os.uname().sysname != "Darwin" else mem // (1024 * 1024)
    except Exception:
        pass

    pool_size: int | None = None
    pool_checked_out: int | None = None
    try:
        pool_size = engine.pool.size()  # type: ignore[attr-defined]
        pool_checked_out = engine.pool.checkedout()  # type: ignore[attr-defined]
    except Exception:
        pass

    user_states_count: int | None = None
    dirty_states_count: int | None = None
    try:
        from bot.services.power_monitor import _dirty_states, _user_states
        user_states_count = len(_user_states)
        dirty_states_count = len(_dirty_states)
    except Exception:
        pass

    payload: dict = {
        "status": "ok" if healthy else "degraded",
        "db": db_status,
        "redis": redis_status,
    }
    if memory_mb is not None:
        payload["memory_mb"] = memory_mb
    if pool_size is not None:
        payload["db_pool_size"] = pool_size
        payload["db_pool_checked_out"] = pool_checked_out
    if user_states_count is not None:
        payload["power_states_in_memory"] = user_states_count
        payload["power_dirty_states"] = dirty_states_count

    status_code = 200 if healthy else 503
    return web.json_response(payload, status=status_code)


async def _metrics_handler(_request: web.Request) -> web.Response:
    """Expose Prometheus metrics at /metrics."""
    from bot.utils.metrics import DB_POOL_CHECKED_OUT, DB_POOL_SIZE, metrics_response

    try:
        pool_size = engine.pool.size()  # type: ignore[attr-defined]
        pool_checked_out = engine.pool.checkedout()  # type: ignore[attr-defined]
        DB_POOL_SIZE.set(pool_size)
        DB_POOL_CHECKED_OUT.set(pool_checked_out)
    except Exception:
        pass

    body, content_type = metrics_response()
    # Pass Content-Type via headers= to avoid aiohttp's ValueError when the
    # value contains a charset parameter (CONTENT_TYPE_LATEST includes one).
    return web.Response(body=body, headers={"Content-Type": content_type})


async def _start_health_server() -> None:
    """Start lightweight health endpoint for polling deployments."""
    global _health_runner
    if _health_runner is not None:
        return

    app = web.Application()
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/metrics", _metrics_handler)

    port = int(os.getenv("PORT", "") or settings.HEALTH_PORT)
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
    is_production = settings.ENVIRONMENT == "production"
    storage: RedisStorage | MemoryStorage
    if not redis_url:
        if is_production:
            raise RuntimeError(
                "REDIS_URL is required in production — MemoryStorage loses FSM "
                "state on restart.  Set REDIS_URL or change ENVIRONMENT for dev."
            )
        storage = MemoryStorage()
        logger.warning("⚠️  REDIS_URL not set — MemoryStorage, FSM state буде втрачено при рестарті")
    else:
        try:
            storage = RedisStorage.from_url(redis_url)
            logger.info("✅ Redis FSM storage configured")
        except Exception as e:
            if is_production:
                raise RuntimeError(
                    f"Cannot configure Redis FSM storage in production: {e}. "
                    "Silent fallback to MemoryStorage would drop FSM state on "
                    "every restart — refusing to start."
                ) from e
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
    global _bg_restart_enabled
    _bg_restart_enabled = True  # reset in case on_shutdown ran earlier in this process

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
    if settings.AUTO_MIGRATE:
        await _run_migrations()
    else:
        logger.info("AUTO_MIGRATE=False — skipping automatic migrations")
    await check_db_connectivity()
    logger.info("✅ База даних ініційована")

    await load_maintenance_mode()

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
            await asyncio.wait_for(bot.send_message(_admin_id, _startup_text), timeout=5)
        except Exception as e:
            logger.warning("Failed to notify admin %s on startup: %s", _admin_id, e)

    _bg(lambda: power_monitor_loop(bot), "power_monitor_loop")
    _bg(lambda: daily_ping_error_loop(bot), "daily_ping_error_loop")
    _bg(lambda: schedule_checker_loop(bot), "schedule_checker_loop")
    _bg(lambda: daily_flush_loop(bot), "daily_flush_loop")
    _bg(lambda: reminder_checker_loop(bot), "reminder_checker_loop")

async def on_shutdown(bot: Bot) -> None:
    logger.info("Shutting down...")

    # Notify admins that bot is stopping
    _now = datetime.now(settings.timezone)
    _shutdown_text = f"⛔ <b>Бот зупинено</b>\n🕐 {_now.strftime('%H:%M')} {_now.strftime('%d.%m.%Y')}"
    for _admin_id in settings.all_admin_ids:
        try:
            await asyncio.wait_for(bot.send_message(_admin_id, _shutdown_text), timeout=5)
        except Exception as e:
            logger.warning("Failed to notify admin %s on shutdown: %s", _admin_id, e)

    await save_states_on_shutdown()

    stop_scheduler()
    stop_power_monitor()

    global _bg_restart_enabled
    _bg_restart_enabled = False

    # Give tasks up to 10s to finish gracefully before cancelling
    if _bg_tasks:
        done, pending = await asyncio.wait(list(_bg_tasks), timeout=10)
        if pending:
            logger.warning("Graceful shutdown timeout: cancelling %d task(s)", len(pending))
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    _bg_tasks.clear()

    shutdown_chart_executor()  # stop chart render threads
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
            app.router.add_get("/metrics", _metrics_handler)

            handler = SimpleRequestHandler(
                dispatcher=dp, bot=bot, secret_token=settings.WEBHOOK_SECRET or None,
            )
            handler.register(app, path=settings.WEBHOOK_PATH)
            setup_application(app, dp, bot=bot)

            port = int(os.getenv("PORT", "") or settings.WEBHOOK_PORT)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", port)
            await site.start()
            logger.info("Webhook server listening on 0.0.0.0:%d", port)

            try:
                await asyncio.Event().wait()
            finally:
                with suppress(asyncio.CancelledError):
                    await runner.cleanup()
        else:
            await _start_health_server()
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
