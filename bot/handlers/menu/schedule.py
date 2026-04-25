from __future__ import annotations

import time

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_schedule_check_time, get_setting, get_user_by_telegram_id
from bot.formatter.schedule import format_schedule_message
from bot.keyboards.inline import get_error_keyboard, get_region_keyboard, get_schedule_view_keyboard
from bot.services.api import (
    calculate_schedule_hash,
    fetch_schedule_data,
    fetch_schedule_image,
    normalize_schedule_chart_metadata,
    parse_schedule_for_queue,
)
from bot.states.fsm import WizardSG
from bot.utils.html_to_entities import append_timestamp, to_aiogram_entities
from bot.utils.logger import get_logger
from bot.utils.telegram import MSG_NOT_MODIFIED, safe_delete, safe_edit_text

logger = get_logger(__name__)
router = Router(name="menu_schedule")

# Per-user cooldown: user_id → timestamp of last "Перевірити" press
_user_last_check: dict[int, float] = {}
_DEFAULT_COOLDOWN_S = 30
_LAST_CHECK_CLEANUP_INTERVAL = 300  # clean up stale entries every 5 minutes
_USER_LAST_CHECK_MAX_SIZE = 10_000  # cap to prevent unbounded growth
_last_check_cleanup_at: float = 0.0


def _ensure_update_timestamp(schedule_data: dict, check_unix: int | None) -> tuple[dict, int]:
    """Backward-compatible wrapper for tests/imports.

    The normalization logic is centralized in ``bot.services.api``.
    """
    return normalize_schedule_chart_metadata(schedule_data, check_unix)


async def _send_schedule_photo(callback: CallbackQuery, user, session: AsyncSession, edit_photo: bool = False) -> None:
    """Send schedule as photo with live timestamp entities.

    edit_photo=True → try editMessageMedia first (no flicker), fallback to delete+send.
    edit_photo=False → always delete+send (initial show from menu).
    """
    data = await fetch_schedule_data(user.region)
    if data is None:
        await callback.message.answer(
            "😅 Щось пішло не так. Спробуйте ще раз!", reply_markup=get_error_keyboard()
        )
        return

    schedule_data = parse_schedule_for_queue(data, user.queue)
    html_text = format_schedule_message(user.region, user.queue, schedule_data)
    kb = get_schedule_view_keyboard()

    last_check = await get_schedule_check_time(session, user.region, user.queue)
    schedule_data, safe_unix = normalize_schedule_chart_metadata(schedule_data, last_check)
    plain_text, raw_entities = append_timestamp(html_text, safe_unix)
    entities = to_aiogram_entities(raw_entities)

    image_bytes = await fetch_schedule_image(user.region, user.queue, schedule_data)

    if image_bytes:
        photo = BufferedInputFile(image_bytes, filename="schedule.png")
        if edit_photo:
            # Try editMessageMedia first (no flicker)
            try:
                media = InputMediaPhoto(media=photo, caption=plain_text, caption_entities=entities, parse_mode=None)
                await callback.message.edit_media(media=media, reply_markup=kb)
                return
            except Exception as e:
                if MSG_NOT_MODIFIED in str(e):
                    return
                logger.warning("edit_media failed, falling back to delete+send: %s", e)
        # Fallback: delete + send new
        await safe_delete(callback.message)
        await callback.message.answer_photo(
            photo=photo, caption=plain_text, caption_entities=entities, reply_markup=kb, parse_mode=None
        )
    else:
        if edit_photo:
            # Try edit text
            try:
                await callback.message.edit_text(plain_text, entities=entities, reply_markup=kb, parse_mode=None)
                return
            except Exception as e:
                if MSG_NOT_MODIFIED in str(e):
                    return
                logger.warning("edit_text failed, falling back to delete+send: %s", e)
        await safe_delete(callback.message)
        await callback.message.answer(plain_text, entities=entities, reply_markup=kb, parse_mode=None)


@router.callback_query(F.data == "menu_schedule")
async def menu_schedule(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await safe_edit_text(callback.message, "❌ Спочатку запустіть бота, натиснувши /start")
        return
    await _send_schedule_photo(callback, user, session, edit_photo=True)


@router.callback_query(F.data == "schedule_check")
async def schedule_check(callback: CallbackQuery, session: AsyncSession) -> None:
    global _last_check_cleanup_at
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.answer("❌ Користувача не знайдено")
        return

    # --- Cooldown check ---
    try:
        cooldown_s = int(await get_setting(session, "refresh_cooldown") or _DEFAULT_COOLDOWN_S)
    except (ValueError, TypeError):
        cooldown_s = _DEFAULT_COOLDOWN_S
    now = time.monotonic()

    # Periodically evict entries older than cooldown_s to prevent unbounded growth
    if now - _last_check_cleanup_at > _LAST_CHECK_CLEANUP_INTERVAL:
        cutoff = now - cooldown_s
        stale = [uid for uid, t in _user_last_check.items() if t <= cutoff]
        for uid in stale:
            del _user_last_check[uid]
        _last_check_cleanup_at = now

    last = _user_last_check.get(callback.from_user.id, 0.0)
    elapsed = now - last
    if elapsed < cooldown_s:
        remaining = int(cooldown_s - elapsed) + 1
        await callback.answer(f"⏳ Зачекай ще {remaining} сек", show_alert=False)
        return

    # Mark cooldown BEFORE first await so concurrent taps from the same user
    # cannot both slip through the check above (asyncio cooperative scheduling
    # means nothing preempts us between here and the next await point).
    # On API failure we clear it so the user can retry immediately.
    # When the dict is at its size cap, batch-evict stale entries first.
    if len(_user_last_check) >= _USER_LAST_CHECK_MAX_SIZE:
        cutoff = now - cooldown_s
        stale_uids = [uid for uid, t in _user_last_check.items() if t <= cutoff]
        for uid in stale_uids:
            del _user_last_check[uid]
        if stale_uids:
            logger.debug(
                "_user_last_check: batch-evicted %d stale entries at cap", len(stale_uids)
            )
        # If still at cap after TTL eviction, evict 10% of the oldest entries
        if len(_user_last_check) >= _USER_LAST_CHECK_MAX_SIZE:
            evict_count = max(1, _USER_LAST_CHECK_MAX_SIZE // 10)
            oldest_uids = sorted(_user_last_check, key=lambda uid: _user_last_check[uid])[:evict_count]
            for uid in oldest_uids:
                del _user_last_check[uid]
            logger.debug(
                "_user_last_check: force-evicted %d oldest entries (10%% of cap)", evict_count
            )
    _user_last_check[callback.from_user.id] = now

    # --- Get old hash from cached data (before force refresh) ---
    old_data = await fetch_schedule_data(user.region)
    old_events = parse_schedule_for_queue(old_data, user.queue).get("events", []) if old_data else []
    old_hash = calculate_schedule_hash(old_events) if old_events else None

    # --- Force refresh ---
    new_data = await fetch_schedule_data(user.region, force_refresh=True)
    if new_data is None:
        # Transient API failure — clear cooldown so the user can retry immediately
        _user_last_check.pop(callback.from_user.id, None)
        await callback.answer("❌ Не вдалось отримати дані", show_alert=False)
        return

    # --- Compare hashes ---
    new_events = parse_schedule_for_queue(new_data, user.queue).get("events", [])
    new_hash = calculate_schedule_hash(new_events) if new_events else None

    if old_hash != new_hash:
        await _send_schedule_photo(callback, user, session, edit_photo=True)
        await callback.answer("💡 Знайдено зміни — оновлено", show_alert=False)
    else:
        await _send_schedule_photo(callback, user, session, edit_photo=True)
        await callback.answer("✅ Без змін — дані актуальні", show_alert=False)


@router.callback_query(F.data == "my_queues")
async def change_queue(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return

    await state.set_state(WizardSG.region)
    await state.update_data(mode="edit_from_schedule")

    if callback.message.photo:
        await safe_delete(callback.message)
        await callback.message.answer("Оберіть свій регіон:", reply_markup=get_region_keyboard(current_region=user.region))
    else:
        await safe_edit_text(callback.message, "Оберіть свій регіон:", reply_markup=get_region_keyboard(current_region=user.region))
