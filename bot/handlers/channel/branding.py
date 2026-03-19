from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_user_by_telegram_id
from bot.states.fsm import ChannelConversationSG
from bot.utils.helpers import CHANNEL_NAME_PREFIX
from bot.utils.logger import get_logger

logger = get_logger(__name__)
router = Router(name="channel_branding")


@router.callback_query(F.data == "channel_edit_title")
async def channel_edit_title(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.channel_config or not user.channel_config.channel_id:
        await callback.message.edit_text("❌ Канал не підключено")
        return

    current = user.channel_config.channel_user_title or ""
    await state.set_state(ChannelConversationSG.editing_title)
    await callback.message.edit_text(
        f"📝 Зміна назви каналу\n\n"
        f"Поточна назва: {CHANNEL_NAME_PREFIX}{current}\n\n"
        f"Введіть нову назву (без префіксу):"
    )


@router.callback_query(F.data == "channel_edit_description")
async def channel_edit_description(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.channel_config or not user.channel_config.channel_id:
        await callback.message.edit_text("❌ Канал не підключено")
        return

    current = user.channel_config.channel_user_description or "(не встановлено)"
    await state.set_state(ChannelConversationSG.editing_description)
    await callback.message.edit_text(
        f"📝 Зміна опису каналу\n\nПоточний опис: {current}\n\nВведіть новий опис:"
    )


@router.callback_query(F.data == "channel_add_desc")
async def channel_add_desc(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ChannelConversationSG.waiting_for_description)
    await callback.message.edit_text(
        "📝 Введіть опис каналу:\n\n"
        'Приклад: "Графіки відключень для Київ, черга 3.1"'
    )


@router.callback_query(F.data == "channel_skip_desc")
async def channel_skip_desc(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    await state.clear()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.channel_config:
        return

    await _apply_branding(callback.bot, user)

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⤵ Меню", callback_data="back_to_main")],
            [InlineKeyboardButton(text="📢 Новини бота", url="https://t.me/Voltyk_news")],
        ]
    )
    title = user.channel_config.channel_title or ""
    await callback.message.edit_text(
        f"✅ Канал успішно налаштовано!\n\n"
        f"📺 Назва каналу: {title}\n\n"
        "⚠️ Увага!\nНе змінюйте назву, опис або фото каналу.\n\n"
        "Якщо ці дані буде змінено — бот припинить роботу,\n"
        "і канал потрібно буде налаштувати заново.\n\n"
        "⤵ Меню — перейти в головне меню\n"
        "📢 Новини бота — канал з оновленнями",
        reply_markup=kb,
    )


async def _apply_branding(bot, user) -> None:
    cc = user.channel_config
    if not cc or not cc.channel_id:
        return

    full_title = f"{CHANNEL_NAME_PREFIX}{cc.channel_user_title or ''}"
    try:
        await bot.set_chat_title(cc.channel_id, full_title[:128])
        cc.channel_title = full_title[:128]
    except Exception as e:
        logger.warning("Failed to set channel title: %s", e)

    if cc.channel_user_description:
        from bot.utils.helpers import CHANNEL_DESCRIPTION_BASE

        desc = f"{CHANNEL_DESCRIPTION_BASE}\n\n{cc.channel_user_description}"
        try:
            await bot.set_chat_description(cc.channel_id, desc[:255])
            cc.channel_description = desc[:255]
        except Exception as e:
            logger.warning("Failed to set channel description: %s", e)

    from bot.utils.helpers import get_channel_welcome_message

    try:
        await bot.send_message(cc.channel_id, get_channel_welcome_message(user.queue))
    except Exception as e:
        logger.warning("Failed to send welcome message: %s", e)

    from datetime import UTC, datetime

    cc.channel_branding_updated_at = datetime.now(UTC)
