"""Task-list inline-button callbacks (3po split).

Toggle task, deadline menu, deadline set, back, delete-list, legacy
"not a list", and the pinned-service-message cleaner. Owns its own Router.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from .shared import (
    _build_keyboard,
    _deadline_from_code,
    _list_deadline_menu,
    _redraw,
    _render_text,
    _rerender_at_bottom,
)

logger = logging.getLogger(__name__)

router = Router()


# ───────────────────── Callback: toggle task ─────────────────────


@router.callback_query(F.data.startswith("tg:"))
async def cb_toggle_task(callback: CallbackQuery, api, store=None):
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return

    from bot.handlers.start import _ensure_user
    token = await _ensure_user(callback, api)
    if not token:
        return

    _, bid, idx_str = callback.data.split(":")
    idx = int(idx_str)

    try:
        bookmark = await api.get_bookmark(token, bid)
    except Exception:
        await callback.answer("Ошибка", show_alert=True)
        return

    structured = bookmark.get("structured_data") or {}
    tasks = structured.get("tasks", [])
    if idx < 0 or idx >= len(tasks):
        await callback.answer()
        return

    tasks[idx]["done"] = not tasks[idx].get("done", False)
    structured["tasks"] = tasks

    try:
        updated = await api.update_bookmark(token, bid, {"structured_data": structured})
    except Exception:
        await callback.answer("Ошибка", show_alert=True)
        return

    # Перенести список вниз как свежее сообщение
    await _rerender_at_bottom(
        callback.message.bot,
        callback.message.chat.id,
        callback.message.message_id,
        updated, store=store,
    )
    await callback.answer()


# ───────────────────── Callback: deadline menu ─────────────────────


@router.callback_query(F.data.startswith("tldm:"))
async def cb_list_deadline_menu(callback: CallbackQuery):
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return

    _, bid = callback.data.split(":")
    try:
        await callback.message.edit_reply_markup(reply_markup=_list_deadline_menu(bid))
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("tlds:"))
async def cb_list_deadline_set(callback: CallbackQuery, api, store=None):
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return

    from bot.handlers.start import _ensure_user
    token = await _ensure_user(callback, api)
    if not token:
        return

    _, bid, code = callback.data.split(":")
    deadline = _deadline_from_code(code)

    try:
        bookmark = await api.get_bookmark(token, bid)
    except Exception:
        await callback.answer("Ошибка", show_alert=True)
        return

    structured = bookmark.get("structured_data") or {}
    if deadline is None:
        structured.pop("common_deadline", None)
    else:
        structured["common_deadline"] = deadline

    try:
        updated = await api.update_bookmark(token, bid, {"structured_data": structured})
    except Exception:
        await callback.answer("Ошибка", show_alert=True)
        return

    await _rerender_at_bottom(
        callback.message.bot,
        callback.message.chat.id,
        callback.message.message_id,
        updated, store=store,
    )
    await callback.answer("Готово" if deadline else "Сроки убраны")


@router.callback_query(F.data.startswith("tback:"))
async def cb_back(callback: CallbackQuery, api, store=None):
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return

    from bot.handlers.start import _ensure_user
    token = await _ensure_user(callback, api)
    if not token:
        return

    _, bid = callback.data.split(":")
    try:
        bookmark = await api.get_bookmark(token, bid)
    except Exception:
        await callback.answer("Ошибка", show_alert=True)
        return
    await _redraw(callback, bookmark, store=store)
    await callback.answer()


# ───────────────────── Callback: delete entire list ─────────────────────


@router.callback_query(F.data.startswith("td:"))
async def cb_delete_list(callback: CallbackQuery, api, store=None):
    """🗑 — удалить список полностью: bookmark + сообщение бота + unpin."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return

    from bot.handlers.start import _ensure_user
    token = await _ensure_user(callback, api)
    if not token:
        return

    _, bid = callback.data.split(":")

    # Сначала unpin (иначе сообщение нельзя удалить если оно pinned с restrict)
    try:
        await callback.message.unpin()
    except TelegramBadRequest:
        pass

    # Удаляем bookmark в БД
    try:
        await api.delete_bookmark(token, bid)
    except Exception as e:
        logger.error(f"delete_bookmark failed: {e}")

    # Удаляем сообщение из чата
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        # Если старше 48ч — Telegram не даст удалить, просто очистим
        try:
            await callback.message.edit_text(
                "🗑 Удалён", parse_mode=None, reply_markup=None,
            )
        except TelegramBadRequest:
            pass

    # Чистим map
    if store is not None:
        try:
            await store.unbind_list_message(
                callback.message.chat.id, callback.message.message_id,
            )
        except Exception:
            pass

    await callback.answer("Удалено")


# ───────────────────── Callback: legacy "not a list" ─────────────────────


@router.callback_query(F.data.startswith("tn:"))
async def cb_not_a_list(callback: CallbackQuery, api):
    """Legacy — старые сообщения могут иметь эту кнопку. Откатывает к обычной закладке."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return

    from bot.handlers.start import _ensure_user
    token = await _ensure_user(callback, api)
    if not token:
        return

    _, bid = callback.data.split(":")
    try:
        bookmark = await api.update_bookmark(token, bid, {"structured_data": None})
    except Exception:
        await callback.answer("Ошибка", show_alert=True)
        return

    try:
        await callback.message.unpin()
    except TelegramBadRequest:
        pass

    title = bookmark.get("title") or "Закладка"
    summary = bookmark.get("summary") or ""
    lines = [f"✅ <b>{title}</b>"]
    if bookmark.get("category"):
        lines.append(f"Категория: {bookmark['category']}")
    if summary:
        lines.append(summary[:200])

    buttons = {"inline_keyboard": [[
        {"text": "📖 Открыть", "callback_data": f"view:{bid}"},
        {"text": "🗑 Удалить", "callback_data": f"del:{bid}"},
    ]]}
    try:
        await callback.message.edit_text(
            "\n".join(lines), reply_markup=buttons,
            parse_mode="HTML", disable_web_page_preview=True,
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


# ───────────────────── Service messages: чистим "закрепил" ─────────────────────


@router.message(F.pinned_message)
async def on_pin_service_message(message: Message, store=None):
    """Сервисное "note_bot закрепил(а) …" — удаляем, чтобы не засоряло чат.

    Чистим только для НАШИХ task_list (проверяем через Redis-map).
    Пины, которые поставил кто-то другой (или будущие фичи) — не трогаем.
    """
    pinned = message.pinned_message
    if not pinned or store is None:
        return
    bid = await store.get_list_bookmark(message.chat.id, pinned.message_id)
    if not bid:
        return
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
