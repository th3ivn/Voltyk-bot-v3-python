from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings as app_settings
from bot.db.queries import get_user_by_telegram_id
from bot.keyboards.inline import (
    get_faq_keyboard,
    get_help_keyboard,
    get_instruction_section_keyboard,
    get_instructions_keyboard,
    get_support_keyboard,
)
from bot.utils.telegram import safe_edit_or_resend

router = Router(name="menu_help")


@router.callback_query(F.data == "menu_help")
async def menu_help(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    faq_url = app_settings.FAQ_CHANNEL_URL or None
    support_url = app_settings.SUPPORT_CHANNEL_URL or None
    msg = await safe_edit_or_resend(
        callback.message,
        "❓ Допомога\n\nТут ви можете дізнатися як користуватися\nботом або звернутися за підтримкою.",
        reply_markup=get_help_keyboard(faq_url=faq_url, support_url=support_url),
    )
    if user and msg:
        user.last_menu_message_id = msg.message_id


@router.callback_query(F.data == "help_instructions")
async def help_instructions(callback: CallbackQuery) -> None:
    await callback.answer()
    await safe_edit_or_resend(
        callback.message,
        "📖 Інструкція\n\nОберіть розділ який вас цікавить:",
        reply_markup=get_instructions_keyboard(),
    )


@router.callback_query(F.data == "help_faq")
async def help_faq(callback: CallbackQuery) -> None:
    await callback.answer()
    faq_url = app_settings.FAQ_CHANNEL_URL or None
    text = (
        '<tg-emoji emoji-id="5319180751143476261">❓</tg-emoji> FAQ\n\n'
        "Тут ви знайдете відповіді на найпоширеніші\n"
        "питання про роботу бота."
    )
    await safe_edit_or_resend(
        callback.message,
        text,
        reply_markup=get_faq_keyboard(faq_url=faq_url),
    )


@router.callback_query(F.data == "help_support")
async def help_support(callback: CallbackQuery) -> None:
    await callback.answer()
    support_url = app_settings.SUPPORT_CHANNEL_URL or None
    text = (
        '<tg-emoji emoji-id="5310296757320586255">💬</tg-emoji> Служба підтримки\n\n'
        "Натисніть кнопку нижче щоб написати\n"
        "адміністратору напряму в Telegram.\n"
        "Відповідь надійде найближчим часом."
    )
    await safe_edit_or_resend(
        callback.message,
        text,
        reply_markup=get_support_keyboard(support_url=support_url),
    )


@router.callback_query(F.data == "instr_region")
async def instr_region(callback: CallbackQuery) -> None:
    await callback.answer()
    text = (
        '<tg-emoji emoji-id="5319069545850247853">📍</tg-emoji> Регіон і черга\n\n'
        "Для отримання графіку відключень потрібно\n"
        "обрати свій регіон та чергу.\n\n"
        "Як знайти свою чергу — введіть свою адресу\n"
        "на сайті свого обленерго:\n\n"
        '• Київ — <a href="https://www.dtek-kem.com.ua/ua/shutdowns">dtek-kem.com.ua</a>\n'
        '• Київська обл. — <a href="https://www.dtek-krem.com.ua/ua/shutdowns">dtek-krem.com.ua</a>\n'
        '• Дніпропетровська обл. — <a href="https://www.dtek-dnem.com.ua/ua/shutdowns">dtek-dnem.com.ua</a>\n'
        '• Одеська обл. — <a href="https://www.dtek-oem.com.ua/ua/shutdowns">dtek-oem.com.ua</a>\n\n'
        "Як налаштувати в боті:\n"
        "1. Перейдіть в Налаштування → Регіон\n"
        "2. Оберіть свою область\n"
        "3. Оберіть свою чергу (наприклад 3.1)"
    )
    await safe_edit_or_resend(callback.message, text, reply_markup=get_instruction_section_keyboard())


@router.callback_query(F.data == "instr_notif")
async def instr_notif(callback: CallbackQuery) -> None:
    await callback.answer()
    text = (
        '<tg-emoji emoji-id="5262598817626234330">🔔</tg-emoji> Сповіщення\n\n'
        "Бот автоматично надсилає сповіщення про:\n"
        "• Зміни в графіку відключень\n"
        "• Появу нового графіку на завтра\n"
        "• Щоденний графік о 06:00\n"
        "• Фактичне зникнення та появу світла (з IP)\n\n"
        "Куди надходять сповіщення:\n"
        "• В особистий чат з ботом\n"
        "• В підключений канал (якщо налаштовано)\n\n"
        "Важливо: бот і канал мають окремі\n"
        "налаштування сповіщень — ви можете\n"
        "увімкнути або вимкнути їх незалежно\n"
        "один від одного.\n\n"
        "Як налаштувати:\n"
        "1. Перейдіть в Налаштування → Сповіщення\n"
        "2. Налаштуйте окремо для бота і каналу"
    )
    await safe_edit_or_resend(callback.message, text, reply_markup=get_instruction_section_keyboard())


@router.callback_query(F.data == "instr_channel")
async def instr_channel(callback: CallbackQuery) -> None:
    await callback.answer()
    text = (
        '<tg-emoji emoji-id="5312374181462055424">📺</tg-emoji> Канал\n\n'
        "Ви можете підключити свій Telegram канал —\n"
        "бот автоматично публікуватиме в ньому\n"
        "графіки відключень та сповіщення.\n\n"
        "Що публікується в каналі:\n"
        "• Графік відключень (фото + текст)\n"
        "• Сповіщення про зміни графіку\n"
        "• Сповіщення про зникнення та появу світла\n\n"
        "Як підключити:\n"
        "1. Перейдіть в Налаштування → Канал\n"
        "2. Натисніть кнопку Підключити канал\n"
        "3. Перейдіть у свій канал і додайте бота\n"
        "   як адміністратора\n"
        "4. Бот автоматично виявить канал і\n"
        "   запитає підтвердження підключення\n\n"
        "Канал має окремі налаштування сповіщень —\n"
        "незалежно від особистого чату з ботом."
    )
    await safe_edit_or_resend(callback.message, text, reply_markup=get_instruction_section_keyboard())


@router.callback_query(F.data == "instr_ip")
async def instr_ip(callback: CallbackQuery) -> None:
    await callback.answer()
    text = (
        '<tg-emoji emoji-id="5312283536177273995">📡</tg-emoji> IP моніторинг\n\n'
        "Бот може визначати фактичний статус світла\n"
        "у вас вдома — пінгуючи ваш роутер.\n\n"
        "Важливо: роутер має вимикатись при\n"
        "відключенні світла. Якщо він підключений\n"
        "до безперебійника — моніторинг не працюватиме\n"
        "коректно.\n\n"
        "Що потрібно:\n"
        "• Статична (біла) IP-адреса роутера\n"
        "  (~30–50 грн/місяць у провайдера)\n"
        "• або DDNS — якщо немає статичного IP\n\n"
        "Що отримуєте:\n"
        "• Сповіщення коли світло зникло\n"
        "• Сповіщення коли світло з'явилося\n"
        "• Визначення позапланових відключень\n\n"
        "Як підключити:\n"
        "1. Перейдіть в Налаштування → IP\n"
        "2. Введіть IP-адресу або DDNS вашого роутера\n"
        "3. Бот автоматично перевірить з'єднання\n\n"
        "Підтримувані формати:\n"
        "• 89.267.32.1\n"
        "• 89.267.32.1:80\n"
        "• myhome.ddns.net"
    )
    await safe_edit_or_resend(callback.message, text, reply_markup=get_instruction_section_keyboard())


@router.callback_query(F.data == "instr_schedule")
async def instr_schedule(callback: CallbackQuery) -> None:
    await callback.answer()
    text = (
        '<tg-emoji emoji-id="5264999721524562037">📊</tg-emoji> Графік відключень\n\n'
        "Бот показує актуальний графік відключень\n"
        "для вашого регіону та черги.\n\n"
        "Що показує графік:\n"
        "• Планові відключення на сьогодні\n"
        "• Планові відключення на завтра\n"
        "• Загальний час без світла за день\n\n"
        "Щоденне повідомлення о 06:00:\n"
        "Кожного ранку бот надсилає актуальний\n"
        "графік на поточний день.\n\n"
        "Як переглянути графік:\n"
        "1. Натисніть кнопку Графік в головному меню\n"
        "2. Дочекайтесь щоденного повідомлення о 06:00\n"
        "3. Увімкніть сповіщення — і бот сам\n"
        "   повідомить коли графік зміниться\n\n"
        "Порівняння графіків:\n"
        "Ви можете порівнювати графік за вчора\n"
        "та сьогодні — бот зберігає історію\n"
        "по кожному календарному дню."
    )
    await safe_edit_or_resend(callback.message, text, reply_markup=get_instruction_section_keyboard())


@router.callback_query(F.data == "instr_bot_settings")
async def instr_bot_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    text = (
        '<tg-emoji emoji-id="5312280340721604022">⚙️</tg-emoji> Налаштування бота\n\n'
        "В налаштуваннях ви можете керувати\n"
        "всіма параметрами бота.\n\n"
        "Що можна налаштувати:\n"
        "• Регіон і черга — змінити свій регіон\n"
        "• Сповіщення — увімкнути або вимкнути\n"
        "• Канал — підключити свій Telegram канал\n"
        "• IP моніторинг — налаштувати відстеження\n"
        "  фактичного стану світла\n\n"
        "Додаткові можливості:\n"
        "• Тимчасово зупинити / відновити канал —\n"
        "  керуйте публікаціями в канал в будь-який\n"
        "  момент прямо з головного меню або\n"
        "  налаштувань каналу\n"
        "• Видалити мої дані — повністю видалити\n"
        "  всі ваші дані з бота\n\n"
        "Як відкрити налаштування:\n"
        "Натисніть кнопку Налаштування\n"
        "в головному меню."
    )
    await safe_edit_or_resend(callback.message, text, reply_markup=get_instruction_section_keyboard())
