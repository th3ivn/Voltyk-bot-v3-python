from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.queries import add_pause_log, get_pause_logs, get_setting, set_setting
from bot.keyboards.inline import (
    get_debounce_keyboard,
    get_pause_menu_keyboard,
    get_pause_message_keyboard,
    get_pause_type_keyboard,
)
from bot.states.fsm import ChannelConversationSG

router = Router(name="admin_pause")


@router.callback_query(F.data == "admin_pause")
async def admin_pause(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    is_paused = (await get_setting(session, "bot_paused") or "false") == "true"
    await callback.message.edit_text(
        "⏸️ Режим паузи",
        reply_markup=get_pause_menu_keyboard(is_paused=is_paused),
    )


@router.callback_query(F.data == "pause_status")
async def pause_status(callback: CallbackQuery, session: AsyncSession) -> None:
    is_paused = (await get_setting(session, "bot_paused") or "false") == "true"
    await callback.answer(f"{'🔴 На паузі' if is_paused else '🟢 Активний'}")


@router.callback_query(F.data == "pause_toggle")
async def pause_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    current = (await get_setting(session, "bot_paused") or "false") == "true"
    new_val = "false" if current else "true"
    await set_setting(session, "bot_paused", new_val)
    is_paused = new_val == "true"

    event_type = "pause_on" if is_paused else "pause_off"
    await add_pause_log(session, callback.from_user.id, event_type)

    await callback.answer(f"{'🔴 Пауза увімкнена' if is_paused else '🟢 Пауза вимкнена'}")
    await callback.message.edit_text(
        "⏸️ Режим паузи",
        reply_markup=get_pause_menu_keyboard(is_paused=is_paused),
    )


@router.callback_query(F.data == "pause_message_settings")
async def pause_message_settings(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    show_support = (await get_setting(session, "pause_show_support") or "false") == "true"
    current_message = await get_setting(session, "pause_message") or ""
    await callback.message.edit_text(
        "📋 Налаштування повідомлення паузи",
        reply_markup=get_pause_message_keyboard(show_support_button=show_support, current_message=current_message),
    )


@router.callback_query(F.data.startswith("pause_template_"))
async def pause_template(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    templates = {
        "1": "🔧 Бот тимчасово недоступний. Спробуйте пізніше.",
        "2": "⏸️ Бот на паузі. Скоро повернемось",
        "3": "🔧 Бот тимчасово оновлюється. Спробуйте пізніше.",
        "4": "⏸️ Бот на паузі. Скоро повернемось.",
        "5": "🚧 Технічні роботи. Дякуємо за розуміння.",
    }
    idx = callback.data.replace("pause_template_", "")
    msg = templates.get(idx, templates["1"])
    await set_setting(session, "pause_message", msg)
    await callback.answer(f"✅ Повідомлення: {msg[:50]}")
    show_support = (await get_setting(session, "pause_show_support") or "false") == "true"
    await callback.message.edit_reply_markup(
        reply_markup=get_pause_message_keyboard(show_support_button=show_support, current_message=msg)
    )


@router.callback_query(F.data == "pause_custom_message")
async def pause_custom_message(callback: CallbackQuery, state: FSMContext) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    await state.set_state(ChannelConversationSG.waiting_for_pause_message)
    await callback.message.edit_text("✏️ Введіть текст повідомлення паузи:")


@router.message(ChannelConversationSG.waiting_for_pause_message)
async def pause_custom_message_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not settings.is_admin(message.from_user.id):
        return
    if not message.text:
        await message.reply("❌ Введіть текст повідомлення")
        return
    await set_setting(session, "pause_message", message.text.strip())
    await state.clear()
    show_support = (await get_setting(session, "pause_show_support") or "false") == "true"
    await message.answer(
        f"✅ Повідомлення паузи збережено: {message.text.strip()[:80]}",
        reply_markup=get_pause_message_keyboard(show_support_button=show_support, current_message=message.text.strip()),
    )


@router.callback_query(F.data == "pause_toggle_support")
async def pause_toggle_support(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    current = (await get_setting(session, "pause_show_support") or "false") == "true"
    new_val = "false" if current else "true"
    await set_setting(session, "pause_show_support", new_val)
    await callback.answer("✅ Збережено")
    current_message = await get_setting(session, "pause_message") or ""
    await callback.message.edit_reply_markup(
        reply_markup=get_pause_message_keyboard(show_support_button=new_val == "true", current_message=current_message)
    )


@router.callback_query(F.data == "pause_type_select")
async def pause_type_select(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    current = await get_setting(session, "pause_type") or "update"
    await callback.message.edit_text(
        "🏷 Тип паузи",
        reply_markup=get_pause_type_keyboard(current_type=current),
    )


@router.callback_query(F.data.startswith("pause_type_"))
async def pause_type_set(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    pause_type = callback.data.replace("pause_type_", "")
    if pause_type == "select":
        return
    await set_setting(session, "pause_type", pause_type)
    await callback.answer(f"✅ Тип: {pause_type}")
    await callback.message.edit_reply_markup(
        reply_markup=get_pause_type_keyboard(current_type=pause_type)
    )


@router.callback_query(F.data == "pause_log")
async def pause_log(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    logs = await get_pause_logs(session, limit=10)
    if not logs:
        await callback.message.edit_text("📜 Лог паузи порожній")
        return
    lines = ["📜 Лог паузи\n"]
    for log in logs:
        date = log.created_at.strftime("%d.%m %H:%M") if log.created_at else "-"
        lines.append(f"{date} | {log.event_type} | {log.pause_type or '-'}")
    await callback.message.edit_text("\n".join(lines))


@router.callback_query(F.data == "admin_debounce")
async def admin_debounce(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_owner(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено. Тільки головний адмін може змінювати ці налаштування")
        return
    await callback.answer()
    current = int(await get_setting(session, "power_debounce_minutes") or "5")
    await callback.message.edit_text(
        f"⏸ Debounce\n\nПоточне значення: {current} хв",
        reply_markup=get_debounce_keyboard(current_value=current),
    )


@router.callback_query(F.data.startswith("debounce_set_"))
async def debounce_set(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_owner(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено. Тільки головний адмін може змінювати ці налаштування")
        return
    value = int(callback.data.replace("debounce_set_", ""))
    await set_setting(session, "power_debounce_minutes", str(value))
    label = "Вимкнено" if value == 0 else f"{value} хв"
    await callback.answer(f"✅ Debounce: {label}")
    await callback.message.edit_reply_markup(
        reply_markup=get_debounce_keyboard(current_value=value)
    )
