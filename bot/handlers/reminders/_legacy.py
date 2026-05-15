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
# T13: Pre-AI strong intent detector (отдельный router)
# ──────────────────────────────────────────────────

# Регекс strong-маркеров — только в начале сообщения (50 первых символов).
# Высокая точность, низкий recall: лучше пропустить strong как weak (попадёт в
# обычный flow с offer'ом), чем спросить «напоминание или заметка?» где
# юзер не хотел никакого reminder'а.
_STRONG_INTENT_RE = re.compile(
    r"^\s*(надо|нужно|не\s+забыт[ьи]|срочно|обяза(тельно|н))\b",
    re.IGNORECASE,
)


def is_strong_intent(text: str) -> bool:
    """True если сообщение начинается с strong-маркера.

    Триггеры (только в начале):
      надо, нужно, не забыть/не забыти, срочно, обязательно, обязан

    NOT-trigger:
      «думаю надо как-то» (не в начале)
      «нужное направление» (полное слово другое — \\b защищает)
      «надобность» (\\b после «надо» защищает)
    """
    if not text:
        return False
    head = text[:80]  # с запасом: «не забыть» это 9 символов
    return bool(_STRONG_INTENT_RE.match(head))


# Отдельный router — регистрируется в bot/main.py ПЕРЕД start.router.
strong_router = Router()


_STRONG_PROMPT_TTL = 60 * 60  # 1 час
_STRONG_HANDLED_TTL = 5 * 60  # 5 мин для anti-double-offer flag


@strong_router.message(
    F.text
    & ~F.text.startswith("/")
    & ~F.reply_to_message
    & (F.chat.type == "private")  # защитный — на случай добавления в группы
)
async def handle_strong_intent_message(message: Message, api, store):
    """T13: ловим сообщения с strong intent ДО AI/закладки.

    Если intent сильный — показываем 3-button prompt и ставим anti-double-
    offer флажок. Worker._maybe_offer_reminder проверит флажок и не пошлёт
    weak-offer если юзер выбрал «📝 Заметка».

    Если intent НЕ сильный — `raise SkipHandler` → событие падает дальше
    на start.handle_text без изменений.
    """
    from aiogram.dispatcher.event.bases import SkipHandler

    text = (message.text or "").strip()
    if not is_strong_intent(text):
        raise SkipHandler()

    chat_id = message.chat.id

    # Pre-validation: длина, не команда, не пустота
    if len(text) < 4 or len(text) > 1000:
        raise SkipHandler()

    # 3 кнопки: 🔔 / 📝 / ✕
    buttons = {
        "inline_keyboard": [
            [
                {"text": "🔔 Напомнить", "callback_data": "rstrong_b"},
                {"text": "📝 Заметка", "callback_data": "rstrong_n"},
                {"text": "✕", "callback_data": "rstrong_x"},
            ]
        ]
    }

    try:
        prompt = await message.answer(
            "🔔 Это напоминание или заметка?",
            reply_markup=buttons,
            parse_mode=None,
        )
    except Exception as e:
        logger.warning(f"strong_intent: failed to send prompt: {e}")
        raise SkipHandler()

    if prompt is None or not getattr(prompt, "message_id", None):
        raise SkipHandler()

    # Pre-parse time из исходного текста (auto-detect).
    # Если есть — сэкономим юзеру шаг «когда?».
    # T19 приоритет: если у юзера Telegram client с Bot API 9.5 — берём
    # date_time entity напрямую (правильная локаль и таймзона). Иначе fallback
    # на текстовый парсер.
    parsed_dt_iso = None
    try:
        from bot.handlers.start import _ensure_user
        token = await _ensure_user(message, api)
        if token:
            user_tz_name = await _get_user_tz_name(api, token)
            entity_dt = extract_first_datetime_entity(message)
            if entity_dt is not None and entity_dt > datetime.now(timezone.utc):
                parsed_dt_iso = entity_dt.isoformat()
                # Не трогаем text — в payload идёт оригинал юзера. Entity offset
                # не вырезаем чтобы юзер видел «надо купить хлеб 13 мая в 9»
                # как полную фразу в reminder.
            else:
                from bot.services.nl_date import ParseStatus, parse
                split_text, split_time = _split_remind_text_and_time(text, user_tz_name)
                if split_time:
                    pr = parse(split_time, user_tz=user_tz_name)
                    if pr.status == ParseStatus.OK and pr.dt is not None:
                        parsed_dt_iso = pr.dt.isoformat()
                        text = split_text  # обрезаем время — в payload пойдёт чистый текст
    except Exception as e:
        logger.debug(f"strong_intent: pre-parse failed: {e}")

    # Сохраняем state в Redis (с capped text — H2 защита от DoS)
    state = {
        "text": _cap_text(text),
        "source_msg_id": message.message_id,
        "parsed_dt_iso": parsed_dt_iso,
    }
    try:
        await store.store_reminder_strong(chat_id, prompt.message_id, state)
    except Exception as e:
        logger.warning(f"strong_intent: failed to save state: {e}")
        # Удалим уже отправленный prompt чтобы не было broken-button
        try:
            await prompt.delete()
        except Exception:
            pass
        raise SkipHandler()


def _strong_callback_data_kind(data: str) -> str | None:
    """rstrong_b → 'remind', rstrong_n → 'note', rstrong_x → 'cancel'."""
    if data == "rstrong_b":
        return "remind"
    if data == "rstrong_n":
        return "note"
    if data == "rstrong_x":
        return "cancel"
    return None


@strong_router.callback_query(F.data.startswith("rstrong_"))
async def cb_strong_choice(callback: CallbackQuery, api, store):
    """3 callback'а strong-flow: 🔔 / 📝 / ✕."""
    from bot.handlers.start import _ensure_user

    kind = _strong_callback_data_kind(callback.data or "")
    if kind is None:
        try:
            await callback.answer()
        except Exception:
            pass
        return

    chat_id = callback.message.chat.id
    msg_id = callback.message.message_id

    # Достаём state (атомарный GETDEL через типизированный метод)
    state: dict = {}
    try:
        loaded = await store.pop_reminder_strong(chat_id, msg_id)
    except Exception as e:
        logger.warning(f"cb_strong_choice: state get failed: {e}")
        try:
            await callback.answer("Это сообщение устарело")
        except Exception:
            pass
        return

    if loaded is None:
        # Истёк TTL или второй клик
        try:
            await callback.answer("Это сообщение устарело")
            await callback.message.edit_text("⏱ Это сообщение устарело.", parse_mode=None)
        except Exception:
            pass
        return
    state = loaded

    text = state.get("text", "")
    source_msg_id = state.get("source_msg_id")
    parsed_dt_iso = state.get("parsed_dt_iso")

    if kind == "cancel":
        # ✕ — удаляем prompt, ничего не сохраняем
        try:
            await callback.message.delete()
        except Exception:
            try:
                await callback.message.edit_text("✕", parse_mode=None)
            except Exception:
                pass
        try:
            await callback.answer()
        except Exception:
            pass
        return

    token = await _ensure_user(callback, api)
    if not token:
        return

    if kind == "note":
        # 📝 — отправить в обычный AI/bookmark flow напрямую.
        # 1) Ставим anti-double-offer флажок на ИСХОДНОЕ сообщение (не prompt).
        # 2) Edit prompt в «📝 Сохраняю...» и используем его как notify-target
        #    для статуса AI обработки.
        # 3) api.create_bookmark — обычная закладка. Worker увидит флажок и
        #    не покажет offer.
        if source_msg_id is not None:
            try:
                r = await store._get()
                await r.set(
                    f"strong_handled:{chat_id}:{source_msg_id}",
                    "1",
                    ex=_STRONG_HANDLED_TTL,
                )
            except Exception as e:
                logger.warning(f"strong note: set anti-double flag failed: {e}")

        try:
            await callback.message.edit_text("📝 Сохраняю как заметку...", parse_mode=None)
        except Exception:
            pass

        try:
            await api.create_bookmark(
                token=token,
                raw_text=text,
                source="bot_forward",
                source_message_id=source_msg_id,
                notify_chat_id=chat_id,
                notify_message_id=msg_id,  # обновляем prompt-сообщение
                silent=False,  # verbose flow — чтобы edit'ы статуса работали
            )
        except Exception as e:
            logger.warning(f"strong note: create_bookmark failed: {e}")
            try:
                await callback.message.edit_text(
                    "⚠️ Не удалось обработать. Попробуй ещё раз.", parse_mode=None,
                )
            except Exception:
                pass

        try:
            await callback.answer()
        except Exception:
            pass
        return

    # kind == "remind"
    # Если время уже распознано → создаём reminder сразу
    if parsed_dt_iso:
        try:
            await api.create_reminder(
                token, parsed_dt_iso,
                bookmark_id=None,
                payload={"text": text, "source": "strong_intent"},
            )
        except Exception as e:
            logger.warning(f"strong remind auto-create failed: {e}")
            try:
                await callback.message.edit_text(
                    "⚠️ Не получилось. Попробуй ещё раз.", parse_mode=None,
                )
            except Exception:
                pass
            try:
                await callback.answer()
            except Exception:
                pass
            return

        from datetime import datetime
        try:
            dt = datetime.fromisoformat(parsed_dt_iso)
            user_tz_name = await _get_user_tz_name(api, token)
            when = _format_fire_at(dt, user_tz_name)
        except Exception:
            when = parsed_dt_iso
        try:
            await callback.message.edit_text(
                f"🔔 Напомню <b>{_safe(when)}</b> — «{_safe(text)}»", parse_mode="HTML",
            )
        except Exception:
            pass
        try:
            await callback.answer("Готово")
        except Exception:
            pass
        return

    # Времени нет → просим reply со временем (используя explicit-marker)
    try:
        new_prompt = await callback.message.edit_text(
            _reply_prompt(f"🔔 Когда напомнить «<b>{_safe(text)}</b>»?"),
            parse_mode="HTML",
        )
    except Exception:
        new_prompt = None

    target_msg_id = (
        new_prompt.message_id if new_prompt and getattr(new_prompt, "message_id", None)
        else msg_id
    )
    state_saved = False
    try:
        await store.store_reminder_pending_explicit(
            chat_id, target_msg_id, _cap_text(text),
        )
        state_saved = True
        logger.info(
            f"strong remind: pending saved chat={chat_id} msg={target_msg_id} "
            f"text={_cap_text(text, limit=40)!r}"
        )
    except Exception as e:
        logger.warning(f"strong remind: failed to save pending: {e}")

    if not state_saved:
        # State не сохранился — reply юзера потом упадёт в «устарело».
        # Лучше сразу честно сказать что не получилось.
        try:
            await callback.message.edit_text(
                "⚠️ Не получилось подготовить ожидание. Попробуй "
                "<code>/remind &lt;текст&gt; &lt;когда&gt;</code>.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        try:
            await callback.answer("Ошибка")
        except Exception:
            pass
        return

    try:
        await callback.answer("Жду время")
    except Exception:
        pass



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





