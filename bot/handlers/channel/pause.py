from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_user_by_telegram_id
from bot.formatter.messages import format_main_menu_message
from bot.keyboards.inline import get_main_menu
from bot.utils.logger import get_logger
from bot.utils.telegram import safe_edit_text

logger = get_logger(__name__)
router = Router(name="channel_pause")


@router.callback_query(F.data == "channel_pause")
async def channel_pause(callback: CallbackQuery) -> None:
    await callback.answer()
    await safe_edit_text(callback.message,
        "Ви впевнені, що хочете тимчасово зупинити свій канал?\n\n"
        "Користувачі отримають повідомлення, що канал зупинено.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Скасувати", callback_data="back_to_main")],
                [InlineKeyboardButton(text="Так, зупинити", callback_data="channel_pause_confirm")],
            ]
        ),
    )


@router.callback_query(F.data == "channel_pause_confirm")
async def channel_pause_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.answer("❌ Помилка")
        return
    if user.channel_config and user.channel_config.channel_id:
        user.channel_config.channel_paused = True
        try:
            await callback.bot.send_message(
                user.channel_config.channel_id,
                "⚠ Канал зупинено на технічну перерву!",
            )
        except Exception as e:
            logger.warning("Could not send pause notice to channel %s: %s", user.channel_config.channel_id, e)
    await callback.answer("✅ Канал зупинено")
    text = format_main_menu_message(user)
    await safe_edit_text(callback.message,
        text,
        reply_markup=get_main_menu(channel_paused=True, has_channel=True),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "channel_resume")
async def channel_resume(callback: CallbackQuery) -> None:
    await callback.answer()
    await safe_edit_text(callback.message,
        "Ви впевнені, що хочете відновити роботу каналу?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Скасувати", callback_data="back_to_main")],
                [InlineKeyboardButton(text="Так, відновити", callback_data="channel_resume_confirm")],
            ]
        ),
    )


@router.callback_query(F.data == "channel_resume_confirm")
async def channel_resume_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.answer("❌ Помилка")
        return
    if user.channel_config and user.channel_config.channel_id:
        user.channel_config.channel_paused = False
        try:
            await callback.bot.send_message(
                user.channel_config.channel_id,
                "✅ Роботу каналу відновлено!",
            )
        except Exception as e:
            logger.warning("Could not send resume notice to channel %s: %s", user.channel_config.channel_id, e)
    await callback.answer("✅ Канал відновлено")
    text = format_main_menu_message(user)
    await safe_edit_text(callback.message,
        text,
        reply_markup=get_main_menu(channel_paused=False, has_channel=True),
        parse_mode="HTML",
    )
