from aiogram import Dispatcher

from bot.handlers.admin import router as admin_router
from bot.handlers.channel import router as channel_router
from bot.handlers.chat_member import router as chat_member_router
from bot.handlers.feedback import router as feedback_router
from bot.handlers.menu import router as menu_router
from bot.handlers.region_request import router as region_request_router
from bot.handlers.schedule import router as schedule_router
from bot.handlers.settings import router as settings_router
from bot.handlers.start import router as start_router


def register_all_handlers(dp: Dispatcher) -> None:
    dp.include_router(start_router)
    dp.include_router(menu_router)
    dp.include_router(schedule_router)
    dp.include_router(feedback_router)
    dp.include_router(region_request_router)
    dp.include_router(chat_member_router)
    dp.include_router(settings_router)
    dp.include_router(channel_router)
    dp.include_router(admin_router)
