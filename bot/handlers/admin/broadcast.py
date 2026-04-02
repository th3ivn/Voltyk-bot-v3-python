from __future__ import annotations

import asyncio

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import settings
from bot.db.queries import get_active_user_ids_paginated
from bot.db.session import async_session
from bot.keyboards.inline import get_broadcast_cancel_keyboard
from bot.states.fsm import BroadcastSG
from bot.utils.logger import get_logger

logger = get_logger(__name__)
router = Router(name="admin_broadcast")

BROADCAST_HEADER = '📢 <b>Повідомлення від адміністрації:</b>\n\n'
_BROADCAST_MAX_TEXT_LEN = 4096 - len(BROADCAST_HEADER)
_SEND_DELAY_S = 1.0 / settings.TELEGRAM_RATE_LIMIT_PER_SEC
_PROGRESS_EVERY = 1000

# ─── Active broadcast state ─────────────────────────────────────────────

_active_broadcast: asyncio.Task | None = None
_broadcast_cancel: asyncio.Event = asyncio.Event()


def is_broadcast_running() -> bool:
    return _active_broadcast is not None and not _active_broadcast.done()


# ─── Handlers ────────────────────────────────────────────────────────────


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    if is_broadcast_running():
        await callback.answer("⚠️ Розсилка вже виконується", show_alert=True)
        return
    await callback.answer()
    await state.set_state(BroadcastSG.waiting_for_text)
    await callback.message.edit_text(
        f"📢 Розсилка\n\nВведіть текст повідомлення (макс. {_BROADCAST_MAX_TEXT_LEN} символів):",
        reply_markup=get_broadcast_cancel_keyboard(),
    )


@router.message(BroadcastSG.waiting_for_text)
async def broadcast_text(message: Message, state: FSMContext) -> None:
    if not settings.is_admin(message.from_user.id):
        await state.clear()
        return
    if not message.text:
        await message.reply("❌ Введіть текст повідомлення")
        return
    if len(message.text) > _BROADCAST_MAX_TEXT_LEN:
        await message.reply(
            f"❌ Текст занадто довгий: {len(message.text)} символів.\n"
            f"Максимум: {_BROADCAST_MAX_TEXT_LEN} символів."
        )
        return
    await state.update_data(broadcast_text=message.text)
    await state.set_state(BroadcastSG.preview)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Відправити", callback_data="broadcast_confirm_send")],
            [InlineKeyboardButton(text="✏️ Редагувати текст", callback_data="broadcast_edit_text")],
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="broadcast_cancel")],
        ]
    )
    preview = BROADCAST_HEADER + message.text
    await message.answer(f"👁 Попередній перегляд:\n\n{preview}", reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "broadcast_edit_text")
async def broadcast_edit_text(callback: CallbackQuery, state: FSMContext) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    await state.set_state(BroadcastSG.waiting_for_text)
    await callback.message.edit_text(
        "✏️ Введіть новий текст:", reply_markup=get_broadcast_cancel_keyboard()
    )


@router.callback_query(F.data == "broadcast_confirm_send")
async def broadcast_confirm_send(callback: CallbackQuery, state: FSMContext) -> None:
    global _active_broadcast
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    if is_broadcast_running():
        await callback.answer("⚠️ Розсилка вже виконується", show_alert=True)
        return
    data = await state.get_data()
    text = data.get("broadcast_text", "")
    await state.clear()
    await callback.answer()

    _broadcast_cancel.clear()
    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏹ Зупинити розсилку", callback_data="broadcast_cancel_active")],
        ]
    )
    await callback.message.edit_text("📤 Розсилка розпочата...", reply_markup=cancel_kb)

    admin_id = callback.from_user.id
    _active_broadcast = asyncio.create_task(
        _run_broadcast(callback.bot, BROADCAST_HEADER + text, admin_id)
    )


@router.callback_query(F.data == "broadcast_cancel_active")
async def broadcast_cancel_active(callback: CallbackQuery) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    if not is_broadcast_running():
        await callback.answer("ℹ️ Розсилка не активна")
        return
    _broadcast_cancel.set()
    await callback.answer("⏹ Зупиняємо розсилку...")


@router.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("❌ Розсилку скасовано.")


# ─── Background broadcast ───────────────────────────────────────────────


async def _run_broadcast(bot: Bot, full_text: str, admin_id: int) -> None:
    """Send broadcast in background, reporting progress to admin."""
    global _active_broadcast
    sent = 0
    failed = 0
    blocked = 0
    offset = 0
    batch_size = 500

    try:
        while True:
            if _broadcast_cancel.is_set():
                break

            async with async_session() as session:
                batch = await get_active_user_ids_paginated(session, limit=batch_size, offset=offset)
            if not batch:
                break

            for row in batch:
                if _broadcast_cancel.is_set():
                    break
                telegram_id = int(row.telegram_id)
                for attempt in range(settings.TELEGRAM_MAX_RETRIES + 1):
                    try:
                        await bot.send_message(telegram_id, full_text, parse_mode="HTML")
                        sent += 1
                        break
                    except TelegramForbiddenError:
                        blocked += 1
                        break
                    except TelegramRetryAfter as e:
                        if attempt >= settings.TELEGRAM_MAX_RETRIES:
                            logger.warning(
                                "Broadcast: rate limit exceeded for user %s after %d retries",
                                telegram_id, settings.TELEGRAM_MAX_RETRIES,
                            )
                            failed += 1
                            break
                        await asyncio.sleep(e.retry_after + 1)
                    except Exception as e:
                        logger.warning("Broadcast failed for user %s: %s", telegram_id, e)
                        failed += 1
                        break
                await asyncio.sleep(_SEND_DELAY_S)

                if sent > 0 and sent % _PROGRESS_EVERY == 0:
                    try:
                        await bot.send_message(
                            admin_id,
                            f"📤 Прогрес розсилки: надіслано {sent}, помилок {failed}, заблокували {blocked}",
                        )
                    except Exception:
                        pass

            offset += len(batch)

    except asyncio.CancelledError:
        logger.info("Broadcast task cancelled")
    except Exception as e:
        logger.error("Broadcast error: %s", e)
        failed += 1

    # Send final summary
    cancelled = _broadcast_cancel.is_set()
    status = "⏹ Розсилку зупинено" if cancelled else "✅ Розсилка завершена"
    summary_parts = [f"{status}\n\n📤 Надіслано: {sent}\n❌ Помилок: {failed}"]
    if blocked:
        summary_parts.append(f"🚫 Заблокували бота: {blocked}")
    try:
        await bot.send_message(admin_id, "\n".join(summary_parts))
    except Exception as e:
        logger.error("Could not send broadcast summary to admin: %s", e)
