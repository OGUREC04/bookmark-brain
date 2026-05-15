"""Бот-handlers для напоминаний (Phase 2.5 T6).

Состоит из:
1. Четыре callback'а на inline-кнопках:
   - rsk:{bookmark_id}    — юзер подтвердил создание после save → просим время
   - rsn:{bookmark_id}    — отказ → убираем кнопки, чистим state
   - rdone:{reminder_id}  — нажал «Выполнено» на отправленном reminder
   - rsnz:{reminder_id}   — нажал «Продлить» → просим новое время
2. Reply-handler: ловит reply на сообщение с pending offer или snooze,
   парсит время через `backend.app.services.nl_date.parse()`, дёргает API.

Ключи Redis (ставит worker, читает бот):
  reminder_pending:{chat_id}:{msg_id} → bookmark_id (TTL 1ч)
  reminder:{chat_id}:{msg_id}         → reminder_id (TTL 25ч)
  reminder_snooze:{chat_id}:{msg_id}  → reminder_id (TTL 1ч)
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)

router = Router()

# Часовой пояс по умолчанию — если у юзера в users.timezone пусто или
# зона не распарсилась.
DEFAULT_TZ = "Europe/Moscow"

# Безопасные лимиты на пользовательский текст перед записью в Redis.
# Защита от DoS-наполнения памяти Redis (H2 из security review).
MAX_REMINDER_TEXT_LEN = 500
# Максимальная длина reply-текста перед передачей в dateparser (M2 защитный).
MAX_PARSE_INPUT_LEN = 200


def _safe(s: str | None) -> str:
    """HTML-escape для встраивания юзерского текста в parse_mode=HTML.

    Telegram HTML mode допускает `<a>`, `<b>`, `<i>`, `<code>`, `<pre>` —
    без экранирования юзер может вставить `<a href="tg://...">` (C-sec).
    """
    return html.escape(s or "", quote=False)


def _cap_text(s: str | None, limit: int = MAX_REMINDER_TEXT_LEN) -> str:
    """Обрезаем пользовательский текст до безопасного лимита."""
    if not s:
        return ""
    if len(s) <= limit:
        return s
    return s[: limit - 3] + "..."


def _is_valid_uuid(s: str | None) -> bool:
    """Проверка что строка из callback_data — валидный UUID.

    Защита от подделанного callback_data (H1): без валидации значение
    напрямую улетает в API URL.
    """
    if not s:
        return False
    try:
        UUID(s)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


async def _send_reminder_confirmation_with_chip(
    message: Message, fire_at: datetime, reminder_text: str, tz_name: str,
) -> None:
    """Подтверждение reminder с полным форматом даты для авто-детекции
    клиентом Telegram.

    Bot API 9.5 разрешает date_time MessageEntity только в checklist /
    quote / gift, причём checklist требует business_connection_id —
    обычные боты её слать не могут. Поэтому полагаемся на client-side
    NSDataDetector / TextClassifier: полный формат «12.05.2026 09:00»
    распознаётся iOS/Android клиентами как дата с long-press меню
    «добавить в календарь». Работает не на всех клиентах, но это
    лучшее что доступно без business-режима.
    """
    short_text = (reminder_text or "").strip() or "напоминание"
    if len(short_text) > 60:
        short_text = short_text[:57] + "..."

    # Полный формат даты ДД.ММ.ГГГГ ЧЧ:ММ — авто-детект на стороне клиента.
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo(DEFAULT_TZ)
    local = fire_at.astimezone(tz)
    formatted_full = local.strftime("%d.%m.%Y %H:%M")

    await message.answer(
        f"🔔 Напомню <b>{_safe(formatted_full)}</b> — «{_safe(short_text)}»",
        parse_mode="HTML",
    )


def extract_first_datetime_entity(message: Message) -> datetime | None:
    """T19 (Bot API 9.5): если в сообщении есть MessageEntity type='date_time' —
    Telegram-клиент уже определил дату в локали и таймзоне юзера. Используем
    готовый unix_time, парсер не нужен.

    Fallback на nl_date.parse если entity нет (старые клиенты до Bot API 9.5).
    """
    entities = list(message.entities or []) + list(message.caption_entities or [])
    for ent in entities:
        ent_type = getattr(ent, "type", None)
        # aiogram отдаёт enum или строку — поддержим оба
        if hasattr(ent_type, "value"):
            ent_type = ent_type.value
        if ent_type == "date_time":
            unix_ts = getattr(ent, "unix_time", None)
            if unix_ts is not None:
                try:
                    return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc)
                except (TypeError, ValueError, OSError):
                    continue
    return None

# Подсказка с примерами для reply'я (используется в rsk: и rsnz:)
TIME_EXAMPLES = (
    "Примеры:\n"
    "• <code>через час</code>\n"
    "• <code>завтра в 9</code>\n"
    "• <code>в субботу в 18</code>\n"
    "• <code>15 мая</code>"
)


def _reply_prompt(question: str) -> str:
    """Унифицированный текст prompt'а для ввода времени через reply.

    UX: Reply подсвечено максимально явно — отдельная строка с ↩️ + жирный
    текст + конкретный пример. Без этого юзеры шлют next-message вместо
    reply и попадают в catch-all → save_yes/no → «Не сохраняю».
    См. bookmark-brain-4dr.
    """
    return (
        f"{question}\n\n"
        f"↩️ <b>Сделай Reply</b> на это сообщение со временем "
        f"(зажми/свайпни сообщение → «Ответить»).\n\n"
        f"{TIME_EXAMPLES}"
    )


# ──────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────


async def _get_user_tz_name(api, token: str) -> str:
    """IANA-имя часового пояса юзера. Fallback Europe/Moscow если поле
    пусто или невалидно. Возвращаем строку — `nl_date.parse()` сам
    валидирует через ZoneInfo внутри."""
    try:
        user = await api.get_me(token)
        tz_name = (user or {}).get("timezone") or DEFAULT_TZ
    except Exception as e:
        logger.warning(f"_get_user_tz_name: get_me failed, using {DEFAULT_TZ}: {e}")
        return DEFAULT_TZ
    try:
        ZoneInfo(tz_name)  # валидируем
        return tz_name
    except Exception:
        logger.warning(f"_get_user_tz_name: invalid tz {tz_name!r}, fallback {DEFAULT_TZ}")
        return DEFAULT_TZ


def _format_fire_at(fire_at: datetime, tz_name: str) -> str:
    """Локализованное «11.05 09:00» для подтверждения юзеру."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo(DEFAULT_TZ)
    local = fire_at.astimezone(tz)
    return local.strftime("%d.%m %H:%M")




# ──────────────────────────────────────────────────
# /reminders — moved to .list (q21 Step 1)
# ──────────────────────────────────────────────────


# Imported back for callers that still reference reminders.cmd_reminders directly.
# Public API is re-exported via the package ``__init__``.
from .list import (  # noqa: E402, F401
    _format_reminder_short,
    cmd_reminders,
    handle_reminders_list_reply,
)





