"""Admin and owner filters for aiogram routers.

Usage — protect an entire router so every handler inside it is restricted:

    from bot.filters.admin import AdminFilter

    router = Router(name="admin")
    router.message.filter(AdminFilter())
    router.callback_query.filter(AdminFilter())

Or use inline on individual handlers:

    @router.callback_query(AdminFilter(), F.data == "some_action")
    async def handler(callback: CallbackQuery) -> None: ...

Both ``AdminFilter`` and ``OwnerFilter`` silently deny access (no message) when
used as router-level filters.  Handlers that want to send a user-facing error
should keep the ``settings.is_admin()`` check and reply themselves; these
filters are primarily a defence-in-depth safeguard so that a handler that
forgets the per-handler check still cannot be reached by non-admins.
"""
from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import settings


def _get_user_id(event: TelegramObject) -> int | None:
    """Extract the sender's user ID from a Message or CallbackQuery event."""
    if isinstance(event, (Message, CallbackQuery)) and event.from_user:
        return event.from_user.id
    return None


class AdminFilter(BaseFilter):
    """Pass only if the event sender is an admin (or owner)."""

    async def __call__(self, event: TelegramObject) -> bool:
        user_id = _get_user_id(event)
        return user_id is not None and settings.is_admin(user_id)


class OwnerFilter(BaseFilter):
    """Pass only if the event sender is the bot owner."""

    async def __call__(self, event: TelegramObject) -> bool:
        user_id = _get_user_id(event)
        return user_id is not None and settings.is_owner(user_id)
