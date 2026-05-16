"""Shared auth-bootstrap seam for bot feature packages.

`ensure_user` is the single place that turns an incoming Telegram
message/callback into a backend JWT (creating the user on first contact).
It lives in `bot.common` — the lowest bot layer — so every feature package
(handlers/*) and the orchestration layer can depend on it WITHOUT importing
each other. This keeps the auth concern under the import-linter/layers
contract instead of being a hidden fan-in to an orchestration module.

The token cache and TTL are auth internals: module-private, not exported.
"""
from __future__ import annotations

import logging
import time

from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)

# Кэш токенов: telegram_id -> (JWT token, expires_at)
_user_tokens: dict[int, tuple[str, float]] = {}

_TOKEN_TTL = 6 * 24 * 3600  # 6 days (JWT is 7 days, refresh before expiry)


async def ensure_user(message_or_callback, api) -> str | None:
    """Получить JWT-токен юзера, создав его при необходимости."""
    user = message_or_callback.from_user

    tg_id = user.id
    cached = _user_tokens.get(tg_id)
    if cached:
        token, expires_at = cached
        if time.monotonic() < expires_at:
            return token

    try:
        data = await api.get_or_create_user(
            telegram_id=tg_id,
            username=user.username,
            first_name=user.first_name,
        )
        token = data["access_token"]
        _user_tokens[tg_id] = (token, time.monotonic() + _TOKEN_TTL)
        return token
    except Exception as e:
        logger.error(f"Failed to auth user {tg_id}: {e}")
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.answer("Ошибка подключения к серверу.", show_alert=True)
        else:
            await message_or_callback.answer("Ошибка подключения к серверу. Попробуй позже.", parse_mode=None)
        return None
