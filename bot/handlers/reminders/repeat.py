"""/repeat — регулярные (ежедневные) напоминания (PRD RECURRING-REMINDERS).

Одной строкой: ``/repeat полить цветы каждый день в 10:00``. Бот шлёт сырой
текст на бэкенд, тот парсит расписание и считает next_fire_at в таймзоне юзера.
Распознавание регулярности из СВОБОДНОГО текста НЕ делаем — только явная команда.

Owns its own ``Router()``; aggregated by package ``__init__``.
"""
from __future__ import annotations

import logging
from html import escape

import httpx
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.common.auth import ensure_user

logger = logging.getLogger(__name__)

router = Router()

REPEAT_HELP_TEXT = (
    "🔁 <b>Регулярное напоминание</b>\n\n"
    "Пример: <code>/repeat полить цветы каждый день в 10:00</code>\n\n"
    "Пока только ежедневно. Время — в твоей таймзоне (см. /tz)."
)

_FALLBACK_ERR = (
    "Не понял расписание. Пример: /repeat полить цветы каждый день в 10:00"
)


def _confirm_text(series: dict) -> str:
    """Подтверждение серии. На дубле — «Уже напоминаю…»."""
    hh = int(series.get("hour", 0))
    mm = int(series.get("minute", 0))
    text = escape((series.get("text") or "").strip())
    when = f"{hh:02d}:{mm:02d}"
    head = "🔁 Уже напоминаю" if series.get("deduplicated") else "🔁 Буду напоминать"
    return f"{head} каждый день в <b>{when}</b> — «{text}»"


@router.message(Command("repeat"))
async def cmd_repeat(message: Message, command: CommandObject, api, store):
    """Завести ежедневную серию из явной команды /repeat."""
    args = (command.args or "").strip()
    if not args:
        await message.answer(REPEAT_HELP_TEXT, parse_mode="HTML")
        return

    token = await ensure_user(message, api)
    if not token:
        return

    try:
        series = await api.create_recurring(token, args)
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 422:
            detail = _FALLBACK_ERR
            try:
                detail = e.response.json().get("detail") or detail
            except Exception:
                pass
            await message.answer(detail)
            return
        logger.warning("cmd_repeat: create_recurring HTTP error: %s", e)
        await message.answer("Не получилось завести напоминание, попробуй ещё раз.")
        return
    except Exception as e:
        logger.warning("cmd_repeat: create_recurring failed: %s", e)
        await message.answer("Не получилось завести напоминание, попробуй ещё раз.")
        return

    await message.answer(_confirm_text(series), parse_mode="HTML")
