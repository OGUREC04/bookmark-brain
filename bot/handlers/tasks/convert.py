"""Конвертация заметки-дубля в список / напоминание после «сохрани как новую».

Контекст (c6ti): near-dup алерт показывается ТОЛЬКО для простых заметок —
списки и напоминания его пропускают (см. processing.py:_is_task_list_early /
_reminder_intent_early). Поэтому «сохрани как новую» всегда давало заметку, а
выбрать тип было негде. Две НЕобязательные кнопки на подтверждении save_new:

  d2l:{bid} — превратить заметку в task_list (из её же текста, сразу)
  d2r:{bid} — поставить напоминание на текст заметки (спросит «Когда?»)

Не нажал → осталась заметка (дефолт). Own Router (include из tasks/__init__.py).
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


async def _materialize_list(
    bot, chat_id: int, token: str, api, store, bid: str, user_id: int,
) -> None:
    """Отрендерить + запинить только что структурированный список."""
    from bot.handlers.settings import is_silent

    from .confirm import _create_and_pin_task_list
    silent = await is_silent(api, token, user_id)
    await _create_and_pin_task_list(
        bot, chat_id, token, api, store, bid, silent=silent,
    )


@router.callback_query(F.data.startswith("d2l:"))
async def cb_convert_to_list(callback: CallbackQuery, api, store):
    """📋 Сделать списком — структурируем текст заметки и пиним список СРАЗУ.

    Текст уже отправлен юзером, поэтому не переспрашиваем пункты: текст с
    несколькими пунктами → список из них; фраза-заголовок → список из 1 пункта
    (allow_single), дальше растишь через «добавь …».
    """
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
    # Анти-двойной-тап: оптимистично снимаем кнопки. Второй тап придёт на уже
    # отредактированное сообщение → "not modified" → выходим (иначе два
    # запинённых списка).
    try:
        await callback.message.edit_text("⏳ Делаю список…", reply_markup=None)
    except TelegramBadRequest as e:
        if "not modified" in str(e).lower() or "not found" in str(e).lower():
            await callback.answer()
            return

    try:
        # allow_single: фраза-заголовок → 1-пунктовый список, без переспроса.
        resp = await api.structure_as_list(token, bid, allow_single=True)
    except Exception as e:
        logger.warning(f"cb_convert_to_list: structure_as_list failed: {e}")
        await callback.answer("Не получилось сделать список")
        return

    if not resp.get("structured"):
        # Сюда дойдёт только пустой текст заметки.
        try:
            await callback.message.edit_text("✅ Сохранено как новая заметка")
        except TelegramBadRequest:
            pass
        await callback.answer("Пустая заметка — нечего в список")
        return

    try:
        await _materialize_list(
            callback.message.bot, chat_id, token, api, store, bid,
            callback.from_user.id,
        )
    except Exception as e:
        # structured_data уже выставлен бэкендом — список есть в БД, но
        # рендер/пин упал. Не оставляем сообщение залипшим на «⏳».
        logger.warning(f"cb_convert_to_list: materialize failed: {e}")
        try:
            await callback.message.edit_text("✅ Сохранено как новая заметка")
        except TelegramBadRequest:
            pass
        await callback.answer("Не получилось показать список — он сохранён, см. /list")
        return
    try:
        await callback.message.edit_text("📋 Готово — список создан.")
    except TelegramBadRequest:
        pass
    await callback.answer("Список создан")


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
    # Анти-двойной-тап: второй тап → "not modified" → выходим (без 2-го промпта).
    try:
        await callback.message.edit_text("✅ Сохранено как новая заметка", reply_markup=None)
    except TelegramBadRequest as e:
        if "not modified" in str(e).lower():
            await callback.answer()
            return

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
