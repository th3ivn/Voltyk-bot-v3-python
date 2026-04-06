from __future__ import annotations

from aiogram import Router

from .help import router as _help_router
from .navigation import router as _navigation_router
from .reminders import router as _reminders_router
from .schedule import _send_schedule_photo
from .schedule import router as _schedule_router
from .settings import router as _settings_router
from .stats import router as _stats_router
from .timer import router as _timer_router

router = Router(name="menu")
router.include_router(_navigation_router)
router.include_router(_schedule_router)
router.include_router(_timer_router)
router.include_router(_stats_router)
router.include_router(_help_router)
router.include_router(_settings_router)
router.include_router(_reminders_router)

__all__ = ["router", "_send_schedule_photo"]
