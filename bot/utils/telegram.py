from __future__ import annotations

from aiogram.types import Message

from bot.utils.logger import get_logger

logger = get_logger(__name__)

MSG_NOT_MODIFIED = "message is not modified"


async def safe_edit_text(message: Message, text: str, reply_markup=None, parse_mode: str = "HTML") -> bool:
    """Safely edit message text, handling 'message not modified' errors.

    Returns True if the edit succeeded (or the message was already up-to-date),
    False on any other error.
    """
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return True
    except Exception as e:
        if MSG_NOT_MODIFIED in str(e):
            return True
        logger.warning("safe_edit_text failed: %s", e)
        return False


async def safe_delete(message: Message) -> None:
    """Safely delete a message, logging non-fatal errors at DEBUG level."""
    try:
        await message.delete()
    except Exception as e:
        logger.debug("Could not delete message: %s", e)


async def safe_edit_or_resend(
    message: Message,
    text: str,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> Message | None:
    """Edit a text message in-place, or delete-and-resend when the message contains a photo.

    Returns the new or original Message object on success, or None on unexpected error.
    """
    try:
        if message.photo:
            await safe_delete(message)
            return await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            if not await safe_edit_text(message, text, reply_markup=reply_markup, parse_mode=parse_mode):
                return await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
            return message
    except Exception as e:
        logger.error("safe_edit_or_resend failed: %s", e)
        return None
