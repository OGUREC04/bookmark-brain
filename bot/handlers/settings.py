"""Настройки бота — /silent toggle."""

import asyncio
import logging
import time

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.utils import _delete_after

logger = logging.getLogger(__name__)

router = Router()

# Кэш silent_mode: telegram_id -> (silent: bool, expires_at: float)
_silent_cache: dict[int, tuple[bool, float]] = {}
_CACHE_TTL = 300  # 5 минут


async def is_silent(api, token: str, telegram_id: int) -> bool:
    """Проверить включён ли silent mode. Default: True (silent по умолчанию)."""
    cached = _silent_cache.get(telegram_id)
    if cached:
        silent, expires_at = cached
        if time.monotonic() < expires_at:
            return silent

    try:
        user = await api.get_me(token)
        settings = user.get("settings") or {}
        silent = settings.get("silent_mode", True)  # default: True
        _silent_cache[telegram_id] = (silent, time.monotonic() + _CACHE_TTL)
        return silent
    except Exception as e:
        logger.debug("Failed to get user settings: %s", e)
        return True  # default: silent


def invalidate_cache(telegram_id: int) -> None:
    """Сбросить кэш после переключения."""
    _silent_cache.pop(telegram_id, None)


@router.message(Command("silent"))
async def cmd_silent(message: Message, api):
    """Переключить тихий/обычный режим."""
    from bot.common.auth import ensure_user

    token = await ensure_user(message, api)
    if not token:
        return

    tg_id = message.from_user.id

    # Определяем текущее состояние
    current_silent = await is_silent(api, token, tg_id)

    # Проверяем аргумент: /silent on | /silent off
    parts = (message.text or "").split()
    if len(parts) > 1:
        arg = parts[1].lower()
        if arg == "on":
            new_silent = True
        elif arg == "off":
            new_silent = False
        else:
            new_silent = not current_silent
    else:
        new_silent = not current_silent

    # Обновляем на сервере
    try:
        await api.update_settings(token, {"silent_mode": new_silent})
        invalidate_cache(tg_id)
    except Exception as e:
        logger.error("Failed to update silent mode: %s", e)
        await message.answer("Ошибка при обновлении настроек.", parse_mode=None)
        return

    if new_silent:
        text = "🔕 Тихий режим включён. Буду подтверждать реакциями 👀→👍"
    else:
        text = "🔔 Обычный режим включён. Буду отвечать текстом."

    # Ephemeral: удалить через 8 секунд
    reply = await message.answer(text, parse_mode=None)
    asyncio.create_task(_delete_after(reply, delay=8))
