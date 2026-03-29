from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.queries import get_setting, set_setting
from bot.keyboards.inline import get_chart_preview_keyboard, get_chart_render_mode_keyboard
from bot.services.api import set_chart_render_mode
from bot.services.chart_generator import KYIV_TZ, generate_schedule_chart

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


# ── Chart preview ──────────────────────────────────────────────────────────────

_SCENARIO_LABELS = {
    "two_outages":   "2 відключення на день",
    "three_outages": "3 відключення на день",
    "allday":        "Цілий день без світла",
    "halfhour":      "30-хвилинні стани",
}


def _make_preview_data(scenario: str, today_start: datetime, tomorrow_start: datetime) -> dict:
    """Build a mock schedule_data dict for the given preview scenario."""

    def _ev(day_start: datetime, h_from: float, h_to: float, possible: bool = False) -> dict:
        """Single event: h_from/h_to are hours (may be .5 for 30-min boundary)."""
        return {
            "start": (day_start + timedelta(hours=h_from)).isoformat(),
            "end":   (day_start + timedelta(hours=h_to)).isoformat(),
            "isPossible": possible,
        }

    events: list[dict] = []

    if scenario == "two_outages":
        # Today: 06:00–08:00 definite, 17:00–21:00 definite
        # Tomorrow: same pattern
        for day in (today_start, tomorrow_start):
            events += [
                _ev(day, 6, 8),
                _ev(day, 17, 21),
            ]

    elif scenario == "three_outages":
        # Today: 04:00–07:00, 12:00–15:00, 20:00–23:00
        # Tomorrow: same
        for day in (today_start, tomorrow_start):
            events += [
                _ev(day, 4, 7),
                _ev(day, 12, 15),
                _ev(day, 20, 23),
            ]

    elif scenario == "allday":
        # Today: entire day off; tomorrow: entire day maybe
        events += [
            _ev(today_start, 0, 24, possible=False),
            _ev(tomorrow_start, 0, 24, possible=True),
        ]

    elif scenario == "halfhour":
        # Showcase all split-cell states:
        # 00–01 on, 01–02 nfirst (off first half), 02–03 nsecond,
        # 03–04 mfirst, 04–05 msecond, 05–06 no, 06–07 maybe,
        # 07–24 mix: alternating no/on blocks
        for day in (today_start, tomorrow_start):
            events += [
                _ev(day, 1, 1.5),          # nfirst  → slot 1 first half off
                _ev(day, 2.5, 3),          # nsecond → slot 2 second half off
                _ev(day, 3, 3.5, True),    # mfirst  → slot 3 first half maybe
                _ev(day, 4.5, 5, True),    # msecond → slot 4 second half maybe
                _ev(day, 5, 6),            # no      → slot 5 full off
                _ev(day, 6, 7, True),      # maybe   → slot 6 full maybe
                _ev(day, 8, 10),           # no block
                _ev(day, 12, 14),          # no block
                _ev(day, 16, 18, True),    # maybe block
                _ev(day, 20, 22),          # no block
            ]

    ts = today_start.strftime("%d.%m.%Y %H:%M")
    return {"events": events, "dtek_updated_at": ts}


@router.callback_query(F.data == "chart_preview_menu")
async def chart_preview_menu(callback: CallbackQuery) -> None:
    if not _admin_only(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    await callback.message.edit_text(
        "👁 <b>Перегляд графіка</b>\n\n"
        "Оберіть сценарій для попереднього перегляду:",
        reply_markup=get_chart_preview_keyboard(),
    )


@router.callback_query(F.data.startswith("chart_preview:"))
async def chart_preview_render(callback: CallbackQuery) -> None:
    if not _admin_only(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    scenario = callback.data.removeprefix("chart_preview:")
    if scenario not in _SCENARIO_LABELS:
        await callback.answer("❌ Невідомий сценарій")
        return
    await callback.answer("⏳ Генерую графік…")

    now = datetime.now(KYIV_TZ)
    today_start    = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)

    mock_data = _make_preview_data(scenario, today_start, tomorrow_start)
    png_bytes = await generate_schedule_chart("Київ", "1.1", mock_data)

    label = _SCENARIO_LABELS[scenario]
    await callback.message.answer_photo(
        BufferedInputFile(png_bytes, filename="preview.png"),
        caption=f"👁 <b>Перегляд:</b> {label}",
    )
