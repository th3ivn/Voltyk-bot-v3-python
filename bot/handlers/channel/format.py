from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_user_by_telegram_id
from bot.keyboards.inline import (
    get_format_power_keyboard,
    get_format_schedule_keyboard,
    get_format_settings_keyboard,
)
from bot.states.fsm import ChannelConversationSG
from bot.utils.telegram import safe_edit_text

router = Router(name="channel_format")


@router.callback_query(F.data.in_({"channel_format", "format_menu"}))
async def format_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await safe_edit_text(callback.message,
        "📋 Формат публікацій\n\nОберіть, що хочете налаштувати:",
        reply_markup=get_format_settings_keyboard(),
    )


@router.callback_query(F.data == "format_schedule_settings")
async def format_schedule_settings(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.channel_config:
        return
    cc = user.channel_config
    await safe_edit_text(callback.message,
        "📊 Графік відключень\n\nНалаштуйте формат публікацій графіка:",
        reply_markup=get_format_schedule_keyboard(
            delete_old=cc.delete_old_message, picture_only=cc.picture_only
        ),
    )


@router.callback_query(F.data == "format_power_settings")
async def format_power_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    await safe_edit_text(callback.message,
        "⚡ Фактичний стан\n\nНалаштуйте текст повідомлень про стан світла:",
        reply_markup=get_format_power_keyboard(),
    )


@router.callback_query(F.data == "format_toggle_delete")
async def format_toggle_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user and user.channel_config:
        user.channel_config.delete_old_message = not user.channel_config.delete_old_message
        await callback.message.edit_reply_markup(
            reply_markup=get_format_schedule_keyboard(
                delete_old=user.channel_config.delete_old_message,
                picture_only=user.channel_config.picture_only,
            )
        )
    await callback.answer()


@router.callback_query(F.data == "format_toggle_piconly")
async def format_toggle_piconly(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user and user.channel_config:
        user.channel_config.picture_only = not user.channel_config.picture_only
        await callback.message.edit_reply_markup(
            reply_markup=get_format_schedule_keyboard(
                delete_old=user.channel_config.delete_old_message,
                picture_only=user.channel_config.picture_only,
            )
        )
    await callback.answer()


@router.callback_query(F.data == "format_schedule_text")
async def format_schedule_text(callback: CallbackQuery) -> None:
    await callback.answer()
    text = (
        "📝 Текст графіка\n\n"
        "Доступні змінні:\n"
        "{d} — дата (01.01.2026)\n"
        "{dm} — дата без року (01.01)\n"
        "{dd} — сьогодні/завтра\n"
        "{sdw} — день тижня (Пн)\n"
        "{fdw} — день тижня (Понеділок)\n"
        "{queue} — номер черги\n"
        "{region} — назва регіону\n"
        "<br> — перенос рядка"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Змінити підпис", callback_data="format_schedule_caption")],
            [InlineKeyboardButton(text="⏰ Змінити формат часу", callback_data="format_schedule_periods")],
            [InlineKeyboardButton(text="← Назад", callback_data="format_schedule_settings")],
        ]
    )
    await safe_edit_text(callback.message, text, reply_markup=kb)


@router.callback_query(F.data == "format_schedule_caption")
async def format_schedule_caption(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ChannelConversationSG.waiting_for_schedule_caption)
    await safe_edit_text(callback.message,
        "📝 Шаблон підпису під графіком\n\n"
        "Введіть шаблон підпису. Доступні змінні:\n"
        "{d}, {dm}, {dd}, {sdw}, {fdw}, {queue}, {region}, <br>"
    )


@router.callback_query(F.data == "format_schedule_periods")
async def format_schedule_periods(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ChannelConversationSG.waiting_for_period_format)
    await safe_edit_text(callback.message,
        "⏰ Формат періодів відключень\n\n"
        "Введіть формат. Доступні змінні:\n"
        "{s} — початок, {f} — кінець, {h} — тривалість"
    )


@router.callback_query(F.data == "format_power_off")
async def format_power_off(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ChannelConversationSG.waiting_for_power_off_text)
    await safe_edit_text(callback.message,
        '📴 Текст при відключенні світла\n\n'
        "Введіть текст. Доступні змінні:\n"
        "{time} — час, {date} — дата, {duration} — тривалість, {schedule} — графік"
    )


@router.callback_query(F.data == "format_power_on")
async def format_power_on(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ChannelConversationSG.waiting_for_power_on_text)
    await safe_edit_text(callback.message,
        '💡 Текст при появі світла\n\n'
        "Введіть текст. Доступні змінні:\n"
        "{time} — час, {date} — дата, {duration} — тривалість, {schedule} — графік"
    )


@router.callback_query(F.data.startswith("format_reset_"))
async def format_reset(callback: CallbackQuery, session: AsyncSession) -> None:
    action = callback.data.replace("format_reset_", "")
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.channel_config:
        await callback.answer()
        return
    cc = user.channel_config

    if action == "caption":
        cc.schedule_caption = None
        await callback.answer("✅ Підпис скинуто")
    elif action == "periods":
        cc.period_format = None
        await callback.answer("✅ Формат скинуто")
    elif action == "power_off":
        cc.power_off_text = None
        await callback.answer("✅ Текст відключення скинуто")
    elif action == "power_on":
        cc.power_on_text = None
        await callback.answer("✅ Текст включення скинуто")
    elif action == "all_schedule":
        cc.schedule_caption = None
        cc.period_format = None
        await callback.answer("✅ Все скинуто")
    elif action == "all_power":
        cc.power_off_text = None
        cc.power_on_text = None
        await callback.answer("✅ Все скинуто")
    else:
        await callback.answer()
