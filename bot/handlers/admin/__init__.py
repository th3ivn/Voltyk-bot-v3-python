from aiogram import Router

from bot.handlers.admin.admin_router import router as admin_router_r
from bot.handlers.admin.broadcast import router as broadcast_router
from bot.handlers.admin.database import router as database_router
from bot.handlers.admin.growth import router as growth_router
from bot.handlers.admin.intervals import router as intervals_router
from bot.handlers.admin.maintenance import router as maintenance_router
from bot.handlers.admin.panel import router as panel_router
from bot.handlers.admin.pause import router as pause_router

router = Router(name="admin")
router.include_router(panel_router)
router.include_router(broadcast_router)
router.include_router(maintenance_router)
router.include_router(growth_router)
router.include_router(intervals_router)
router.include_router(pause_router)
router.include_router(admin_router_r)
router.include_router(database_router)
