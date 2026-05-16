"""T13 strong-intent flow — 3-button «🔔 Напомнить / 📝 Заметка / ✕» (q21 Step 5).

This sub-module owns the SEPARATE ``strong_router``, NOT the main package router.
``strong_router`` is registered in ``bot/main.py`` BEFORE ``start.router`` so it
can intercept strong-intent messages ahead of the regular text flow.

Public API (re-exported via package ``__init__``):
- ``strong_router`` — the Router (kept as ``strong_router`` for bot/main.py compat)
- ``is_strong_intent`` — pure regex check
- ``handle_strong_intent_message`` — message handler
- ``cb_strong_choice`` — callback handler
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.common import format_fire_at, get_user_tz_name, safe, split_remind_text_and_time

from .shared import (
    _cap_text,
    _reply_prompt,
    extract_first_datetime_entity,
)

logger = logging.getLogger(__name__)


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
    parsed_dt_iso = None
    try:
        from bot.common.auth import ensure_user
        token = await ensure_user(message, api)
        if token:
            user_tz_name = await get_user_tz_name(api, token)
            entity_dt = extract_first_datetime_entity(message)
            if entity_dt is not None and entity_dt > datetime.now(timezone.utc):
                parsed_dt_iso = entity_dt.isoformat()
            else:
                from bot.services.nl_date import ParseStatus, parse
                split_text, split_time = split_remind_text_and_time(text, user_tz_name)
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
    from bot.common.auth import ensure_user

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

    token = await ensure_user(callback, api)
    if not token:
        return

    if kind == "note":
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

        try:
            dt = datetime.fromisoformat(parsed_dt_iso)
            user_tz_name = await get_user_tz_name(api, token)
            when = format_fire_at(dt, user_tz_name)
        except Exception:
            when = parsed_dt_iso
        try:
            await callback.message.edit_text(
                f"🔔 Напомню <b>{safe(when)}</b> — «{safe(text)}»", parse_mode="HTML",
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
            _reply_prompt(f"🔔 Когда напомнить «<b>{safe(text)}</b>»?"),
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
