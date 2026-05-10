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

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)

router = Router()

# Часовой пояс по умолчанию — если у юзера в users.timezone пусто или
# зона не распарсилась.
DEFAULT_TZ = "Europe/Moscow"

# Подсказка с примерами для reply'я (используется в rsk: и rsnz:)
TIME_EXAMPLES = (
    "Примеры:\n"
    "• <code>через час</code>\n"
    "• <code>завтра в 9</code>\n"
    "• <code>в субботу в 18</code>\n"
    "• <code>15 мая</code>"
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
# Callbacks
# ──────────────────────────────────────────────────


@router.callback_query(F.data.startswith("rsk:"))
async def cb_create_reminder(callback: CallbackQuery, api, store):
    """Юзер нажал «🔔 Создать напоминание?» — просим reply со временем.

    Bookmark_id мы НЕ берём из callback_data (хотя он там есть) — берём
    из Redis-ключа `reminder_pending:{chat_id}:{msg_id}` который ставит
    worker. Так не зависим от целостности callback_data.
    """
    chat_id = callback.message.chat.id
    msg_id = callback.message.message_id

    try:
        await callback.message.edit_text(
            "Когда напомнить? <b>Ответь reply</b> на это сообщение со временем.\n\n"
            f"{TIME_EXAMPLES}",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.debug(f"cb_create_reminder: edit_text failed: {e}")
    # Redis key (reminder_pending:...) уже стоит — worker его поставил.
    # TTL 1ч хватит на ответ.
    try:
        await callback.answer("Жду время")
    except Exception:
        pass


@router.callback_query(F.data.startswith("rsn:"))
async def cb_dismiss_reminder(callback: CallbackQuery, api, store):
    """Юзер отказался от напоминания — убираем кнопки, чистим state."""
    chat_id = callback.message.chat.id
    msg_id = callback.message.message_id

    try:
        await callback.message.edit_text(
            "Окей, без напоминания.",
            parse_mode=None,
        )
    except Exception as e:
        logger.debug(f"cb_dismiss_reminder: edit_text failed: {e}")
    try:
        await store.delete_reminder_pending(chat_id, msg_id)
    except Exception as e:
        logger.debug(f"cb_dismiss_reminder: delete state failed: {e}")
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("rdone:"))
async def cb_done_reminder(callback: CallbackQuery, api, store):
    """«✅ Выполнено» на отправленном reminder — DELETE через API
    (status='cancelled') + edit message без кнопок."""
    from bot.handlers.start import _ensure_user

    chat_id = callback.message.chat.id
    msg_id = callback.message.message_id
    reminder_id = (callback.data or "").split(":", 1)[1] if ":" in (callback.data or "") else ""

    token = await _ensure_user(callback, api)
    if not token:
        return

    try:
        await api.cancel_reminder(token, reminder_id)
    except httpx.HTTPStatusError as e:
        # 404 — уже удалён (например auto_done или второй клик). Не палимся.
        if e.response.status_code != 404:
            logger.warning(f"cb_done_reminder: cancel failed: {e}")
    except Exception as e:
        logger.warning(f"cb_done_reminder: cancel failed: {e}")

    try:
        await callback.message.edit_text(
            "✅ Выполнено",
            parse_mode=None,
        )
    except Exception as e:
        logger.debug(f"cb_done_reminder: edit_text failed: {e}")
    try:
        await store.delete_reminder_id(chat_id, msg_id)
    except Exception as e:
        logger.debug(f"cb_done_reminder: delete state failed: {e}")
    try:
        await callback.answer("Готово")
    except Exception:
        pass


@router.callback_query(F.data.startswith("rsnz:"))
async def cb_snooze_reminder(callback: CallbackQuery, api, store):
    """«💤 Продлить» — сохраняем reminder_id в snooze-state, просим
    новое время через reply."""
    chat_id = callback.message.chat.id
    msg_id = callback.message.message_id
    reminder_id = (callback.data or "").split(":", 1)[1] if ":" in (callback.data or "") else ""

    if reminder_id:
        try:
            await store.store_reminder_snooze(chat_id, msg_id, reminder_id)
        except Exception as e:
            logger.warning(f"cb_snooze_reminder: store_snooze failed: {e}")

    try:
        await callback.message.edit_text(
            "💤 На сколько продлить? <b>Ответь reply</b> со временем.\n\n"
            f"{TIME_EXAMPLES}",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.debug(f"cb_snooze_reminder: edit_text failed: {e}")
    try:
        await callback.answer()
    except Exception:
        pass


# ──────────────────────────────────────────────────
# Reply-handler — парсинг времени
# ──────────────────────────────────────────────────


async def handle_reminder_reply(message: Message, api, store) -> bool:
    """Обработка reply'я когда чат ждёт время от юзера.

    Возвращает True если reply распознан как reminder-related (не важно
    успешно или с ошибкой — просто чтобы вызывающий код не передавал в
    catch-all). False — этот reply нас не касается.
    """
    rt = message.reply_to_message
    if rt is None:
        return False

    chat_id = message.chat.id
    reply_to_id = rt.message_id

    # Snooze в приоритете: это активный reminder с уже сохранённым reminder_id.
    snooze_rid = None
    try:
        snooze_rid = await store.pop_reminder_snooze(chat_id, reply_to_id)
    except Exception as e:
        logger.debug(f"handle_reminder_reply: pop_snooze failed: {e}")

    pending_bid = None
    if not snooze_rid:
        try:
            pending_bid = await store.pop_reminder_pending(chat_id, reply_to_id)
        except Exception as e:
            logger.debug(f"handle_reminder_reply: pop_pending failed: {e}")

    if not snooze_rid and not pending_bid:
        return False  # reply не наш

    from bot.handlers.start import _ensure_user

    token = await _ensure_user(message, api)
    if not token:
        return True  # наш reply, но без токена — просто молча выйти

    text = (message.text or "").strip()
    if not text:
        await message.answer(
            "Не понял время. " + TIME_EXAMPLES, parse_mode="HTML",
        )
        return True

    # Парсер живёт в backend/app/services/nl_date.py.
    # Оба процесса (bot, worker) импортируют его одинаково.
    from backend.app.services.nl_date import ParseStatus, parse

    user_tz_name = await _get_user_tz_name(api, token)
    result = parse(text, user_tz=user_tz_name)

    if result.status == ParseStatus.UNPARSEABLE:
        await message.answer(
            "Не понял время. " + TIME_EXAMPLES, parse_mode="HTML",
        )
        return True
    if result.status == ParseStatus.IN_PAST:
        await message.answer(
            "Это в прошлом. Назначь время в будущем.",
            parse_mode=None,
        )
        return True
    if result.status == ParseStatus.NEEDS_TIME:
        await message.answer(
            "Уточни время (например «в 9» или «в 18:30»). " + TIME_EXAMPLES,
            parse_mode="HTML",
        )
        return True

    # OK или FALLBACK_DEFAULT — у нас валидный datetime
    if result.dt is None:
        await message.answer(
            "Не понял время. " + TIME_EXAMPLES, parse_mode="HTML",
        )
        return True

    fire_at_iso = result.dt.isoformat()

    if snooze_rid:
        try:
            await api.update_reminder(token, snooze_rid, fire_at_iso)
        except httpx.HTTPStatusError as e:
            logger.warning(f"update_reminder failed: {e}")
            await message.answer(
                "Не получилось продлить — попробуй ещё раз.",
                parse_mode=None,
            )
            return True
        except Exception as e:
            logger.warning(f"update_reminder failed: {e}")
            await message.answer("Не получилось продлить.", parse_mode=None)
            return True

        await message.answer(
            f"💤 Продлено до <b>{_format_fire_at(result.dt, user_tz_name)}</b>",
            parse_mode="HTML",
        )
        return True

    # pending_bid — создание нового reminder
    try:
        await api.create_reminder(
            token,
            fire_at_iso,
            bookmark_id=pending_bid,
            payload={"text": text},
        )
    except httpx.HTTPStatusError as e:
        logger.warning(f"create_reminder failed: {e}")
        await message.answer(
            "Не получилось создать напоминание — попробуй ещё раз.",
            parse_mode=None,
        )
        return True
    except Exception as e:
        logger.warning(f"create_reminder failed: {e}")
        await message.answer("Не получилось создать напоминание.", parse_mode=None)
        return True

    await message.answer(
        f"🔔 Напомню <b>{_format_fire_at(result.dt, user_tz_name)}</b>",
        parse_mode="HTML",
    )
    return True


# ──────────────────────────────────────────────────
# Router-level message hook
# ──────────────────────────────────────────────────


@router.message(F.reply_to_message & F.text & ~F.text.startswith("/"))
async def _reply_dispatch(message: Message, api, store):
    """Перехватываем reply ДО tasks/start. Если это reminder-reply —
    обработали и возвращаемся. Иначе `raise SkipHandler`, чтобы aiogram
    передал событие следующему router'у (tasks → ... → start catch-all).
    """
    from aiogram.dispatcher.event.bases import SkipHandler

    handled = await handle_reminder_reply(message, api, store)
    if handled:
        return
    raise SkipHandler()
