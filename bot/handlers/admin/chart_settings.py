from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.queries import get_setting, set_setting
from bot.keyboards.inline import get_chart_render_mode_keyboard
from bot.services.api import set_chart_render_mode

router = Router(name="admin_chart_settings")

SETTING_KEY = "chart_render_mode"


def _admin_only(user_id: int) -> bool:
    return settings.is_admin(user_id)


@router.callback_query(F.data == "admin_chart_render")
async def admin_chart_render(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _admin_only(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    current_mode = await get_setting(session, SETTING_KEY) or "on_change"
    await callback.message.edit_text(
        "🖼 <b>Режим рендерингу графіків</b>\n\n"
        "• <b>При зміні</b> — рендер один раз коли змінився розклад; "
        "всі користувачі отримують кешоване фото (швидко)\n\n"
        "• <b>При запиті</b> — рендер при кожному натисканні кнопки «Графік»; "
        "завжди свіже фото, але більше навантаження на CPU",
        reply_markup=get_chart_render_mode_keyboard(current_mode),
    )


@router.callback_query(F.data.startswith("chart_render_mode_"))
async def set_chart_render(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _admin_only(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    mode = callback.data.removeprefix("chart_render_mode_")
    if mode not in ("on_change", "on_demand"):
        await callback.answer("❌ Невідомий режим")
        return
    await set_setting(session, SETTING_KEY, mode)
    await session.commit()
    set_chart_render_mode(on_demand=(mode == "on_demand"))
    label = "При запиті" if mode == "on_demand" else "При зміні розкладу"
    await callback.answer(f"✅ Збережено: {label}")
    await callback.message.edit_reply_markup(reply_markup=get_chart_render_mode_keyboard(mode))
