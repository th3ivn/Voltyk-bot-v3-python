from aiogram import Router

from bot.handlers.channel.branding import router as branding_router
from bot.handlers.channel.connect import router as connect_router
from bot.handlers.channel.conversation import router as conversation_router
from bot.handlers.channel.format import router as format_router
from bot.handlers.channel.notifications import router as notifications_router
from bot.handlers.channel.pause import router as pause_router
from bot.handlers.channel.settings import router as ch_settings_router
from bot.handlers.channel.test import router as test_router

router = Router(name="channel")
router.include_router(connect_router)
router.include_router(branding_router)
router.include_router(conversation_router)
router.include_router(format_router)
router.include_router(notifications_router)
router.include_router(pause_router)
router.include_router(ch_settings_router)
router.include_router(test_router)
