from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import (
    delete_pending_channel,
    delete_pending_channel_by_telegram_id,
    get_pending_channel_by_telegram_id,
    get_user_by_telegram_id,
)
from bot.states.fsm import ChannelConversationSG
from bot.utils.helpers import CHANNEL_NAME_PREFIX

logger = logging.getLogger(__name__)
router = Router(name="channel_connect")


@router.callback_query(F.data == "channel_connect")
async def channel_connect(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    pending = await get_pending_channel_by_telegram_id(session, callback.from_user.id)
    if pending:
        await callback.message.edit_text(
            f'📺 Знайдено канал!\n\n"{pending.channel_title}"\n\nПідключити цей канал?',
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✓ Так, підключити", callback_data=f"channel_confirm_{pending.channel_id}")],
                    [InlineKeyboardButton(text="✕ Ні", callback_data="settings_channel")],
                ]
            ),
        )
        return

    bot_me = await callback.bot.get_me()
    await callback.message.edit_text(
        "📺 Підключення каналу\n\n"
        "Щоб бот міг публікувати графіки у ваш канал:\n\n"
        "1️⃣ Відкрийте ваш канал у Telegram\n"
        "2️⃣ Перейдіть у Налаштування каналу → Адміністратори\n"
        "3️⃣ Натисніть \"Додати адміністратора\"\n"
        f"4️⃣ Знайдіть бота: @{bot_me.username}\n"
        "5️⃣ Надайте права на публікацію повідомлень\n\n"
        "Після цього натисніть кнопку \"✅ Перевірити\" нижче.\n\n"
        f"💡 Порада: скопіюйте @{bot_me.username} і вставте у пошук",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Перевірити", callback_data="channel_connect")],
                [InlineKeyboardButton(text="← Назад", callback_data="settings_channel")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("channel_confirm_"))
async def channel_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    channel_id = callback.data.replace("channel_confirm_", "")
    await callback.answer()

    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return

    pending = await get_pending_channel_by_telegram_id(session, callback.from_user.id)
    if not pending or pending.channel_id != channel_id:
        await callback.message.edit_text("❌ Канал не знайдено або час очікування вийшов.")
        return

    user.channel_config.channel_id = channel_id
    user.channel_config.channel_title = pending.channel_title
    user.channel_config.channel_status = "active"
    await delete_pending_channel(session, channel_id)

    await state.set_state(ChannelConversationSG.waiting_for_title)
    await callback.message.edit_text(
        "✅ Канал підключено!\n\n"
        "Як назвати канал?\n\n"
        f'Назва буде додана після "{CHANNEL_NAME_PREFIX}"\n\n'
        f"Приклад: Київ Черга 3.1\n"
        f"Результат: {CHANNEL_NAME_PREFIX}Київ Черга 3.1",
    )


@router.callback_query(F.data.startswith("connect_channel_"))
async def connect_channel(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    channel_id = callback.data.replace("connect_channel_", "")
    await callback.answer()

    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return

    pending = await get_pending_channel_by_telegram_id(session, callback.from_user.id)
    if not pending:
        await callback.message.edit_text("❌ Канал не знайдено або час очікування вийшов.")
        return

    user.channel_config.channel_id = channel_id
    user.channel_config.channel_title = pending.channel_title
    user.channel_config.channel_status = "active"
    await delete_pending_channel(session, channel_id)

    await state.set_state(ChannelConversationSG.waiting_for_title)
    await callback.message.edit_text(
        "📝 Введіть назву для каналу\n\n"
        f'Назва буде додана після "{CHANNEL_NAME_PREFIX}"\n\n'
        f"Приклад: Київ Черга 3.1\n"
        f"Результат: {CHANNEL_NAME_PREFIX}Київ Черга 3.1",
    )


@router.callback_query(F.data.startswith("replace_channel_"))
async def replace_channel(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    channel_id = callback.data.replace("replace_channel_", "")
    await callback.answer()

    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return

    pending = await get_pending_channel_by_telegram_id(session, callback.from_user.id)
    if not pending:
        await callback.message.edit_text("❌ Канал не знайдено або час очікування вийшов.")
        return

    user.channel_config.channel_id = channel_id
    user.channel_config.channel_title = pending.channel_title
    user.channel_config.channel_status = "active"
    await delete_pending_channel(session, channel_id)

    await state.set_state(ChannelConversationSG.waiting_for_title)
    await callback.message.edit_text(
        f'✅ Канал замінено на "{pending.channel_title}"!\n\n'
        "📝 Введіть назву для каналу\n\n"
        f'Назва буде додана після "{CHANNEL_NAME_PREFIX}"\n\n'
        f"Приклад: Київ Черга 3.1\n"
        f"Результат: {CHANNEL_NAME_PREFIX}Київ Черга 3.1",
    )


@router.callback_query(F.data == "keep_current_channel")
async def keep_current(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await delete_pending_channel_by_telegram_id(session, callback.from_user.id)
    await callback.message.edit_text("👌 Добре, залишаємо поточний канал.")


@router.callback_query(F.data == "cancel_channel_connect")
async def cancel_connect(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await delete_pending_channel_by_telegram_id(session, callback.from_user.id)
    await callback.message.edit_text(
        "👌 Добре, канал не підключено. Ви можете підключити його пізніше в налаштуваннях."
    )
