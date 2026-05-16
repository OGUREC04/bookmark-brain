"""Команда /tz — сменить часовой пояс пользователя.

Использование:
    /tz                       — показать текущий часовой пояс
    /tz Europe/Moscow         — сменить на MSK
    /tz Europe/Kaliningrad    — сменить на UTC+2
    /tz reset                 — вернуть default (Europe/Moscow)

Часовой пояс используется для парсинга «завтра в 9» в reminder'ах:
без него юзер из Калининграда получит напоминание в 8 утра по своим часам.
"""
from __future__ import annotations

import logging

import httpx
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

logger = logging.getLogger(__name__)

router = Router()

DEFAULT_TZ = "Europe/Moscow"
HELP_TEXT = (
    "Часовой пояс нужен, чтобы «напомнить завтра в 9» сработало по твоему времени.\n\n"
    "Использование:\n"
    "<code>/tz</code> — показать текущий\n"
    "<code>/tz Europe/Moscow</code> — сменить (IANA-имя)\n"
    "<code>/tz reset</code> — вернуть в Europe/Moscow\n\n"
    "Популярные пояса:\n"
    "• <code>Europe/Moscow</code> (UTC+3)\n"
    "• <code>Europe/Kaliningrad</code> (UTC+2)\n"
    "• <code>Europe/Samara</code> (UTC+4)\n"
    "• <code>Asia/Yekaterinburg</code> (UTC+5)\n"
    "• <code>Asia/Novosibirsk</code> (UTC+7)\n"
    "• <code>Asia/Vladivostok</code> (UTC+10)"
)


@router.message(Command("tz"))
async def cmd_tz(message: Message, api):
    """Показать или сменить часовой пояс юзера."""
    from bot.common.auth import ensure_user

    token = await ensure_user(message, api)
    if not token:
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 1:
        # /tz без аргумента — показать текущий
        try:
            user = await api.get_me(token)
        except Exception as exc:
            logger.error("Failed to get user: %s", exc)
            await message.answer("Не получилось получить настройки.", parse_mode=None)
            return
        current = user.get("timezone", DEFAULT_TZ)
        await message.answer(
            f"Твой часовой пояс: <code>{current}</code>\n\n{HELP_TEXT}",
            parse_mode="HTML",
        )
        return

    arg = parts[1].strip()
    if arg.lower() == "reset":
        new_tz = DEFAULT_TZ
    else:
        new_tz = arg

    try:
        await api.update_timezone(token, new_tz)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 400:
            await message.answer(
                f"Пояс <code>{new_tz}</code> не похож на IANA-имя.\n\n{HELP_TEXT}",
                parse_mode="HTML",
            )
        else:
            logger.error("Failed to update timezone: %s", exc)
            await message.answer("Ошибка сервера.", parse_mode=None)
        return
    except Exception as exc:
        logger.error("Failed to update timezone: %s", exc)
        await message.answer("Ошибка сервера.", parse_mode=None)
        return

    await message.answer(
        f"Часовой пояс: <code>{new_tz}</code>",
        parse_mode="HTML",
    )
