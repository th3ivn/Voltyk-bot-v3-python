from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import MaybeInaccessibleMessage, Message

from bot.utils.logger import get_logger

logger = get_logger(__name__)

MSG_NOT_MODIFIED = "message is not modified"

# Telegram exceptions that indicate the message is already gone / immutable
_EXPECTED_TELEGRAM_ERRORS = (TelegramBadRequest, TelegramForbiddenError)


async def safe_edit_text(
    message: MaybeInaccessibleMessage | None,
    text: str,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> bool:
    """Safely edit message text, handling 'message not modified' errors.

    Returns True if the edit succeeded (or the message was already up-to-date),
    False on any Telegram error.
    """
    if not isinstance(message, Message):
        return False
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return True
    except _EXPECTED_TELEGRAM_ERRORS as e:
        if MSG_NOT_MODIFIED in str(e):
            return True
        logger.warning("safe_edit_text failed: %s", e)
        return False


async def safe_delete(message: MaybeInaccessibleMessage | None) -> None:
    """Safely delete a message, ignoring expected Telegram errors."""
    if not isinstance(message, Message):
        return
    try:
        await message.delete()
    except _EXPECTED_TELEGRAM_ERRORS as e:
        logger.debug("Could not delete message: %s", e)


async def safe_edit_or_resend(
    message: MaybeInaccessibleMessage | None,
    text: str,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> Message | None:
    """Edit a text message in-place, or delete-and-resend when the message contains a photo.

    Returns the new or original Message object on success, or None if message is unavailable.
    """
    if not isinstance(message, Message):
        return None
    try:
        if message.photo:
            await safe_delete(message)
            return await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            if not await safe_edit_text(message, text, reply_markup=reply_markup, parse_mode=parse_mode):
                return await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
            return message
    except _EXPECTED_TELEGRAM_ERRORS as e:
        logger.warning("safe_edit_or_resend failed: %s", e)
        return None

