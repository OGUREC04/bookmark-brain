"""Конвертация заметки-дубля в список / напоминание после «сохрани как новую».

Контекст (c6ti): near-dup алерт показывается ТОЛЬКО для простых заметок —
списки и напоминания его пропускают (см. processing.py:_is_task_list_early /
_reminder_intent_early). Поэтому «сохрани как новую» всегда давало заметку,
а выбрать тип было негде. Эти две кнопки на подтверждении save_new закрывают
дырку:

  d2l:{bid} — превратить заметку в task_list
  d2r:{bid} — поставить напоминание на текст заметки (спросит «Когда?»)

Кнопки НЕобязательные: не нажал → осталась заметка (дефолт, как было).
Owns its own Router (нативный aiogram include_router из tasks/__init__.py).
"""
from __future__ import annotations

import logging
from uuid import UUID

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from bot.common import TIME_EXAMPLES
from shared.messages import compose, reply_hint_full

logger = logging.getLogger(__name__)

router = Router()


# Промпт «пришли пункты» — когда текст заметки одна фраза без выделяемых
# пунктов (вариант (а): спрашиваем пункты явно, а не клонируем заголовок).
_ASK_ITEMS = compose(
    reply_hint_full(action="прислать пункты списка"),
    "📋 Пришли пункты — по одному на строку или через запятую.",
)

# Промпт «Когда напомнить?» — строим локально из shared.messages + bot.common
# (НЕ импортируем reminders._reply_prompt: feature-пакеты независимы, см.
# import-linter contract). «Когда напомнить» в тексте важно — это fallback
# stale-state detection в reminders/reply.py. reply на него ловит обычный
# reminder-reply флоу через reminder_pending kind=bookmark.
_ASK_TIME = compose(reply_hint_full(), "🔔 Когда напомнить?", TIME_EXAMPLES)


def _is_valid_uuid(s: str | None) -> bool:
    if not s:
        return False
    try:
        UUID(s)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def saved_new_keyboard(bookmark_id: str) -> dict:
    """Кнопки выбора типа на подтверждении «сохрани как новую» (dedup-заметка)."""
    return {"inline_keyboard": [[
        {"text": "📋 Сделать списком", "callback_data": f"d2l:{bookmark_id}"},
        {"text": "🔔 Напоминание", "callback_data": f"d2r:{bookmark_id}"},
    ]]}


async def _materialize_list(bot, chat_id: int, token: str, api, store, bid: str, user_id: int) -> None:
    """Отрендерить + запинить только что структурированный список."""
    from bot.handlers.settings import is_silent

    from .confirm import _create_and_pin_task_list
    silent = await is_silent(api, token, user_id)
    await _create_and_pin_task_list(
        bot, chat_id, token, api, store, bid, silent=silent,
    )


@router.callback_query(F.data.startswith("d2l:"))
async def cb_convert_to_list(callback: CallbackQuery, api, store):
    """📋 Сделать списком — структурируем текст заметки и пиним список."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return
    bid = callback.data.split(":", 1)[1] if callback.data and ":" in callback.data else ""
    if not _is_valid_uuid(bid):
        await callback.answer("Странный id, попробуй заново")
        return

    from bot.common.auth import ensure_user
    token = await ensure_user(callback, api)
    if not token:
        await callback.answer("Не получилось авторизоваться")
        return

    if callback.from_user is None:
        await callback.answer("Не удалось определить пользователя")
        return
    chat_id = callback.message.chat.id
    try:
        resp = await api.structure_as_list(token, bid)
    except Exception as e:
        logger.warning(f"cb_convert_to_list: structure_as_list failed: {e}")
        await callback.answer("Не получилось сделать список")
        return

    if resp.get("structured"):
        await _materialize_list(
            callback.message.bot, chat_id, token, api, store, bid,
            callback.from_user.id,
        )
        try:
            await callback.message.edit_text("📋 Готово — список создан.", reply_markup=None)
        except TelegramBadRequest:
            pass
        await callback.answer("Список создан")
        return

    # single_phrase / empty — спрашиваем пункты явно (вариант (а)).
    try:
        await callback.message.edit_text(_ASK_ITEMS, parse_mode="HTML", reply_markup=None)
    except TelegramBadRequest:
        pass
    try:
        await store.store_convert_list_pending(chat_id, callback.message.message_id, bid)
    except Exception as e:
        logger.warning(f"cb_convert_to_list: store pending failed: {e}")
    await callback.answer()


@router.callback_query(F.data.startswith("d2r:"))
async def cb_convert_to_reminder(callback: CallbackQuery, api, store):
    """🔔 Напоминание — спрашиваем время, текст берём из заметки."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return
    bid = callback.data.split(":", 1)[1] if callback.data and ":" in callback.data else ""
    if not _is_valid_uuid(bid):
        await callback.answer("Странный id, попробуй заново")
        return

    from bot.common.auth import ensure_user
    token = await ensure_user(callback, api)
    if not token:
        await callback.answer("Не получилось авторизоваться")
        return

    chat_id = callback.message.chat.id
    # Снимаем кнопки с подтверждения — заметка сохранена, тип выбран.
    try:
        await callback.message.edit_text("✅ Сохранено как новая заметка", reply_markup=None)
    except TelegramBadRequest:
        pass

    # Промпт «Когда напомнить?» отдельным сообщением — reply на него ловит
    # существующий reminder-reply флоу (kind=bookmark → текст из закладки).
    prompt = await callback.message.answer(_ASK_TIME, parse_mode="HTML")
    if prompt is not None and getattr(prompt, "message_id", None) is not None:
        try:
            await store.restore_reminder_pending(
                chat_id, prompt.message_id,
                {"kind": "bookmark", "bookmark_id": bid},
            )
        except Exception as e:
            logger.warning(f"cb_convert_to_reminder: store pending failed: {e}")
    await callback.answer()


async def handle_convert_list_reply(message: Message, api, store) -> bool:
    """Reply с пунктами на промпт «пришли пункты» (single-phrase ветка d2l).

    Возвращает True если reply относится к convert-list флоу (обработан).
    False — этот reply нас не касается, идёт дальше по диспетчеру.
    """
    rt = message.reply_to_message
    if rt is None:
        return False
    chat_id = message.chat.id
    try:
        bid = await store.pop_convert_list_pending(chat_id, rt.message_id)
    except Exception as e:
        logger.debug(f"handle_convert_list_reply: pop failed: {e}")
        return False
    if not bid:
        return False

    from bot.common.auth import ensure_user
    token = await ensure_user(message, api)
    if not token:
        await message.answer("⚠️ Не удалось авторизоваться. Попробуй ещё раз.")
        return True
    if message.from_user is None:
        return True

    text = (message.text or "").strip()
    if not text:
        # Пустой reply — переспрашиваем, кладём pending обратно под тот же промпт.
        try:
            await store.store_convert_list_pending(chat_id, rt.message_id, bid)
        except Exception as e:
            logger.debug(f"handle_convert_list_reply: re-store failed: {e}")
        await message.answer(_ASK_ITEMS, parse_mode="HTML")
        return True

    try:
        # allow_single: юзер прислал пункты сам — принимаем даже один.
        resp = await api.structure_as_list(token, bid, text=text, allow_single=True)
    except Exception as e:
        logger.warning(f"handle_convert_list_reply: structure failed: {e}")
        await message.answer("Не получилось сделать список — попробуй ещё раз.")
        return True

    if not resp.get("structured"):
        await message.answer(_ASK_ITEMS, parse_mode="HTML")
        try:
            await store.store_convert_list_pending(chat_id, rt.message_id, bid)
        except Exception as e:
            logger.debug(f"handle_convert_list_reply: re-store (single) failed: {e}")
        return True

    await _materialize_list(
        message.bot, chat_id, token, api, store, bid, message.from_user.id,
    )
    # Чистим промпт «пришли пункты» и reply юзера — список сам себе фидбэк.
    for mid in (rt.message_id, message.message_id):
        try:
            await message.bot.delete_message(chat_id, mid)
        except TelegramBadRequest:
            pass
    return True


@router.message(
    F.reply_to_message & F.reply_to_message.from_user.is_bot
    & F.text & ~F.text.startswith("/")
)
async def _convert_reply_dispatch(message: Message, api, store):
    """Reply-перехват для convert-list (свой Redis-ключ convert_list_pending).

    Живёт в tasks-роутере (а не в reminders/reply.py) — feature-пакеты
    независимы (import-linter). Не наш reply → SkipHandler, событие падает
    дальше на остальные reply-обработчики tasks (nl_edit и т.д.).
    """
    from aiogram.dispatcher.event.bases import SkipHandler

    handled = await handle_convert_list_reply(message, api, store)
    if handled:
        return
    raise SkipHandler()
