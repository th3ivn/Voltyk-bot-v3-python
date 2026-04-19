from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_user_by_telegram_id
from bot.keyboards.inline import get_cleanup_keyboard
from bot.utils.telegram import safe_edit_text

router = Router(name="settings_cleanup")


@router.callback_query(F.data == "settings_cleanup")
async def settings_cleanup(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.notification_settings:
        return
    ns = user.notification_settings
    cmd_status = "увімкнено ✅" if ns.auto_delete_commands else "вимкнено"
    msg_status = "увімкнено ✅" if ns.auto_delete_bot_messages else "вимкнено"
    await safe_edit_text(callback.message,
        f"🗑 Автоматичне очищення\n\n⌨️ Команди: {cmd_status}\n💬 Відповіді: {msg_status}",
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
    text = "✅ Команди будуть видалятись" if ns.auto_delete_commands else "❌ Видалення команд вимкнено"
    await callback.answer(text)
    cmd_status = "увімкнено ✅" if ns.auto_delete_commands else "вимкнено"
    msg_status = "увімкнено ✅" if ns.auto_delete_bot_messages else "вимкнено"
    await safe_edit_text(callback.message,
        f"🗑 Автоматичне очищення\n\n⌨️ Команди: {cmd_status}\n💬 Відповіді: {msg_status}",
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
        "✅ Відповіді будуть видалятись через 120 хв"
        if ns.auto_delete_bot_messages
        else "❌ Видалення відповідей вимкнено"
    )
    await callback.answer(text)
    cmd_status = "увімкнено ✅" if ns.auto_delete_commands else "вимкнено"
    msg_status = "увімкнено ✅" if ns.auto_delete_bot_messages else "вимкнено"
    await safe_edit_text(callback.message,
        f"🗑 Автоматичне очищення\n\n⌨️ Команди: {cmd_status}\n💬 Відповіді: {msg_status}",
        reply_markup=get_cleanup_keyboard(
            auto_delete_commands=ns.auto_delete_commands,
            auto_delete_bot_messages=ns.auto_delete_bot_messages,
        ),
    )
