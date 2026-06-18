"""Shared helpers for tasks package (3po split).

UI rendering, keyboard builders, re-render-at-bottom machinery, ephemeral
helpers and all MSG_* confirm constants. Pure utilities + cross-cutting
helpers used across sub-modules (task_callbacks / dedup / fast_edit /
nl_edit / commands). No router, no handlers.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

# Single source of truth for the ephemeral helper lives in bot.common.
# Kept under the historic private name purely so the ~15 internal call
# sites in this package stay untouched; NOT re-exported to siblings via
# the package facade (only bot.common is the public surface).
from bot.common import send_ephemeral as _ephemeral

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────
# Confirm-сообщения (единая точка правки текста, готовность к i18n)
# ──────────────────────────────────────────────────
MSG_LIST_MERGED = "Списки объединены ✅"
MSG_ORIGINAL_UPDATED = "✅ Оригинал обновлён"
MSG_DUP_DELETED = "✅ Дубль удалён"
MSG_SAVED_NEW = "✅ Сохранено как новая закладка"
MSG_MERGE_FAILED = "Не удалось объединить. Оставлю оба списка."
MSG_UPDATE_FAILED = "Не удалось обновить. Оба сохранены."

# Per-(chat_id, bookmark_id) lock to prevent concurrent _rerender_at_bottom races.
# Locks are evicted after use when no one else is waiting.
_rerender_locks: dict[tuple[int, str], asyncio.Lock] = {}


def _get_rerender_lock(chat_id: int, bookmark_id: str) -> asyncio.Lock:
    key = (chat_id, bookmark_id)
    if key not in _rerender_locks:
        _rerender_locks[key] = asyncio.Lock()
    return _rerender_locks[key]


def _release_rerender_lock(chat_id: int, bookmark_id: str) -> None:
    key = (chat_id, bookmark_id)
    lock = _rerender_locks.get(key)
    if lock and not lock.locked():
        _rerender_locks.pop(key, None)


# ───────────────────── UI helpers ─────────────────────


# Текст списка — ЕДИНЫЙ канонический источник в shared.task_list_render
# (раньше дублировался вербатим тут и в backend/task_list_renderer.py).
# LIST_HEADER ре-экспортируется для обратной совместимости (тесты/импорты).
from shared.task_list_render import LIST_HEADER, render_task_list


def _render_text(title: str | None, structured_data: dict, silent: bool = False) -> str:
    """Тонкий делегат к каноническому рендеру (см. shared.task_list_render)."""
    return render_task_list(title, structured_data, silent=silent)


def _build_keyboard(bookmark_id: str, structured_data: dict) -> dict:
    tasks = structured_data.get("tasks", [])
    rows: list[list[dict]] = []
    for i, t in enumerate(tasks[:15]):
        check = "✅" if t.get("done") else "☐"
        text = t.get("text", "")[:40]
        rows.append([
            {"text": f"{check} {text}", "callback_data": f"tg:{bookmark_id}:{i}"},
        ])
    rows.append([
        {"text": "⏰ Срок", "callback_data": f"tldm:{bookmark_id}"},
        {"text": "🗑 Удалить", "callback_data": f"td:{bookmark_id}"},
    ])
    return {"inline_keyboard": rows}


def _list_deadline_menu(bookmark_id: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "Всё сегодня", "callback_data": f"tlds:{bookmark_id}:t"},
                {"text": "Всё завтра", "callback_data": f"tlds:{bookmark_id}:tm"},
            ],
            [
                {"text": "За неделю", "callback_data": f"tlds:{bookmark_id}:w"},
                {"text": "Убрать сроки", "callback_data": f"tlds:{bookmark_id}:n"},
            ],
            [{"text": "◀ Назад", "callback_data": f"tback:{bookmark_id}"}],
        ]
    }


def _deadline_from_code(code: str) -> str | None:
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if code == "t":
        return today.isoformat()
    if code == "tm":
        return (today + timedelta(days=1)).isoformat()
    if code == "w":
        return (today + timedelta(days=7)).isoformat()
    return None


async def _redraw(callback: CallbackQuery, bookmark: dict, store=None) -> None:
    """In-place edit (используется только для переключения подменю/назад —
    там сам список не меняется, значит таскать вниз бессмысленно).
    """
    structured = bookmark.get("structured_data") or {}
    text = _render_text(bookmark.get("title"), structured)
    keyboard = _build_keyboard(str(bookmark["id"]), structured)
    try:
        await callback.message.edit_text(
            text, reply_markup=keyboard,
            parse_mode="HTML", disable_web_page_preview=True,
        )
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            raise
    if store is not None:
        try:
            await store.bind_list_message(
                callback.message.chat.id,
                callback.message.message_id,
                str(bookmark["id"]),
            )
        except Exception as e:
            logger.debug(f"bind_list_message failed: {e}")


async def _rerender_at_bottom(
    bot, chat_id: int, old_msg_id: int, bookmark: dict, store=None,
    keep_pinned: bool = True, silent: bool = False,
) -> int:
    """Пересоздать сообщение со списком внизу чата — ЕСЛИ оно там не стоит.

    Если старое сообщение уже последнее в чате (last_seen == old_msg_id)
    — делаем обычный edit без delete+send+pin, чтобы не мерцало и не
    генерировало лишний service-pin.

    Uses per-(chat_id, bookmark_id) lock to prevent concurrent tap races.
    """
    bid = str(bookmark["id"])
    lock = _get_rerender_lock(chat_id, bid)
    async with lock:
        result = await _rerender_at_bottom_inner(
            bot, chat_id, old_msg_id, bookmark, store, keep_pinned, silent,
        )
    _release_rerender_lock(chat_id, bid)
    return result


async def _rerender_at_bottom_inner(
    bot, chat_id: int, old_msg_id: int, bookmark: dict, store=None,
    keep_pinned: bool = True, silent: bool = False,
) -> int:
    structured = bookmark.get("structured_data") or {}
    text = _render_text(bookmark.get("title"), structured, silent=silent)
    keyboard = None if silent else _build_keyboard(str(bookmark["id"]), structured)

    # Fast path: уже внизу → in-place edit
    if store is not None:
        try:
            last = await store.get_last_seen(chat_id)
            if last is not None and last <= old_msg_id:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id, message_id=old_msg_id,
                        text=text, reply_markup=keyboard,
                        parse_mode="HTML", disable_web_page_preview=True,
                    )
                    await store.bind_list_message(chat_id, old_msg_id, str(bookmark["id"]))
                    return old_msg_id
                except TelegramBadRequest as e:
                    if "not modified" in str(e):
                        return old_msg_id
                    # падаем в slow path
        except Exception as e:
            logger.debug(f"fast-path check failed: {e}")

    # Slow path: список уехал вверх — пересоздаём внизу
    new_msg = await bot.send_message(
        chat_id, text, reply_markup=keyboard,
        parse_mode="HTML", disable_web_page_preview=True,
    )

    # 2. Удалить старое
    try:
        await bot.delete_message(chat_id, old_msg_id)
    except TelegramBadRequest:
        pass

    # 3. Пин (сервисное "закрепил" удаляется через on_pin_service_message handler)
    if keep_pinned:
        try:
            await bot.pin_chat_message(
                chat_id, new_msg.message_id, disable_notification=True,
            )
        except TelegramBadRequest as e:
            logger.debug(f"pin failed: {e}")

    # 4. Redis map
    if store is not None:
        try:
            await store.unbind_list_message(chat_id, old_msg_id)
            await store.bind_list_message(
                chat_id, new_msg.message_id, str(bookmark["id"]),
            )
        except Exception as e:
            logger.debug(f"store rebind failed: {e}")

    return new_msg.message_id


def _all_tasks_done(structured_data: dict) -> bool:
    """True если список непустой и ВСЕ пункты выполнены."""
    tasks = (structured_data or {}).get("tasks", [])
    return bool(tasks) and all(t.get("done") for t in tasks)


async def _maybe_autounpin(bot, chat_id: int, msg_id: int, structured_data: dict) -> None:
    """#7: открепить сообщение списка, когда все пункты выполнены.

    Best-effort: not-pinned / устаревшее сообщение — TelegramBadRequest,
    молча игнорируем (нечего откреплять — цель уже достигнута).
    """
    if not _all_tasks_done(structured_data):
        return
    try:
        await bot.unpin_chat_message(chat_id, msg_id)
    except TelegramBadRequest as e:
        logger.debug(f"_maybe_autounpin: nothing to unpin {msg_id}: {e.message}")
    except Exception as e:
        logger.debug(f"_maybe_autounpin failed for {msg_id}: {e}")


async def _rerender_with_autounpin(
    bot, chat_id: int, old_msg_id: int, updated: dict,
    store=None, silent: bool = False,
) -> int:
    """#2 + #7: перенести список вниз свежим сообщением; если все пункты
    выполнены — не перепинивать и доснять пин с итогового сообщения.

    Единая точка для всех action-путей (toggle / fast-edit / LLM-edit),
    чтобы поведение пина не разъезжалось между ними.
    """
    structured = updated.get("structured_data") or {}
    all_done = _all_tasks_done(structured)
    new_msg_id = await _rerender_at_bottom(
        bot, chat_id, old_msg_id, updated,
        store=store, silent=silent, keep_pinned=not all_done,
    )
    if all_done:
        await _maybe_autounpin(bot, chat_id, new_msg_id, structured)
    return new_msg_id


# ───────────────────── Ephemeral helpers ─────────────────────


EPHEMERAL_DELAY = 8.0


async def send_and_autodelete(message: Message, text: str, delay: float = EPHEMERAL_DELAY) -> None:
    """Backwards-compat для других модулей."""
    await _ephemeral(message, text)


async def _delete_after(msg: Message, delay: float) -> None:
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except TelegramBadRequest:
        pass


async def _delete_after_by_id(bot, chat_id: int, msg_id: int, delay: float) -> None:
    """Удаляет сообщение по ID через delay секунд."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, msg_id)
    except TelegramBadRequest:
        pass
