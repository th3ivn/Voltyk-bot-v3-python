from __future__ import annotations

from aiogram import Router

from bot.handlers.settings.alerts import router as alerts_router
from bot.handlers.settings.channel import router as channel_settings_router
from bot.handlers.settings.cleanup import router as cleanup_router
from bot.handlers.settings.data import router as data_router
from bot.handlers.settings.emergency import router as emergency_router
from bot.handlers.settings.ip import router as ip_router
from bot.handlers.settings.region import router as region_router

router = Router(name="settings")
router.include_router(region_router)
router.include_router(alerts_router)
router.include_router(ip_router)
router.include_router(emergency_router)
router.include_router(channel_settings_router)
router.include_router(cleanup_router)
router.include_router(data_router)
