"""Shared helpers for reminders package (q21 Step 6 — renamed from _legacy.py).

Pure utilities and constants used across sub-modules
(list / explicit / callbacks / reply / strong). No router, no handlers.

Redis-key conventions (set by worker, read by bot):
  reminder_pending:{chat_id}:{msg_id} → bookmark_id (TTL 1ч)
  reminder:{chat_id}:{msg_id}         → reminder_id (TTL 25ч)
  reminder_snooze:{chat_id}:{msg_id}  → reminder_id (TTL 1ч)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

# Cross-package shared infra lives in bot.common (single source of truth).
# Imported under their PUBLIC names — bot.common is the only public surface
# for these helpers; this package re-exports nothing of them via its facade.
from bot.common import DEFAULT_TZ, TIME_EXAMPLES, safe
from shared.messages import compose, reply_hint_full

logger = logging.getLogger(__name__)

# Безопасные лимиты на пользовательский текст перед записью в Redis.
# Защита от DoS-наполнения памяти Redis (H2 из security review).
MAX_REMINDER_TEXT_LEN = 500
# Максимальная длина reply-текста перед передачей в dateparser (M2 защитный).
MAX_PARSE_INPUT_LEN = 200


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
    deduplicated: bool = False,
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

    # E15: на дубле (тот же текст+минута) бэкенд вернул существующее
    # напоминание — пишем «👌 Уже напомню…», чтобы юзер понял что нового
    # будильника не появилось (а не подумал что наплодил дублей).
    prefix = "👌 Уже напомню" if deduplicated else "🔔 Напомню"
    await message.answer(
        f"{prefix} <b>{safe(formatted_full)}</b> — «{safe(short_text)}»",
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

async def _purge_reminder_dialog(
    bot, chat_id: int, anchor: int, store,
    *, extra_msg_ids=None, keep_msg_id: int | None = None,
) -> None:
    """Единая очистка reminder-диалога на терминале (создано/продлено/устарело).

    Удаляет ВСЕ эфемерные сообщения якоря (prompt'ы бота + reply'и юзера) +
    ``extra_msg_ids`` (обычно последний reply юзера), кроме ``keep_msg_id``
    (сообщение, которое через edit_text САМО стало подтверждением — strong-flow).

    Best-effort: ошибки удаления (сообщение уже удалено / старше 48ч / нет прав)
    проглатываются — очистка не должна ронять подтверждение. Точное зеркало
    `_cleanup_failed_attempts` (tasks/nl_edit.py). Боты могут удалять и свои, и
    входящие сообщения в private chat (<48ч) — паттерн уже в проде.

    ``bot`` (а не message) — чтобы вызывать из callback'ов (callback.message.bot).
    """
    try:
        ids = await store.pop_reminder_ephemeral(chat_id, anchor)
    except Exception as e:
        logger.debug(f"_purge_reminder_dialog pop failed: {e}")
        ids = []
    # Сам anchor (prompt бота «Когда напомнить?») тоже удаляем — это половина
    # того, что юзер хочет убрать. keep_msg_id защищает кейсы, где anchor обязан
    # выжить: snapshot /reminders (для следующей команды) и strong-морф,
    # ставший подтверждением (edit_text сохранил тот же id).
    ids = [anchor] + list(ids)
    if extra_msg_ids:
        ids = ids + list(extra_msg_ids)
    if keep_msg_id is not None:
        ids = [i for i in ids if i != keep_msg_id]
    for mid in dict.fromkeys(ids):  # dedupe, сохраняя порядок
        try:
            await bot.delete_message(chat_id, mid)
        except TelegramBadRequest:
            pass  # уже удалено / старше 48ч / нельзя удалить
        except Exception as e:
            logger.debug(f"_purge_reminder_dialog delete {mid} failed: {e}")


def _reply_prompt(question: str, examples: str = TIME_EXAMPLES) -> str:
    """Унифицированный текст prompt'а для ввода времени через reply.

    UX: Reply подсвечено максимально явно — отдельная строка с ↩️ + жирный
    текст + конкретный пример. Без этого юзеры шлют next-message вместо
    reply и попадают в catch-all → save_yes/no → «Не сохраняю».
    См. bookmark-brain-4dr.

    ``examples`` — TIME_EXAMPLES (дата+час) по умолчанию; для вопроса
    «во сколько?» (дата уже известна) передавай HOUR_EXAMPLES; None — не
    показывать примеры (например вопрос «про что?» — ответ это текст).
    """
    # КАНОН-порядок: reply-подсказка ПЕРВОЙ (самой заметной), потом вопрос,
    # потом примеры. Единый стиль reply — из shared.messages (один на весь бот).
    return compose(reply_hint_full(), question, examples or None)











