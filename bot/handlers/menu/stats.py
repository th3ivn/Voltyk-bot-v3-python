from __future__ import annotations

from datetime import timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings as app_settings
from bot.db.queries import get_power_history_week, get_user_by_telegram_id
from bot.keyboards.inline import get_statistics_keyboard
from bot.utils.telegram import safe_edit_or_resend

router = Router(name="menu_stats")


@router.callback_query(F.data == "menu_stats")
async def menu_stats(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return
    await safe_edit_or_resend(callback.message, "📊 Статистика", reply_markup=get_statistics_keyboard())


@router.callback_query(F.data == "stats_week")
async def stats_week(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return

    history = await get_power_history_week(session, user.id)
    off_events = [h for h in history if h.event_type == "off"]
    total_outages = len(off_events)
    total_seconds = sum(h.duration_seconds or 0 for h in off_events)
    total_hours = total_seconds // 3600
    total_minutes = (total_seconds % 3600) // 60

    if total_outages == 0:
        text = "⚡ Відключення за тиждень\n\nЗа останні 7 днів відключень не зафіксовано."
    else:
        text = (
            f"⚡ Відключення за тиждень\n\n"
            f"📊 Кількість відключень: {total_outages}\n"
            f"⏱ Загальний час без світла: {total_hours}г {total_minutes}хв"
        )
    await safe_edit_or_resend(callback.message, text, reply_markup=get_statistics_keyboard())


@router.callback_query(F.data == "stats_device")
async def stats_device(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return

    if not user.router_ip:
        text = (
            "📡 Статус пристрою\n\n"
            "IP-адресу роутера не налаштовано.\n\n"
            "Щоб відстежувати фактичний стан живлення — вкажіть IP у Налаштуваннях."
        )
    else:
        pt = user.power_tracking
        state = pt.power_state if pt else None
        changed_at = pt.power_changed_at if pt else None

        if state == "on":
            state_text = "🟢 Світло є"
        elif state == "off":
            state_text = "🔴 Світла немає"
        else:
            state_text = "⏳ Статус невідомий"

        since_text = ""
        if changed_at:
            kyiv = app_settings.timezone
            if changed_at.tzinfo is None:
                changed_at = changed_at.replace(tzinfo=timezone.utc)
            since_text = f"\nЗ {changed_at.astimezone(kyiv).strftime('%d.%m %H:%M')}"

        text = (
            f"📡 Статус пристрою\n\n"
            f"🌐 IP: {user.router_ip}\n"
            f"{state_text}{since_text}"
        )

    await safe_edit_or_resend(callback.message, text, reply_markup=get_statistics_keyboard())
