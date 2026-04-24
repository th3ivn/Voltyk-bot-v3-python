from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import settings
from bot.db.queries import (
    deactivate_user,
    delete_setting,
    get_active_user_ids_cursor,
    get_setting,
    set_setting,
)
from bot.db.session import async_session
from bot.keyboards.inline import get_broadcast_cancel_keyboard
from bot.states.fsm import BroadcastSG
from bot.utils.logger import get_logger
from bot.utils.metrics import BROADCAST_MESSAGES_SENT
from bot.utils.rate_limiter import tg_rate_limiter
from bot.utils.telegram import safe_edit_text

logger = get_logger(__name__)
router = Router(name="admin_broadcast")

BROADCAST_HEADER = '📢 <b>Повідомлення від адміністрації:</b>\n\n'
_BROADCAST_MAX_TEXT_LEN = 4096 - len(BROADCAST_HEADER)
_PROGRESS_EVERY = 1000

# Setting key that holds the JSON-encoded snapshot of an in-flight broadcast.
# When present at startup it means the previous run was killed (SIGTERM,
# crash, OOM) before finishing.  Broadcasts over 150k users take minutes, so
# loosing progress is expensive — the operator is offered a resume option.
BROADCAST_STATE_KEY = "interrupted_broadcast"
# Checkpoint cadence — every N successful sends persist progress.  500
# trades a small amount of potential double-send on restart (last batch may
# be re-delivered) for a cheap DB write cost (150k users / 500 = 300 writes).
_CHECKPOINT_EVERY = 500

# ─── Active broadcast state ─────────────────────────────────────────────

_active_broadcast: asyncio.Task | None = None
_broadcast_cancel: asyncio.Event = asyncio.Event()
_broadcast_lock: asyncio.Lock = asyncio.Lock()


async def _save_checkpoint(
    text: str, admin_id: int, last_id: int, sent: int, failed: int, blocked: int
) -> None:
    """Persist broadcast progress so a restart can resume from last_id."""
    payload = json.dumps(
        {
            "text": text,
            "admin_id": admin_id,
            "last_id": last_id,
            "sent": sent,
            "failed": failed,
            "blocked": blocked,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    try:
        async with async_session() as session:
            await set_setting(session, BROADCAST_STATE_KEY, payload)
            await session.commit()
    except Exception as e:
        # Never fail the broadcast because the checkpoint didn't persist —
        # the worst case is we can't resume on restart, which is the
        # pre-feature status quo.
        logger.warning("Broadcast checkpoint save failed: %s", e)


async def _clear_checkpoint() -> None:
    try:
        async with async_session() as session:
            await delete_setting(session, BROADCAST_STATE_KEY)
            await session.commit()
    except Exception as e:
        logger.warning("Broadcast checkpoint clear failed: %s", e)


async def load_interrupted_broadcast() -> dict | None:
    """Return the interrupted-broadcast snapshot if one exists, else None.

    Called from :func:`bot.app.on_startup` so operators are alerted that a
    previous run was killed mid-send and can choose to resume or abort.
    """
    try:
        async with async_session() as session:
            raw = await get_setting(session, BROADCAST_STATE_KEY)
    except Exception as e:
        logger.warning("Could not probe for interrupted broadcast: %s", e)
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Interrupted-broadcast payload is malformed, clearing")
        await _clear_checkpoint()
        return None


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
    await safe_edit_text(callback.message,
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
    await safe_edit_text(callback.message,
        "✏️ Введіть новий текст:", reply_markup=get_broadcast_cancel_keyboard()
    )


@router.callback_query(F.data == "broadcast_confirm_send")
async def broadcast_confirm_send(callback: CallbackQuery, state: FSMContext) -> None:
    global _active_broadcast
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return

    async with _broadcast_lock:
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
        await safe_edit_text(callback.message, "📤 Розсилка розпочата...", reply_markup=cancel_kb)

        admin_id = callback.from_user.id
        bot = callback.bot
        assert bot is not None  # always set inside handlers
        _active_broadcast = asyncio.create_task(
            _run_broadcast(bot, BROADCAST_HEADER + text, admin_id)
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
    await safe_edit_text(callback.message, "❌ Розсилку скасовано.")


# ─── Background broadcast ───────────────────────────────────────────────


async def _run_broadcast(
    bot: Bot,
    full_text: str,
    admin_id: int,
    *,
    start_last_id: int = 0,
    start_sent: int = 0,
    start_failed: int = 0,
    start_blocked: int = 0,
) -> None:
    """Send broadcast in background, reporting progress to admin.

    Checkpoints progress every _CHECKPOINT_EVERY successful sends so an
    interrupted run (SIGTERM, crash, OOM) can be resumed on the next
    startup.  The ``start_*`` parameters let the resume path continue
    from where the previous process stopped.
    """
    global _active_broadcast
    sent = start_sent
    failed = start_failed
    blocked = start_blocked
    last_id = start_last_id
    batch_size = 500
    interrupted = False

    # Persist the initial snapshot so even an immediate SIGKILL after the
    # first acquire() leaves a trail operators can resume.
    await _save_checkpoint(full_text, admin_id, last_id, sent, failed, blocked)

    try:
        while True:
            if _broadcast_cancel.is_set():
                break

            async with async_session() as session:
                batch = await get_active_user_ids_cursor(session, limit=batch_size, after_id=last_id)
            if not batch:
                break

            for row in batch:
                if _broadcast_cancel.is_set():
                    break
                row_id, row_tid = row
                telegram_id = int(row_tid)
                await tg_rate_limiter.acquire()
                for attempt in range(settings.TELEGRAM_MAX_RETRIES + 1):
                    try:
                        await bot.send_message(telegram_id, full_text, parse_mode="HTML")
                        sent += 1
                        BROADCAST_MESSAGES_SENT.inc()
                        break
                    except TelegramForbiddenError:
                        blocked += 1
                        # User blocked the bot — deactivate to avoid future sends.
                        try:
                            async with async_session() as session:
                                await deactivate_user(session, row_tid)
                                await session.commit()
                        except Exception as _de:
                            logger.warning("Could not deactivate blocked user %s: %s", row_tid, _de)
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

                # Checkpoint after each user so a SIGKILL loses at most one
                # user's worth of progress — the cost is a DB write every
                # _CHECKPOINT_EVERY messages, not every message.
                if sent > 0 and sent % _CHECKPOINT_EVERY == 0:
                    await _save_checkpoint(full_text, admin_id, row_id, sent, failed, blocked)

                if sent > 0 and sent % _PROGRESS_EVERY == 0:
                    try:
                        await bot.send_message(
                            admin_id,
                            f"📤 Прогрес розсилки: надіслано {sent}, помилок {failed}, заблокували {blocked}",
                        )
                    except Exception as e:
                        logger.debug("Could not send broadcast progress to admin: %s", e)

            last_id = batch[-1][0] if batch else last_id

    except asyncio.CancelledError:
        # Shutdown mid-broadcast (SIGTERM → on_shutdown cancels background
        # tasks).  Leave the checkpoint in place — on_startup will offer
        # resume.  Still write a final structured log so operators see the
        # interruption in the logs even if they don't act on the prompt.
        interrupted = True
        logger.warning(
            "Broadcast interrupted: sent=%d failed=%d blocked=%d last_id=%d",
            sent, failed, blocked, last_id,
        )
        await _save_checkpoint(full_text, admin_id, last_id, sent, failed, blocked)
    except Exception as e:
        logger.error("Broadcast error: %s", e, exc_info=True)
        failed += 1

    # Clean exit (completed or explicitly cancelled): drop the checkpoint so
    # the next startup doesn't offer to resume a finished broadcast.
    if not interrupted:
        await _clear_checkpoint()

    # Send final summary
    cancelled = _broadcast_cancel.is_set()
    if interrupted:
        status = "⏸ Розсилку перервано (рестарт пода) — можна продовжити"
    elif cancelled:
        status = "⏹ Розсилку зупинено"
    else:
        status = "✅ Розсилка завершена"
    summary_parts = [f"{status}\n\n📤 Надіслано: {sent}\n❌ Помилок: {failed}"]
    if blocked:
        summary_parts.append(f"🚫 Заблокували бота: {blocked}")
    try:
        await bot.send_message(admin_id, "\n".join(summary_parts))
    except Exception as e:
        logger.error("Could not send broadcast summary to admin: %s", e, exc_info=True)


# ─── Resume / Abort handlers (called from startup prompt) ───────────────


@router.callback_query(F.data == "broadcast_resume")
async def broadcast_resume(callback: CallbackQuery) -> None:
    """Resume an interrupted broadcast from the last checkpointed user id."""
    global _active_broadcast
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return

    snapshot = await load_interrupted_broadcast()
    if snapshot is None:
        await callback.answer("ℹ️ Немає перерваної розсилки", show_alert=True)
        await safe_edit_text(callback.message, "ℹ️ Нема перерваної розсилки.")
        return

    async with _broadcast_lock:
        if is_broadcast_running():
            await callback.answer("⚠️ Розсилка вже виконується", show_alert=True)
            return

        await callback.answer("▶️ Продовжуємо розсилку...")
        _broadcast_cancel.clear()

        await safe_edit_text(
            callback.message,
            f"▶️ Продовжуємо розсилку з користувача #{snapshot['last_id']}...",
        )

        bot = callback.bot
        assert bot is not None
        _active_broadcast = asyncio.create_task(
            _run_broadcast(
                bot,
                full_text=snapshot["text"],
                admin_id=snapshot["admin_id"],
                start_last_id=int(snapshot["last_id"]),
                start_sent=int(snapshot.get("sent", 0)),
                start_failed=int(snapshot.get("failed", 0)),
                start_blocked=int(snapshot.get("blocked", 0)),
            )
        )


@router.callback_query(F.data == "broadcast_abort_interrupted")
async def broadcast_abort_interrupted(callback: CallbackQuery) -> None:
    """Drop the interrupted-broadcast checkpoint without resuming."""
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return

    await _clear_checkpoint()
    await callback.answer("✅ Перервана розсилка скасована")
    await safe_edit_text(callback.message, "✅ Перервану розсилку скасовано.")


def get_interrupted_broadcast_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Продовжити", callback_data="broadcast_resume")],
            [
                InlineKeyboardButton(
                    text="❌ Скасувати", callback_data="broadcast_abort_interrupted"
                ),
            ],
        ]
    )
