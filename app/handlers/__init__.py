"""Handler registration."""

from aiogram import Dispatcher

from app.handlers.start import router as start_router


def register_all_handlers(dp: Dispatcher) -> None:
    """Register all routers with the dispatcher."""
    dp.include_router(start_router)
