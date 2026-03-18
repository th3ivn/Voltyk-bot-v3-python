# feedback.py — підтримка через зовнішній канал, без тікетів
from __future__ import annotations

from aiogram import Router

router = Router(name="feedback")
# Логіка підтримки перенесена на зовнішній Telegram-канал.
# Старі handlers feedback_start, feedback_type, feedback_message,
# feedback_confirm, feedback_cancel — видалені.
