from __future__ import annotations

import re

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, MaybeInaccessibleMessage, Message

from bot.utils.logger import get_logger

logger = get_logger(__name__)

MSG_NOT_MODIFIED = "message is not modified"

# Telegram exceptions that indicate the message is already gone / immutable
_EXPECTED_TELEGRAM_ERRORS = (TelegramBadRequest, TelegramForbiddenError)
_CALLBACK_ANSWER_EXPIRED_ERRORS = ("query is too old", "query ID is invalid")

_TG_EMOJI_RE = re.compile(r'<tg-emoji[^>]*>([^<]*)</tg-emoji>')


async def safe_edit_text(
    message: MaybeInaccessibleMessage | None,
    text: str,
    reply_markup=None,
    parse_mode: str = "HTML",
    **kwargs,
) -> bool:
    """Safely edit message text, handling 'message not modified' errors.

    When the first edit attempt fails, strips <tg-emoji> tags from the text and
    retries once (useful for clients that do not support custom emoji).
    Returns True if the edit succeeded (or the message was already up-to-date),
    False on any Telegram error.
    """
    if not isinstance(message, Message):
        return False
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode, **kwargs)
        return True
    except _EXPECTED_TELEGRAM_ERRORS as e:
        if MSG_NOT_MODIFIED in str(e):
            return True
        # Strip <tg-emoji> tags and retry if the text contains them
        clean = _TG_EMOJI_RE.sub(r'\1', text)
        if clean != text:
            try:
                await message.edit_text(clean, reply_markup=reply_markup, parse_mode=parse_mode, **kwargs)
                return True
            except _EXPECTED_TELEGRAM_ERRORS as e2:
                if MSG_NOT_MODIFIED in str(e2):
                    return True
                logger.warning("safe_edit_text failed (tg-emoji fallback): %s", e2)
                return False
        logger.warning("safe_edit_text failed: %s", e)
        return False


async def safe_edit_reply_markup(
    message: MaybeInaccessibleMessage | None,
    reply_markup=None,
) -> bool:
    """Safely edit message reply markup, handling 'message not modified' errors.

    Returns True if the edit succeeded (or the message was already up-to-date),
    False on any Telegram error.
    """
    if not isinstance(message, Message):
        return False
    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
        return True
    except _EXPECTED_TELEGRAM_ERRORS as e:
        if MSG_NOT_MODIFIED in str(e):
            return True
        logger.warning("safe_edit_reply_markup failed: %s", e)
        return False


async def safe_delete(message: MaybeInaccessibleMessage | None) -> None:
    """Safely delete a message, ignoring expected Telegram errors."""
    if not isinstance(message, Message):
        return
    try:
        await message.delete()
    except _EXPECTED_TELEGRAM_ERRORS as e:
        logger.debug("Could not delete message: %s", e)


def is_expired_callback_answer_error(error: TelegramBadRequest) -> bool:
    """Return True when callback answer failed because query has already expired."""
    text = str(error)
    return any(fragment in text for fragment in _CALLBACK_ANSWER_EXPIRED_ERRORS)


async def safe_answer_callback(
    callback: CallbackQuery,
    text: str | None = None,
    show_alert: bool | None = None,
    **kwargs,
) -> bool:
    """Best-effort callback answer that suppresses stale-query Telegram errors.

    Returns ``True`` if callback answer succeeded.
    Returns ``False`` only when Telegram reports an expired/invalid callback query id.
    Re-raises all other unexpected exceptions so callers don't hide real issues.
    """
    answer_kwargs = dict(kwargs)
    if show_alert is not None:
        answer_kwargs["show_alert"] = show_alert
    try:
        if text is None:
            await callback.answer(**answer_kwargs)
        else:
            await callback.answer(text, **answer_kwargs)
        return True
    except TelegramBadRequest as e:
        if is_expired_callback_answer_error(e):
            logger.debug("Ignoring expired callback answer: %s", e)
            return False
        raise


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
