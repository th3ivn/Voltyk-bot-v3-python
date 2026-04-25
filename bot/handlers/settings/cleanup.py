from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.queries import get_user_by_telegram_id
from bot.keyboards.inline import get_cleanup_keyboard
from bot.utils.telegram import safe_edit_text

router = Router(name="settings_cleanup")


def _cleanup_text(*, commands_enabled: bool, bot_messages_enabled: bool) -> str:
    cmd_status = "увімкнено ✅" if commands_enabled else "вимкнено"
    msg_status = "увімкнено ✅" if bot_messages_enabled else "вимкнено"
    ttl = settings.AUTO_DELETE_DELAY_MINUTES
    return (
        "🗑 <b>Автоматичне очищення повідомлень</b>\n\n"
        f"⌨️ Команди користувача: {cmd_status}\n"
        f"💬 Відповіді бота: {msg_status}\n\n"
        f"⏱ Якщо опції увімкнені, бот автоматично видаляє нові повідомлення через {ttl} хв.\n"
        "Це допомагає не засмічувати чат службовими повідомленнями."
    )


@router.callback_query(F.data == "settings_cleanup")
async def settings_cleanup(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.notification_settings:
        return
    ns = user.notification_settings
    await safe_edit_text(callback.message,
        _cleanup_text(
            commands_enabled=ns.auto_delete_commands,
            bot_messages_enabled=ns.auto_delete_bot_messages,
        ),
        reply_markup=get_cleanup_keyboard(
            auto_delete_commands=ns.auto_delete_commands,
            auto_delete_bot_messages=ns.auto_delete_bot_messages,
        ),
    )


@router.callback_query(F.data == "cleanup_toggle_commands")
async def cleanup_toggle_commands(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.notification_settings:
        await callback.answer()
        return
    ns = user.notification_settings
    ns.auto_delete_commands = not ns.auto_delete_commands
    text = (
        f"✅ Команди будуть видалятись через {settings.AUTO_DELETE_DELAY_MINUTES} хв"
        if ns.auto_delete_commands
        else "❌ Видалення команд вимкнено"
    )
    await callback.answer(text)
    await safe_edit_text(callback.message,
        _cleanup_text(
            commands_enabled=ns.auto_delete_commands,
            bot_messages_enabled=ns.auto_delete_bot_messages,
        ),
        reply_markup=get_cleanup_keyboard(
            auto_delete_commands=ns.auto_delete_commands,
            auto_delete_bot_messages=ns.auto_delete_bot_messages,
        ),
    )


@router.callback_query(F.data == "cleanup_toggle_messages")
async def cleanup_toggle_messages(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.notification_settings:
        await callback.answer()
        return
    ns = user.notification_settings
    ns.auto_delete_bot_messages = not ns.auto_delete_bot_messages
    text = (
        f"✅ Відповіді будуть видалятись через {settings.AUTO_DELETE_DELAY_MINUTES} хв"
        if ns.auto_delete_bot_messages
        else "❌ Видалення відповідей вимкнено"
    )
    await callback.answer(text)
    await safe_edit_text(callback.message,
        _cleanup_text(
            commands_enabled=ns.auto_delete_commands,
            bot_messages_enabled=ns.auto_delete_bot_messages,
        ),
        reply_markup=get_cleanup_keyboard(
            auto_delete_commands=ns.auto_delete_commands,
            auto_delete_bot_messages=ns.auto_delete_bot_messages,
        ),
    )
