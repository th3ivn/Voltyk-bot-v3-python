from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_user_by_telegram_id
from bot.formatter.messages import build_channel_notification_message, build_notification_settings_message
from bot.keyboards.inline import (
    E_BELL,
    get_channel_notification_keyboard,
    get_notification_main_keyboard,
    get_notification_reminders_keyboard,
    get_notification_select_keyboard,
    get_notification_target_select_keyboard,
    get_notification_targets_keyboard,
)
from bot.utils.helpers import safe_parse_callback_int
from bot.utils.telegram import safe_edit_reply_markup, safe_edit_text

router = Router(name="settings_alerts")


@router.callback_query(F.data.in_({"settings_alerts", "notif_main"}))
async def settings_alerts(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return

    has_channel = bool(user.channel_config and user.channel_config.channel_id)
    if has_channel:
        await safe_edit_text(
            callback.message,
            f'<tg-emoji emoji-id="{E_BELL}">🔔</tg-emoji> Керування сповіщеннями\n\nОберіть, що хочете налаштувати:',
            reply_markup=get_notification_select_keyboard(),
        )
    else:
        ns = user.notification_settings
        if not ns:
            return
        text = build_notification_settings_message(ns)
        await safe_edit_text(
            callback.message,
            text,
            reply_markup=get_notification_main_keyboard(
                schedule_changes=ns.notify_schedule_changes,
                remind_off=ns.notify_remind_off,
                fact_off=ns.notify_fact_off,
                remind_on=ns.notify_remind_on,
                fact_on=ns.notify_fact_on,
                remind_15m=ns.remind_15m,
                remind_30m=ns.remind_30m,
                remind_1h=ns.remind_1h,
            ),
        )


@router.callback_query(F.data == "notif_select_bot")
async def notif_select_bot(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.notification_settings:
        return
    ns = user.notification_settings
    text = build_notification_settings_message(ns)
    await safe_edit_text(
        callback.message,
        text,
        reply_markup=get_notification_main_keyboard(
            schedule_changes=ns.notify_schedule_changes,
            remind_off=ns.notify_remind_off,
            fact_off=ns.notify_fact_off,
            remind_on=ns.notify_remind_on,
            fact_on=ns.notify_fact_on,
            remind_15m=ns.remind_15m,
            remind_30m=ns.remind_30m,
            remind_1h=ns.remind_1h,
            back_cb="settings_alerts",
        ),
    )


@router.callback_query(F.data == "notif_select_channel")
async def notif_select_channel(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.channel_config:
        return
    cc = user.channel_config
    text = build_channel_notification_message(cc)
    await safe_edit_text(
        callback.message,
        text,
        reply_markup=get_channel_notification_keyboard(
            schedule=cc.ch_notify_schedule,
            remind_off=cc.ch_notify_remind_off,
            fact_off=cc.ch_notify_fact_off,
            remind_on=cc.ch_notify_remind_on,
            fact_on=cc.ch_notify_fact_on,
            remind_15m=cc.ch_remind_15m,
            remind_30m=cc.ch_remind_30m,
            remind_1h=cc.ch_remind_1h,
        ),
    )


@router.callback_query(F.data == "notif_toggle_schedule")
async def notif_toggle_schedule(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user and user.notification_settings:
        ns = user.notification_settings
        ns.notify_schedule_changes = not ns.notify_schedule_changes
        text = build_notification_settings_message(ns)
        await safe_edit_text(
            callback.message,
            text,
            reply_markup=get_notification_main_keyboard(
                schedule_changes=ns.notify_schedule_changes,
                remind_off=ns.notify_remind_off,
                fact_off=ns.notify_fact_off,
                remind_on=ns.notify_remind_on,
                fact_on=ns.notify_fact_on,
                remind_15m=ns.remind_15m,
                remind_30m=ns.remind_30m,
                remind_1h=ns.remind_1h,
            ),
        )
    await callback.answer()


@router.callback_query(F.data == "notif_reminders")
async def notif_reminders(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.notification_settings:
        return
    ns = user.notification_settings
    await safe_edit_text(
        callback.message,
        "⏰ Нагадування",
        reply_markup=get_notification_reminders_keyboard(
            remind_off=ns.notify_remind_off,
            fact_off=ns.notify_fact_off,
            remind_on=ns.notify_remind_on,
            fact_on=ns.notify_fact_on,
            remind_15m=ns.remind_15m,
            remind_30m=ns.remind_30m,
            remind_1h=ns.remind_1h,
        ),
    )


@router.callback_query(F.data.startswith("notif_toggle_"))
async def notif_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    field = callback.data.replace("notif_toggle_", "")
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.notification_settings:
        await callback.answer()
        return
    ns = user.notification_settings
    field_map = {
        "remind_off": "notify_remind_off",
        "fact_off": "notify_fact_off",
        "remind_on": "notify_remind_on",
        "fact_on": "notify_fact_on",
    }
    attr = field_map.get(field)
    if attr:
        new_val = not getattr(ns, attr)
        setattr(ns, attr, new_val)
        # Keep fact_off and fact_on in sync — both represent IP-based detection
        if field == "fact_off":
            ns.notify_fact_on = new_val
        elif field == "fact_on":
            ns.notify_fact_off = new_val
    text = build_notification_settings_message(ns)
    await safe_edit_text(
        callback.message,
        text,
        reply_markup=get_notification_main_keyboard(
            schedule_changes=ns.notify_schedule_changes,
            remind_off=ns.notify_remind_off,
            fact_off=ns.notify_fact_off,
            remind_on=ns.notify_remind_on,
            fact_on=ns.notify_fact_on,
            remind_15m=ns.remind_15m,
            remind_30m=ns.remind_30m,
            remind_1h=ns.remind_1h,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("notif_time_"))
async def notif_time(callback: CallbackQuery, session: AsyncSession) -> None:
    minutes = safe_parse_callback_int(callback.data, "notif_time_")
    if minutes is None:
        await callback.answer()
        return
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.notification_settings:
        await callback.answer()
        return
    ns = user.notification_settings
    if minutes == 15:
        ns.remind_15m = not ns.remind_15m
    elif minutes == 30:
        ns.remind_30m = not ns.remind_30m
    elif minutes == 60:
        ns.remind_1h = not ns.remind_1h
    text = build_notification_settings_message(ns)
    await safe_edit_text(
        callback.message,
        text,
        reply_markup=get_notification_main_keyboard(
            schedule_changes=ns.notify_schedule_changes,
            remind_off=ns.notify_remind_off,
            fact_off=ns.notify_fact_off,
            remind_on=ns.notify_remind_on,
            fact_on=ns.notify_fact_on,
            remind_15m=ns.remind_15m,
            remind_30m=ns.remind_30m,
            remind_1h=ns.remind_1h,
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "notif_targets")
async def notif_targets(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    has_ip = bool(user and user.router_ip)
    await safe_edit_text(
        callback.message,
        "📍 Куди надсилати сповіщення",
        reply_markup=get_notification_targets_keyboard(has_ip=has_ip),
    )


@router.callback_query(F.data.startswith("notif_target_type_"))
async def notif_target_type(callback: CallbackQuery, session: AsyncSession) -> None:
    target_type = callback.data.replace("notif_target_type_", "")
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.notification_settings:
        return
    ns = user.notification_settings
    target_map = {
        "schedule": ns.notify_schedule_target,
        "remind": ns.notify_remind_target,
        "power": ns.notify_power_target,
    }
    current = target_map.get(target_type, "bot")
    await safe_edit_text(
        callback.message,
        "Куди надсилати:",
        reply_markup=get_notification_target_select_keyboard(target_type, current),
    )


@router.callback_query(F.data.startswith("notif_target_set_"))
async def notif_target_set(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.replace("notif_target_set_", "").rsplit("_", 1)
    if len(parts) != 2:
        await callback.answer()
        return
    target_type, target_value = parts
    # Validate target_value against the fixed set of allowed destinations so a
    # crafted callback_data cannot write arbitrary strings into the DB column.
    # "both" is valid — the UI keyboard includes a "📱📺 Обидва" button.
    _ALLOWED_TARGETS = {"bot", "channel", "both"}
    if target_value not in _ALLOWED_TARGETS:
        await callback.answer()
        return
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.notification_settings:
        await callback.answer()
        return
    ns = user.notification_settings
    attr_map = {
        "schedule": "notify_schedule_target",
        "remind": "notify_remind_target",
        "power": "notify_power_target",
    }
    attr = attr_map.get(target_type)
    if attr:
        setattr(ns, attr, target_value)
    await safe_edit_reply_markup(
        callback.message,
        reply_markup=get_notification_target_select_keyboard(target_type, target_value),
    )
    await callback.answer("✅ Збережено")


@router.callback_query(F.data == "alert_toggle")
async def alert_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user and user.notification_settings:
        ns = user.notification_settings
        enabled = any([ns.notify_schedule_changes, ns.notify_remind_off, ns.notify_fact_off])
        new_val = not enabled
        ns.notify_schedule_changes = new_val
        ns.notify_remind_off = new_val
        ns.notify_fact_off = new_val
        ns.notify_remind_on = new_val
        ns.notify_fact_on = new_val
    await callback.answer("✅ Збережено")


@router.callback_query(F.data.startswith("ch_notif_"))
async def ch_notif_handler(callback: CallbackQuery, session: AsyncSession) -> None:
    action = callback.data.replace("ch_notif_", "")
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.channel_config:
        await callback.answer()
        return
    cc = user.channel_config

    if action == "toggle_schedule":
        cc.ch_notify_schedule = not cc.ch_notify_schedule
    elif action == "toggle_fact":
        new_val = not cc.ch_notify_fact_off
        cc.ch_notify_fact_off = new_val
        cc.ch_notify_fact_on = new_val
    elif action.startswith("time_"):
        minutes = safe_parse_callback_int(action, "time_")
        if minutes is None:
            await callback.answer()
            return
        if minutes == 15:
            cc.ch_remind_15m = not cc.ch_remind_15m
        elif minutes == 30:
            cc.ch_remind_30m = not cc.ch_remind_30m
        elif minutes == 60:
            cc.ch_remind_1h = not cc.ch_remind_1h

    text = build_channel_notification_message(cc)
    await safe_edit_text(
        callback.message,
        text,
        reply_markup=get_channel_notification_keyboard(
            schedule=cc.ch_notify_schedule,
            remind_off=cc.ch_notify_remind_off,
            fact_off=cc.ch_notify_fact_off,
            remind_on=cc.ch_notify_remind_on,
            fact_on=cc.ch_notify_fact_on,
            remind_15m=cc.ch_remind_15m,
            remind_30m=cc.ch_remind_30m,
            remind_1h=cc.ch_remind_1h,
        ),
    )
    await callback.answer()
