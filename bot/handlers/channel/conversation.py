from __future__ import annotations

import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_user_by_telegram_id
from bot.states.fsm import ChannelConversationSG
from bot.utils.helpers import CHANNEL_NAME_PREFIX

logger = logging.getLogger(__name__)
router = Router(name="channel_conversation")


@router.message(ChannelConversationSG.waiting_for_title)
async def handle_title(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.text:
        await message.reply("❌ Назва не може бути пустою. Спробуйте ще раз:")
        return
    title = message.text.strip()
    if not title:
        await message.reply("❌ Назва не може бути пустою. Спробуйте ще раз:")
        return
    if len(title) > 128:
        await message.reply(f"❌ Назва занадто довга (максимум 128 символів). Зараз: {len(title)}")
        return

    user = await get_user_by_telegram_id(session, message.from_user.id)
    if user and user.channel_config:
        user.channel_config.channel_user_title = title

    await state.set_state(ChannelConversationSG.waiting_for_description_choice)
    await message.answer(
        f"📝 Хочете додати додатковий опис каналу?\n\n"
        f'Приклад: "Графіки відключень для {title}"',
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✍️ Додати опис", callback_data="channel_add_desc")],
                [InlineKeyboardButton(text="⏭️ Пропустити", callback_data="channel_skip_desc")],
            ]
        ),
    )


@router.message(ChannelConversationSG.waiting_for_description)
async def handle_description(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.text:
        await message.reply("❌ Опис не може бути пустим. Спробуйте ще раз:")
        return
    desc = message.text.strip()
    if not desc:
        await message.reply("❌ Опис не може бути пустим. Спробуйте ще раз:")
        return
    if len(desc) > 255:
        await message.reply(f"❌ Опис занадто довгий (максимум 255 символів). Зараз: {len(desc)}")
        return

    user = await get_user_by_telegram_id(session, message.from_user.id)
    if user and user.channel_config:
        user.channel_config.channel_user_description = desc

    await state.clear()

    from bot.handlers.channel.branding import _apply_branding

    await _apply_branding(message.bot, user)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⤵ Меню", callback_data="back_to_main")],
            [InlineKeyboardButton(text="📢 Новини бота", url="https://t.me/Voltyk_news")],
        ]
    )
    title = user.channel_config.channel_title or ""
    await message.answer(
        f"✅ Канал успішно налаштовано!\n\n"
        f"📺 Назва каналу: {title}\n\n"
        "⚠️ Увага!\nНе змінюйте назву, опис або фото каналу.\n\n"
        "Якщо ці дані буде змінено — бот припинить роботу,\n"
        "і канал потрібно буде налаштувати заново.",
        reply_markup=kb,
    )


@router.message(ChannelConversationSG.editing_title)
async def handle_edit_title(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.text or not message.text.strip():
        await message.reply("❌ Назва не може бути пустою.")
        return
    title = message.text.strip()
    if len(title) > 128:
        await message.reply("❌ Назва занадто довга (максимум 128 символів).")
        return

    user = await get_user_by_telegram_id(session, message.from_user.id)
    if user and user.channel_config:
        user.channel_config.channel_user_title = title
        full_title = f"{CHANNEL_NAME_PREFIX}{title}"
        try:
            await message.bot.set_chat_title(user.channel_config.channel_id, full_title[:128])
            user.channel_config.channel_title = full_title[:128]
        except Exception as e:
            logger.warning("Failed to update title: %s", e)

    await state.clear()
    await message.answer("✅ Назву каналу змінено!")


@router.message(ChannelConversationSG.editing_description)
async def handle_edit_description(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.text or not message.text.strip():
        await message.reply("❌ Опис не може бути пустим.")
        return
    desc = message.text.strip()
    if len(desc) > 255:
        await message.reply("❌ Опис занадто довгий (максимум 255 символів).")
        return

    user = await get_user_by_telegram_id(session, message.from_user.id)
    if user and user.channel_config:
        user.channel_config.channel_user_description = desc
        from bot.utils.helpers import CHANNEL_DESCRIPTION_BASE

        full_desc = f"{CHANNEL_DESCRIPTION_BASE}\n\n{desc}"
        try:
            await message.bot.set_chat_description(user.channel_config.channel_id, full_desc[:255])
            user.channel_config.channel_description = full_desc[:255]
        except Exception as e:
            logger.warning("Failed to update description: %s", e)

    await state.clear()
    await message.answer("✅ Опис каналу змінено!")


@router.message(ChannelConversationSG.waiting_for_schedule_caption)
async def handle_schedule_caption(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.text:
        return
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if user and user.channel_config:
        user.channel_config.schedule_caption = message.text.strip()
    await state.clear()
    await message.answer("✅ Шаблон підпису оновлено!")


@router.message(ChannelConversationSG.waiting_for_period_format)
async def handle_period_format(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.text:
        return
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if user and user.channel_config:
        user.channel_config.period_format = message.text.strip()
    await state.clear()
    await message.answer("✅ Формат періодів оновлено!")


@router.message(ChannelConversationSG.waiting_for_power_off_text)
async def handle_power_off_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.text:
        return
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if user and user.channel_config:
        user.channel_config.power_off_text = message.text.strip()
    await state.clear()
    await message.answer("✅ Текст відключення оновлено!")


@router.message(ChannelConversationSG.waiting_for_power_on_text)
async def handle_power_on_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.text:
        return
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if user and user.channel_config:
        user.channel_config.power_on_text = message.text.strip()
    await state.clear()
    await message.answer("✅ Текст включення оновлено!")


@router.message(ChannelConversationSG.waiting_for_custom_test)
async def handle_custom_test(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.text:
        return
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if user and user.channel_config and user.channel_config.channel_id:
        try:
            await message.bot.send_message(
                user.channel_config.channel_id, message.text, parse_mode="HTML"
            )
            await message.answer("✅ Повідомлення опубліковано в канал!")
        except Exception as e:
            await message.answer(f"❌ Помилка публікації: {e}")
    await state.clear()
