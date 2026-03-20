from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_user_by_telegram_id
from bot.services.branding import apply_channel_branding
from bot.states.fsm import ChannelConversationSG
from bot.utils.branding import MAX_USER_DESC_LEN, MAX_USER_TITLE_LEN
from bot.utils.logger import get_logger

logger = get_logger(__name__)
router = Router(name="channel_conversation")


@router.message(ChannelConversationSG.waiting_for_title)
async def handle_title(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.text or not message.text.strip():
        await message.reply("❌ Назва не може бути пустою. Спробуйте ще раз:")
        return
    title = message.text.strip()
    if len(title) > MAX_USER_TITLE_LEN:
        await message.reply(
            f"❌ Назва занадто довга (максимум {MAX_USER_TITLE_LEN} символів без префіксу). "
            f"Зараз: {len(title)}"
        )
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
    if not message.text or not message.text.strip():
        await message.reply("❌ Опис не може бути пустим. Спробуйте ще раз:")
        return
    desc = message.text.strip()
    if len(desc) > MAX_USER_DESC_LEN:
        await message.reply(
            f"❌ Опис занадто довгий (максимум {MAX_USER_DESC_LEN} символів). "
            f"Зараз: {len(desc)}"
        )
        return

    user = await get_user_by_telegram_id(session, message.from_user.id)
    if user and user.channel_config:
        user.channel_config.channel_user_description = desc

    await state.clear()
    await apply_channel_branding(
        message.bot,
        user.channel_config,
        send_welcome=True,
        queue=user.queue,
        region=user.region,
        has_ip=bool(user.router_ip),
    )

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
    if len(title) > MAX_USER_TITLE_LEN:
        await message.reply(
            f"❌ Назва занадто довга (максимум {MAX_USER_TITLE_LEN} символів без префіксу)."
        )
        return

    user = await get_user_by_telegram_id(session, message.from_user.id)
    if user and user.channel_config:
        user.channel_config.channel_user_title = title
        await apply_channel_branding(message.bot, user.channel_config)

    await state.clear()
    await message.answer("✅ Назву каналу змінено!")


@router.message(ChannelConversationSG.editing_description)
async def handle_edit_description(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.text or not message.text.strip():
        await message.reply("❌ Опис не може бути пустим.")
        return
    desc = message.text.strip()
    if len(desc) > MAX_USER_DESC_LEN:
        await message.reply(
            f"❌ Опис занадто довгий (максимум {MAX_USER_DESC_LEN} символів)."
        )
        return

    user = await get_user_by_telegram_id(session, message.from_user.id)
    if user and user.channel_config:
        user.channel_config.channel_user_description = desc
        await apply_channel_branding(message.bot, user.channel_config)

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
