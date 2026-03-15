from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings as app_settings
from bot.db.queries import (
    add_ticket_message,
    create_admin_ticket_reminder,
    create_ticket,
    deactivate_ping_error_alert,
    get_user_by_telegram_id,
    upsert_ping_error_alert,
)
from bot.db.session import async_session as _async_session
from bot.keyboards.inline import (
    get_ip_change_confirm_keyboard,
    get_ip_delete_confirm_keyboard,
    get_ip_deleted_keyboard,
    get_ip_management_keyboard,
    get_ip_monitoring_keyboard_no_ip,
    get_ip_ping_error_keyboard,
    get_ip_ping_fail_keyboard,
    get_ip_ping_result_keyboard,
    get_ip_saved_fail_keyboard,
    get_ip_saved_keyboard,
    get_ip_saved_success_keyboard,
    get_ip_support_admin_keyboard,
    get_ip_support_cancel_keyboard,
    get_ip_support_sent_keyboard,
    get_settings_keyboard,
)
from bot.states.fsm import IpSetupSG, IpSupportSG
from bot.utils.helpers import is_valid_ip_or_domain
from bot.utils.logger import get_logger

KYIV_TZ = ZoneInfo("Europe/Kyiv")

router = Router(name="settings_ip")
logger = get_logger(__name__)

_INSTRUCTION_TEXT = (
    '<tg-emoji emoji-id="5312532335042794821">⚙️</tg-emoji> Налаштування моніторингу світла\n\n'
    "Бот визначає статус світла у вас вдома — пінгуючи ваш роутер. Для цього потрібно вказати адресу вашого роутера.\n\n"
    "Переконайтесь що ваш роутер вимикається при відключенні світла. Якщо роутер підключений до "
    "безперебійника або павербанку — вкажіть інший пристрій, який живиться напряму від мережі.\n\n"
    "Варіант 1 — Статична (біла) IP-адреса\n"
    "Зверніться до провайдера (~30–50 грн/місяць).\n"
    '<a href="https://2ip.ua/ua/services/ip-service/ping-traceroute">Перевірити доступність IP ззовні</a>\n'
    '<a href="https://2ip.ua/ua/services/ip-service/port-check">Перевірити доступність порту (Port Forwarding)</a>\n\n'
    "Варіант 2 — DDNS (якщо немає статичного IP)\n"
    "Налаштовується в налаштуваннях роутера.\n"
    "Інструкції для роутерів:\n"
    '<a href="https://www.asus.com/ua-ua/support/FAQ/1011725/">ASUS</a> · '
    '<a href="https://help-wifi.com/tp-link/nastrojka-ddns-dinamicheskij-dns-na-routere-tp-link/">TP-Link</a> · '
    '<a href="https://www.youtube.com/watch?v=Q97_8XVyBuo">TP-Link відео</a> · '
    '<a href="https://www.hardreset.info/uk/devices/netgear/netgear-dgnd3700v2/faq/dns-settings/how-to-change-dns/">NETGEAR</a> · '
    '<a href="https://yesondd.com/361-dlinkddns-com-remote-access-to-d-link-wifi-router-via-internet-via-ddns">D-Link</a> · '
    '<a href="https://xn----7sba7aachdbqfnhtigrl.xn--j1amh/nastrojka-mikrotik-cloud-sobstvennyj-ddns/">MikroTik</a> · '
    '<a href="https://www.hardreset.info/ru/devices/xiaomi/xiaomi-mi-router-4a/nastroyki-dns/">Xiaomi</a>\n\n'
    "Приклади вводу:\n"
    "192.168.1.1\n"
    "192.168.1.1:80\n"
    "myhome.ddns.net\n\n"
    "Введіть вашу IP-адресу або DDNS:"
)


async def _safe_edit(message, text: str, **kwargs) -> None:
    """Edit message with tg-emoji fallback and keyboard fallback."""
    try:
        await message.edit_text(text, parse_mode="HTML", **kwargs)
    except Exception as first_err:
        logger.warning("_safe_edit first attempt failed: %s", first_err)
        clean = re.sub(r'<tg-emoji[^>]*>([^<]*)</tg-emoji>', r'\1', text)
        try:
            await message.edit_text(clean, parse_mode="HTML", **kwargs)
        except Exception as second_err:
            logger.warning("_safe_edit second attempt failed: %s", second_err)
            # Third fallback: strip reply_markup in case keyboard is causing the error
            try:
                await message.edit_text(clean, parse_mode="HTML")
            except Exception as third_err:
                logger.error("_safe_edit all attempts failed: %s", third_err)
                try:
                    await message.edit_text("❌ Виникла помилка. Спробуйте ще раз.")
                except Exception as final_err:
                    logger.error("_safe_edit could not notify user: %s", final_err)


async def _show_settings(callback: CallbackQuery, session: AsyncSession) -> None:
    """Helper: show main settings screen (replicates back_to_settings logic)."""
    from bot.formatter.messages import format_live_status_message

    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.message.edit_text("❌ Спочатку запустіть бота, натиснувши /start")
        return
    is_admin = app_settings.is_admin(callback.from_user.id)
    text = format_live_status_message(user)
    await _safe_edit(
        callback.message, text, reply_markup=get_settings_keyboard(is_admin=is_admin)
    )


async def _show_management_screen(callback: CallbackQuery, session: AsyncSession) -> None:
    """Helper: show IP management screen (Екран 1Б).

    Immediately shows the screen with "Перевіряю..." status and keyboard,
    then performs a fresh ping and updates only the text (not the keyboard).
    """
    from bot.services.power_monitor import _check_router_http

    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.message.edit_text("❌ Спочатку запустіть бота, натиснувши /start")
        return
    if not user.router_ip:
        await callback.message.edit_text("❌ IP-адреса не налаштована.")
        return

    router_ip = user.router_ip

    # Step 1: Show immediately with "Перевіряю..." status + keyboard (no wait for ping)
    loading_text = (
        '<tg-emoji emoji-id="5312532335042794821">⚙️</tg-emoji> IP моніторинг\n\n'
        f'<tg-emoji emoji-id="5312283536177273995">📡</tg-emoji> IP: {router_ip}'
        f'\nСтатус: Перевіряю <tg-emoji emoji-id="5890925363067886150">⏳</tg-emoji>'
    )
    await _safe_edit(callback.message, loading_text, reply_markup=get_ip_management_keyboard())

    # Step 2: Perform a fresh ping
    is_alive = await _check_router_http(router_ip)

    # Step 3: Update only the text, preserving the existing keyboard
    if is_alive:
        status_line = '\nСтатус: <tg-emoji emoji-id="5309771882252243514">🟢</tg-emoji> Онлайн'
    else:
        status_line = '\nСтатус: <tg-emoji emoji-id="5312380297495484470">🔴</tg-emoji> Офлайн'

    result_text = (
        '<tg-emoji emoji-id="5312532335042794821">⚙️</tg-emoji> IP моніторинг\n\n'
        f'<tg-emoji emoji-id="5312283536177273995">📡</tg-emoji> IP: {router_ip}'
        f'{status_line}'
    )
    # Edit text AND preserve the existing keyboard by passing reply_markup=callback.message.reply_markup
    existing_keyboard = callback.message.reply_markup
    try:
        await callback.message.edit_text(result_text, parse_mode="HTML", reply_markup=existing_keyboard)
    except Exception as e:
        logger.warning("_show_management_screen: could not update status text: %s", e)
        clean = re.sub(r'<tg-emoji[^>]*>([^<]*)</tg-emoji>', r'\1', result_text)
        try:
            await callback.message.edit_text(clean, parse_mode="HTML", reply_markup=existing_keyboard)
        except Exception as e2:
            logger.warning("_show_management_screen: fallback also failed: %s", e2)


async def _show_input_screen(callback: CallbackQuery, state: FSMContext) -> None:
    """Helper: show instruction + IP input screen (Екран 1А)."""
    await _safe_edit(
        callback.message,
        _INSTRUCTION_TEXT,
        reply_markup=get_ip_monitoring_keyboard_no_ip(),
        disable_web_page_preview=True,
    )
    await state.set_state(IpSetupSG.waiting_for_ip)


# ─── Screen 1A / 1B ───────────────────────────────────────────────────────


@router.callback_query(F.data == "settings_ip")
async def settings_ip(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    await state.clear()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.message.edit_text("❌ Спочатку запустіть бота, натиснувши /start")
        return
    try:
        if user.router_ip:
            await _show_management_screen(callback, session)
        else:
            await _show_input_screen(callback, state)
    except Exception as e:
        logger.error("settings_ip error for user %s: %s", callback.from_user.id, e)
        await callback.message.edit_text("❌ Виникла помилка. Спробуйте ще раз.")


# ─── Screen 2 — Change confirm ────────────────────────────────────────────


@router.callback_query(F.data == "ip_change")
async def ip_change(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    try:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not user:
            await callback.message.edit_text("❌ Спочатку запустіть бота, натиснувши /start")
            return
        text = (
            "Зміна IP-адреси\n\n"
            f"Поточна IP-адреса: {user.router_ip}\n\n"
            "Ви впевнені що хочете змінити IP-адресу?"
        )
        await callback.message.edit_text(
            text, reply_markup=get_ip_change_confirm_keyboard(), parse_mode="HTML"
        )
    except Exception as e:
        logger.error("ip_change error for user %s: %s", callback.from_user.id, e)
        try:
            await callback.message.edit_text("❌ Виникла помилка. Спробуйте ще раз.")
        except Exception as notify_err:
            logger.error("ip_change could not notify user: %s", notify_err)


@router.callback_query(F.data == "ip_change_confirm")
async def ip_change_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _show_input_screen(callback, state)


# ─── Screen 3 — Delete confirm ────────────────────────────────────────────


@router.callback_query(F.data == "ip_delete_confirm")
async def ip_delete_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    try:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not user:
            await callback.message.edit_text("❌ Спочатку запустіть бота, натиснувши /start")
            return
        text = (
            "Видалення IP-адреси\n\n"
            f"Ви впевнені що хочете видалити IP-адресу\n{user.router_ip}?\n\n"
            "Моніторинг світла буде вимкнено."
        )
        await callback.message.edit_text(
            text, reply_markup=get_ip_delete_confirm_keyboard(), parse_mode="HTML"
        )
    except Exception as e:
        logger.error("ip_delete_confirm error for user %s: %s", callback.from_user.id, e)
        try:
            await callback.message.edit_text("❌ Виникла помилка. Спробуйте ще раз.")
        except Exception as notify_err:
            logger.error("ip_delete_confirm could not notify user: %s", notify_err)


# ─── Screen 4 — After delete ──────────────────────────────────────────────


@router.callback_query(F.data == "ip_delete_execute")
async def ip_delete_execute(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user:
        user.router_ip = None
        await session.flush()
        try:
            await deactivate_ping_error_alert(session, str(user.telegram_id))
        except Exception:
            pass
    text = (
        '<tg-emoji emoji-id="5264973221576349285">✅</tg-emoji> IP-адресу видалено\n\n'
        "Моніторинг світла вимкнено."
    )
    await _safe_edit(callback.message, text, reply_markup=get_ip_deleted_keyboard())


# ─── Legacy aliases (backward compat) ────────────────────────────────────


@router.callback_query(F.data == "ip_delete_do")
async def ip_delete_do(callback: CallbackQuery, session: AsyncSession) -> None:
    await ip_delete_execute(callback, session)


@router.callback_query(F.data == "ip_change_do")
async def ip_change_do(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _show_input_screen(callback, state)


# ─── ip_cancel_to_settings — return to settings ───────────────────────────


@router.callback_query(F.data == "ip_cancel_to_settings")
async def ip_cancel_to_settings(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await callback.answer()
    await state.clear()
    await _show_settings(callback, session)


# ─── ip_cancel — legacy alias ────────────────────────────────────────────


@router.callback_query(F.data == "ip_cancel")
async def ip_cancel(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    await state.clear()
    await _show_settings(callback, session)


# ─── ip_cancel_to_management — return to Screen 1Б ───────────────────────


@router.callback_query(F.data == "ip_cancel_to_management")
async def ip_cancel_to_management(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await _show_management_screen(callback, session)


# ─── ip_ping_check — Screen 6 ─────────────────────────────────────────────


@router.callback_query(F.data == "ip_ping_check")
async def ip_ping_check(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.router_ip:
        await callback.message.edit_text("❌ Спочатку запустіть бота, натиснувши /start")
        return
    router_ip = user.router_ip
    loading_text = (
        '<tg-emoji emoji-id="5312283536177273995">📡</tg-emoji> IP-моніторинг\n'
        f"{router_ip}\n"
        'Перевіряю <tg-emoji emoji-id="5890925363067886150">⏳</tg-emoji>'
    )
    await _safe_edit(callback.message, loading_text)
    from bot.services.power_monitor import _check_router_http
    is_alive = await _check_router_http(router_ip)

    if is_alive:
        result_text = '<tg-emoji emoji-id="5264973221576349285">✅</tg-emoji> Пінг пройшов успішно'
        keyboard = get_ip_ping_result_keyboard()
    else:
        result_text = '<tg-emoji emoji-id="5264933407229517572">❌</tg-emoji> Пінг не пройшов'
        keyboard = get_ip_ping_fail_keyboard()
    await _safe_edit(callback.message, result_text, reply_markup=keyboard)


# ─── IP input handler (Screen 5) ──────────────────────────────────────────


@router.message(IpSetupSG.waiting_for_ip)
async def ip_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.text:
        await message.reply("❌ Введіть IP-адресу або домен.")
        return

    result = is_valid_ip_or_domain(message.text)
    if not result["valid"]:
        await message.reply(f"❌ {result['error']}")
        return

    user = await get_user_by_telegram_id(session, message.from_user.id)
    if user:
        user.router_ip = result["address"]
        await session.flush()

    status_msg = await message.answer(
        'Перевіряю IP-адресу <tg-emoji emoji-id="5890925363067886150">⏳</tg-emoji>',
        parse_mode="HTML",
    )

    from bot.services.power_monitor import _check_router_http
    is_alive = await _check_router_http(result["address"])

    if is_alive:
        result_text = (
            '<tg-emoji emoji-id="5264973221576349285">✅</tg-emoji> '
            "IP збережено. Пінг пройшов успішно, моніторинг увімкнено."
        )
    else:
        result_text = (
            '<tg-emoji emoji-id="5264933407229517572">❌</tg-emoji> '
            "IP збережено. Пінг наразі не проходить — можливо, зараз немає світла. "
            "Моніторинг почнеться автоматично коли з'єднання відновиться."
        )
        if user:
            try:
                await upsert_ping_error_alert(session, str(user.telegram_id), result["address"])
            except Exception:
                pass

    await state.clear()
    keyboard = get_ip_saved_success_keyboard() if is_alive else get_ip_saved_fail_keyboard()
    await status_msg.edit_text(
        result_text, reply_markup=keyboard, parse_mode="HTML"
    )


# ─── ip_ping_error_support — Support ticket flow ─────────────────────────


@router.callback_query(F.data == "ip_ping_error_support")
async def ip_ping_error_support(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    text = (
        '<tg-emoji emoji-id="5310296757320586255">💬</tg-emoji> Служба підтримки\n\n'
        "Напишіть ваше повідомлення, і адміністратор\n"
        "відповість вам найближчим часом."
    )
    await _safe_edit(callback.message, text, reply_markup=get_ip_support_cancel_keyboard())
    await state.set_state(IpSupportSG.waiting_for_message)


# ─── ip_ping_support — legacy alias ──────────────────────────────────────


@router.callback_query(F.data == "ip_ping_support")
async def ip_ping_support(callback: CallbackQuery, state: FSMContext) -> None:
    await ip_ping_error_support(callback, state)


@router.message(IpSupportSG.waiting_for_message)
async def ip_support_message(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.text:
        await message.reply("❌ Будь ласка, надішліть текстове повідомлення.")
        return

    user = await get_user_by_telegram_id(session, message.from_user.id)
    if not user:
        await state.clear()
        return

    ticket = await create_ticket(
        session,
        telegram_id=user.telegram_id,
        ticket_type="ip_support",
        subject="IP підтримка",
    )
    await add_ticket_message(
        session,
        ticket_id=ticket.id,
        sender_type="user",
        sender_id=user.telegram_id,
        content=message.text,
    )
    await session.commit()

    await state.clear()

    await message.answer(
        '<tg-emoji emoji-id="5264973221576349285">✅</tg-emoji> Ваше повідомлення надіслано\n\n'
        "Адміністратор відповість вам найближчим часом.",
        reply_markup=get_ip_support_sent_keyboard(),
        parse_mode="HTML",
    )

    now_str = datetime.now(KYIV_TZ).strftime("%d.%m.%Y %H:%M")
    username = f"@{user.username}" if user.username else "(без username)"
    ip_line = f"\n📡 IP: {user.router_ip}" if user.router_ip else ""
    admin_text = (
        "📩 Нове звернення від користувача\n\n"
        f"👤 {username} (ID: {user.telegram_id})\n"
        f"🌍 Регіон: {user.region} | Черга: {user.queue}"
        f"{ip_line}\n"
        f"📅 Дата: {now_str}\n"
        f"💬 {message.text}"
    )
    for admin_id in app_settings.all_admin_ids:
        try:
            await message.bot.send_message(
                admin_id,
                admin_text,
                reply_markup=get_ip_support_admin_keyboard(ticket.id),
                parse_mode="HTML",
            )
        except Exception:
            pass

    for admin_id in app_settings.all_admin_ids:
        try:
            async with _async_session() as s:
                await create_admin_ticket_reminder(s, ticket.id, str(admin_id))
                await s.commit()
        except Exception:
            pass


@router.callback_query(F.data == "ip_support_cancel")
async def ip_support_cancel(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await callback.answer()
    await state.clear()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.message.edit_text("❌ Спочатку запустіть бота, натиснувши /start")
        return
    from bot.formatter.messages import format_main_menu_message
    from bot.keyboards.inline import get_main_menu

    has_channel = bool(user.channel_config and user.channel_config.channel_id)
    channel_paused = bool(user.channel_config and user.channel_config.channel_paused)
    text = format_main_menu_message(user)
    await callback.message.edit_text(
        text,
        reply_markup=get_main_menu(channel_paused=channel_paused, has_channel=has_channel),
        parse_mode="HTML",
    )


# ─── Legacy callbacks ─────────────────────────────────────────────────────


@router.callback_query(F.data == "ip_instruction")
async def ip_instruction(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _show_input_screen(callback, state)


@router.callback_query(F.data == "ip_setup")
async def ip_setup(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _show_input_screen(callback, state)


@router.callback_query(F.data == "ip_show")
async def ip_show(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user and user.router_ip:
        text = f"📡 Поточна IP: {user.router_ip}"
        if user.power_tracking and user.power_tracking.power_state:
            state_text = "🟢 Онлайн" if user.power_tracking.power_state == "on" else "🔴 Офлайн"
            text += f"\nСтатус: {state_text}"
        await callback.answer(text, show_alert=True)
    else:
        await callback.answer("📡 IP не налаштовано")


@router.callback_query(F.data == "ip_delete")
async def ip_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user:
        user.router_ip = None
        await session.flush()
        try:
            await deactivate_ping_error_alert(session, str(user.telegram_id))
        except Exception:
            pass
    from bot.keyboards.inline import get_ip_deleted_keyboard
    await callback.message.edit_text(
        '<tg-emoji emoji-id="5264973221576349285">✅</tg-emoji> IP-адресу видалено\n\n'
        "Моніторинг світла вимкнено.",
        reply_markup=get_ip_deleted_keyboard(),
        parse_mode="HTML",
    )
