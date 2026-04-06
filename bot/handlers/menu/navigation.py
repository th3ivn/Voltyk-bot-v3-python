from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_user_by_telegram_id
from bot.formatter.messages import format_main_menu_message
from bot.keyboards.inline import get_main_menu
from bot.utils.logger import get_logger
from bot.utils.telegram import safe_delete, safe_edit_text

logger = get_logger(__name__)
router = Router(name="menu_navigation")


@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await safe_edit_text(callback.message, "❌ Спочатку запустіть бота, натиснувши /start")
        return

    # Delete previous menu message if it exists and differs from the current one
    if user.last_menu_message_id and user.last_menu_message_id != callback.message.message_id:
        try:
            await callback.bot.delete_message(callback.message.chat.id, user.last_menu_message_id)
        except Exception as e:
            logger.debug("Could not delete old menu message %s: %s", user.last_menu_message_id, e)

    text = format_main_menu_message(user)
    has_channel = bool(user.channel_config and user.channel_config.channel_id)
    channel_paused = bool(user.channel_config and user.channel_config.channel_paused)
    kb = get_main_menu(channel_paused=channel_paused, has_channel=has_channel)

    if callback.message.photo:
        await safe_delete(callback.message)
        msg = await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        if await safe_edit_text(callback.message, text, reply_markup=kb):
            msg = callback.message
        else:
            msg = await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    user.last_menu_message_id = msg.message_id
