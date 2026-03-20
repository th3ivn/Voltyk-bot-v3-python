from __future__ import annotations

from aiogram import Router
from aiogram.types import ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import (
    delete_pending_channel,
    get_user_by_channel_id,
    get_user_by_telegram_id,
    save_pending_channel,
)
from bot.keyboards.inline import get_understood_keyboard
from bot.utils.logger import get_logger

logger = get_logger(__name__)
router = Router(name="chat_member")


@router.my_chat_member()
async def handle_chat_member(event: ChatMemberUpdated, session: AsyncSession) -> None:
    if event.chat.type not in ("channel",):
        return

    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status
    chat = event.chat
    from_user = event.from_user

    if new_status in ("administrator", "creator") and old_status in ("left", "kicked", "member"):
        channel_id = str(chat.id)
        channel_title = chat.title or "Невідомий канал"
        channel_username = chat.username

        existing_owner = await get_user_by_channel_id(session, channel_id)
        if existing_owner and existing_owner.telegram_id != str(from_user.id):
            try:
                await event.bot.send_message(
                    from_user.id,
                    f'⚠️ Канал вже підключений\n\n'
                    f'Канал "{channel_title}" вже підключено до іншого користувача.\n\n'
                    "Кожен канал може бути підключений тільки до одного облікового запису.\n\n"
                    "Якщо це ваш канал — зверніться до підтримки.",
                )
            except Exception as e:
                logger.warning("Could not notify user %s about already connected channel: %s", from_user.id, e)
            return

        user = await get_user_by_telegram_id(session, from_user.id)

        await save_pending_channel(
            session,
            channel_id,
            from_user.id,
            channel_username=channel_username,
            channel_title=channel_title,
        )

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Так, підключити", callback_data=f"connect_channel_{channel_id}")],
                [InlineKeyboardButton(text="❌ Ні", callback_data="cancel_channel_connect")],
            ]
        )

        if user and user.channel_config and user.channel_config.channel_id:
            current_title = user.channel_config.channel_title or "поточний"
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Так, замінити", callback_data=f"replace_channel_{channel_id}")],
                    [InlineKeyboardButton(text="❌ Залишити поточний", callback_data="keep_current_channel")],
                ]
            )
            try:
                await event.bot.send_message(
                    from_user.id,
                    f'✅ Ви додали мене в канал "{channel_title}"!\n\n'
                    f'⚠️ У вас вже підключений канал "{current_title}".\n'
                    "Замінити на новий?",
                    reply_markup=kb,
                )
            except Exception as e:
                logger.warning("Could not send channel replace prompt to user %s: %s", from_user.id, e)
        else:
            try:
                await event.bot.send_message(
                    from_user.id,
                    f'✅ Канал знайдено: "{channel_title}"\n\nВикористовувати його для сповіщень?',
                    reply_markup=kb,
                )
            except Exception as e:
                logger.warning("Could not send channel connect prompt to user %s: %s", from_user.id, e)

    elif new_status in ("left", "kicked") and old_status in ("administrator", "creator"):
        channel_id = str(chat.id)
        channel_title = chat.title or "Невідомий канал"

        await delete_pending_channel(session, channel_id)

        user = await get_user_by_channel_id(session, channel_id)
        if user:
            user.channel_config.channel_id = None
            user.channel_config.channel_title = None
            user.channel_config.channel_status = "disconnected"
            try:
                await event.bot.send_message(
                    int(user.telegram_id),
                    f'⚠️ Мене видалили з каналу "{channel_title}".\n\n'
                    "Сповіщення в цей канал більше не надсилатимуться.",
                    reply_markup=get_understood_keyboard(),
                )
            except Exception as e:
                logger.warning("Could not notify user %s about channel removal: %s", user.telegram_id, e)
