from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings as app_settings
from bot.constants.regions import REGIONS
from bot.db.queries import get_user_by_telegram_id
from bot.formatter.messages import format_live_status_message
from bot.keyboards.inline import get_region_keyboard, get_settings_keyboard
from bot.states.fsm import WizardSG
from bot.utils.telegram import safe_edit_text

router = Router(name="settings_region")


@router.callback_query(F.data == "settings_region")
async def settings_region(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return
    region = REGIONS.get(user.region)
    region_name = region.name if region else user.region
    await safe_edit_text(callback.message,
        f"⚠️ Зміна регіону/черги\n\nПоточний: {region_name}, черга {user.queue}\n\nЗмінити?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Так, змінити", callback_data="settings_region_confirm")],
                [InlineKeyboardButton(text="Скасувати", callback_data="back_to_settings")],
            ]
        ),
    )


@router.callback_query(F.data == "settings_region_confirm")
async def settings_region_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    current_region = user.region if user else None
    await state.set_state(WizardSG.region)
    await state.update_data(mode="edit")
    await safe_edit_text(callback.message,
        "1️⃣ Оберіть ваш регіон:",
        reply_markup=get_region_keyboard(current_region=current_region),
    )


@router.callback_query(F.data == "back_to_settings")
async def back_to_settings(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return
    is_admin = app_settings.is_admin(callback.from_user.id)
    text = format_live_status_message(user)
    await safe_edit_text(callback.message,
        text, reply_markup=get_settings_keyboard(is_admin=is_admin), parse_mode="HTML"
    )
