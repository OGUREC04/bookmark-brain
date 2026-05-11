"""Обработчики task_list.

Минималистичный UX — одна кнопка-toggle на задачу + ряд действий
[⏰ Срок] [🗑 Удалить]. Всё остальное (добавить / удалить / переименовать /
проставить deadline / добавить описание) — через **reply на сообщение со
списком** свободной фразой. LLM применяет изменения.

Callback схема (лимит 64 байта):
  tg:{id}:{idx}   — toggle одной задачи
  tldm:{id}       — меню сроков (для всего списка)
  tlds:{id}:{c}   — установить срок всему списку (t/tm/w/n)
  tback:{id}      — вернуться из подменю
  td:{id}         — удалить весь список (bookmark + сообщение бота)
  tn:{id}         — (legacy) "не список" — откатить к обычной закладке
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)

router = Router()

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


HINT_LINE = "💬 <i>Ответь на это сообщение чтобы изменить список</i>"
# Компактная подсказка — синхронизирована с backend/task_list_renderer.py.
# Если меняешь — меняй там тоже, оба рендерера обязаны давать одинаковый HTML.
HINT_LINE_SILENT = (
    "↩️ <i>Reply: закрыть · добавить · удалить пункт или список</i>\n"
    "<i>Примеры: «закрой 1, 3» / «добавь хлеб» / «удали 2»</i>"
)


def _render_text(title: str | None, structured_data: dict, silent: bool = False) -> str:
    tasks = structured_data.get("tasks", [])
    header = f"📋 <b>{title or 'Список задач'}</b>"

    common_deadline = structured_data.get("common_deadline")
    if common_deadline:
        try:
            dt = datetime.fromisoformat(common_deadline)
            tag = dt.strftime('%d.%m') if dt.hour == 0 and dt.minute == 0 else dt.strftime('%d.%m %H:%M')
            header += f"  <i>⏰ {tag}</i>"
        except Exception:
            pass

    hint = HINT_LINE_SILENT if silent else HINT_LINE

    lines = [header]
    if not tasks:
        lines.append("\n<i>Нет задач</i>")
        lines.append("")
        lines.append(hint)
        return "\n".join(lines)

    lines.append("")
    for i, t in enumerate(tasks, start=1):
        check = "✅" if t.get("done") else "☐"
        text = t.get("text", "")
        deadline = t.get("deadline")
        dl_tag = ""
        if deadline:
            try:
                dt = datetime.fromisoformat(deadline)
                dl_tag = f" · <i>⏰ {dt.strftime('%d.%m')}</i>"
            except Exception:
                pass
        if t.get("done"):
            lines.append(f"{check} <s>{i}. {text}</s>{dl_tag}")
        else:
            lines.append(f"{check} {i}. {text}{dl_tag}")
        note = t.get("note")
        if note:
            lines.append(f"   <i>↳ {note}</i>")

    done = sum(1 for t in tasks if t.get("done"))
    if done > 0:
        lines.append(f"\n<i>Выполнено: {done} из {len(tasks)}</i>")

    lines.append("")
    lines.append(hint)
    return "\n".join(lines)


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


# ───────────────────── Dedup: merge / keep ─────────────────────


@router.callback_query(F.data.startswith("dm:"))
async def cb_dedup_merge(callback: CallbackQuery, api, store=None):
    """🔗 Объединить — merge new task list into old one."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return

    parts = callback.data.split(":", 1)
    if len(parts) < 2:
        await callback.answer("Ошибка", show_alert=True)
        return
    new_bid = parts[1]  # UUID нового bookmark

    if store is None:
        await callback.answer("Ошибка", show_alert=True)
        return

    # Атомарно читаем И удаляем состояние (GETDEL) — защита от double-tap
    dedup = await store.pop_dedup_alert(callback.message.chat.id, new_bid)
    if not dedup:
        await callback.answer("Предложение устаре��о.", show_alert=True)
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        return

    from bot.handlers.start import _ensure_user
    from bot.handlers.settings import is_silent
    token = await _ensure_user(callback, api)
    if not token:
        return

    new_bid = dedup["new_bid"]
    old_bid = dedup["old_bid"]
    new_msg_id = dedup["new_msg_id"]
    chat_id = callback.message.chat.id

    # Индикатор
    try:
        await callback.message.edit_text(
            "⏳ Объединяю списки...", parse_mode=None, reply_markup=None,
        )
    except TelegramBadRequest:
        pass

    # Вызываем merge endpoint
    try:
        updated_old = await api.merge_task_list(token, new_bid, old_bid)
    except Exception as e:
        logger.error(f"merge_task_list failed: {e}")
        await callback.answer(MSG_MERGE_FAILED, show_alert=True)
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        # pop уже удалил dedup state — ничего чистить не нужно
        return

    # ВАЖНО: рендерим обновлённый старый список ПЕРВЫМ — даже если delete
    # ниже упадёт, юзер уже увидит результат merge.
    # См. docs/bugs/2026-05-11-task-list-duplicates-and-merge-ui.md.
    silent = await is_silent(api, token, callback.from_user.id)

    # Найдём старое сообщение списка (может быть другой msg_id)
    old_msg_id = None
    try:
        task_list_ids = await store.list_task_list_message_ids(chat_id)
        for mid in task_list_ids:
            bid = await store.get_list_bookmark(chat_id, mid)
            if bid == old_bid:
                old_msg_id = mid
                break
    except Exception as e:
        logger.warning(f"cb_dedup_merge: scan for old_msg_id failed: {e}")

    rendered_ok = False
    if old_msg_id:
        try:
            await _rerender_at_bottom(
                callback.message.bot, chat_id, old_msg_id,
                updated_old, store=store, silent=silent,
            )
            rendered_ok = True
        except Exception as e:
            logger.warning(f"cb_dedup_merge: _rerender_at_bottom failed: {e}")

    if not rendered_ok:
        # Fallback: отправляем обновлённый список свежим сообщением
        try:
            text = _render_text(
                updated_old.get("title"),
                updated_old.get("structured_data", {}),
                silent=silent,
            )
            keyboard = (
                None if silent
                else _build_keyboard(old_bid, updated_old.get("structured_data", {}))
            )
            resp = await callback.message.bot.send_message(
                chat_id, text, reply_markup=keyboard,
                parse_mode="HTML", disable_web_page_preview=True,
            )
            try:
                await store.bind_list_message(chat_id, resp.message_id, old_bid)
            except Exception as e:
                logger.warning(f"cb_dedup_merge: bind_list_message failed: {e}")
        except Exception as e:
            # Если и это не сработало — юзеру хоть alert чтобы понимал.
            logger.error(f"cb_dedup_merge: send_message fallback failed: {e}")

    # Теперь чистим старое сообщение нового списка + alert.
    # Pinned message — сначала unpin (best-effort), потом delete.
    try:
        await callback.message.bot.unpin_chat_message(chat_id, new_msg_id)
    except TelegramBadRequest as e:
        # Если не был запинен — это OK
        logger.debug(f"cb_dedup_merge: unpin {new_msg_id} skipped: {e.message}")
    except Exception as e:
        logger.warning(f"cb_dedup_merge: unpin {new_msg_id} unexpected: {e}")

    try:
        await callback.message.bot.delete_message(chat_id, new_msg_id)
    except TelegramBadRequest as e:
        # WARNING — иначе никогда не узнаем что мусор остаётся в чате.
        # См. docs/bugs/2026-05-11-task-list-duplicates-and-merge-ui.md.
        logger.warning(
            f"cb_dedup_merge: delete new list message {new_msg_id} failed: {e.message}"
        )

    # Unbind новый список из Redis
    try:
        await store.unbind_list_message(chat_id, new_msg_id)
    except Exception as e:
        logger.debug(f"cb_dedup_merge: unbind_list_message failed: {e}")

    # Удаляем alert
    try:
        await callback.message.delete()
    except TelegramBadRequest as e:
        logger.warning(f"cb_dedup_merge: delete alert failed: {e.message}")

    # Redis dedup state уже удалён через pop_dedup_alert
    await callback.answer(MSG_LIST_MERGED)


@router.callback_query(F.data.startswith("dk:"))
async def cb_dedup_keep(callback: CallbackQuery, store=None):
    """📋 Оставить отдельно — dismiss dedup alert."""
    parts = callback.data.split(":", 1)
    if len(parts) < 2:
        await callback.answer("Ошибка", show_alert=True)
        return
    new_bid = parts[1]

    # Удаляем alert
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass

    # Чистим Redis
    if store is not None:
        try:
            await store.delete_dedup_alert(callback.message.chat.id, new_bid)
        except Exception:
            pass

    await callback.answer("Оставлено как есть")


# ────��──────────────── Reply meta-commands ──────��──────────────

_DELETE_PHRASES = frozenset({
    "удали", "удалить", "удали список", "удалить список",
    "убери", "убери список", "убрать список", "снеси", "снеси список",
})


def _is_delete_command(text: str) -> bool:
    return text in _DELETE_PHRASES


# ───────────────────── Fast-path NL edits (без LLM) ─────────────

# Паттерны: "9 до завтра", "3 до пятницы", "9 пункт до завтра", "9: до 08.05"
_DEADLINE_PATTERN = re.compile(
    r"^(\d+)\s*(?:пункт|п|:|-|—)?\s*(?:до|к|дедлайн|срок|deadline)?\s*(.+)$",
    re.IGNORECASE,
)
# Mark done — широкий список синонимов + один или несколько индексов через "," или "и".
# Ловит: "закрой 1", "закрой 1, 3", "выполни 2 и 4", "1 готово", "3 пункт сделано",
#        "✅ 1, 2", "сделал 5", "гтв 7", "done 10".
# ВАЖНО: идемпотентный SET (done=True), НЕ toggle. Снять галку — через _UNDONE_PATTERN.
_INDEX_GROUP = r"(\d+(?:\s*(?:[,;]|\bи\b)\s*\d+)*)"
_DONE_VERBS = (
    r"готово|сделано?|сделал[аи]?|закончил[аи]?|завершил[аи]?|"
    r"гтв|done|✓|✅|закрой|закрыть|закрыт[аоы]?|"
    r"отметь|отметить|выполни|выполнить|сделай"
)
_DONE_PATTERN = re.compile(
    rf"^(?:{_DONE_VERBS})\s*{_INDEX_GROUP}\s*(?:пункт[аы]?|п)?$"
    rf"|"
    rf"^{_INDEX_GROUP}\s*(?:пункт[аы]?|п)?\s*(?:{_DONE_VERBS})$",
    re.IGNORECASE,
)
# Unmark done — снять галку. ВАЖНО: «не готово» проверяем ДО _DONE_PATTERN
# чтобы «готово» не сматчилось раньше.
_UNDONE_VERBS = (
    r"не\s+готов[оы]?|не\s+сделано?|"
    r"отмени|отменить|"
    r"вернуть|верни|"
    r"снять|сними|открой|открыть"
)
_UNDONE_PATTERN = re.compile(
    rf"^(?:{_UNDONE_VERBS})\s*{_INDEX_GROUP}\s*(?:пункт[аы]?|п)?$"
    rf"|"
    rf"^{_INDEX_GROUP}\s*(?:пункт[аы]?|п)?\s*(?:{_UNDONE_VERBS})$",
    re.IGNORECASE,
)
# Bulk: «всё/все готово», «закрой всё/все», «готово всё». done=True для всех.
_ALL_DONE_PATTERN = re.compile(
    r"^(?:"
    r"(?:всё|все)\s+(?:готово|сделано|закрыт[оы]?)"
    r"|закрой\s+(?:всё|все)"
    r"|закрыть\s+(?:всё|все)"
    r"|готово\s+(?:всё|все)"
    r")$",
    re.IGNORECASE,
)
# "добавь X", "+ X", "запиши X"
_ADD_PATTERN = re.compile(
    r"^(?:добавь|добавить|запиши|записать|внеси|внести|\+)\s+(.+)$",
    re.IGNORECASE,
)
# "удали 3", "удали 1, 3", "убери 2 и 4", "- 5"
_REMOVE_PATTERN = re.compile(
    rf"^(?:удали|удалить|убери|убрать|-)\s*{_INDEX_GROUP}\s*(?:пункт[аы]?|п)?$",
    re.IGNORECASE,
)


def _parse_indices(group_text: str) -> list[int]:
    """'1, 3', '1 и 4', '2;5' → [0, 2] / [0, 3] / [1, 4] (0-based, отсортировано, без дублей)."""
    raw = re.split(r"[,;]|\sи\s", group_text)
    out: set[int] = set()
    for chunk in raw:
        chunk = chunk.strip()
        if chunk.isdigit():
            out.add(int(chunk) - 1)
    return sorted(out)

_DAY_NAMES = {
    "понедельник": 0, "пн": 0,
    "вторник": 1, "вт": 1,
    "среда": 2, "ср": 2, "среду": 2,
    "четверг": 3, "чт": 3,
    "пятница": 4, "пт": 4, "пятницу": 4,
    "суббота": 5, "сб": 5, "субботу": 5,
    "воскресенье": 6, "вс": 6,
}


def _parse_date(text: str) -> str | None:
    """Парсит дату из текста. Возвращает ISO YYYY-MM-DD или None."""
    text = text.strip().lower().rstrip(".")

    today = date.today()

    if text in ("сегодня", "today"):
        return today.isoformat()
    if text in ("завтра", "tomorrow"):
        return (today + timedelta(days=1)).isoformat()
    if text in ("послезавтра",):
        return (today + timedelta(days=2)).isoformat()

    # "через N дней"
    m = re.match(r"через\s+(\d+)\s+(?:день|дня|дней)", text)
    if m:
        return (today + timedelta(days=int(m.group(1)))).isoformat()

    # "через неделю"
    if text in ("через неделю",):
        return (today + timedelta(weeks=1)).isoformat()

    # День недели
    if text in _DAY_NAMES:
        target_wd = _DAY_NAMES[text]
        current_wd = today.weekday()
        days_ahead = (target_wd - current_wd) % 7
        if days_ahead == 0:
            days_ahead = 7  # следующий такой день
        return (today + timedelta(days=days_ahead)).isoformat()

    # DD.MM или DD.MM.YYYY
    m = re.match(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?$", text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            pass

    return None


def _try_fast_edit(user_text: str, structured: dict) -> dict | None:
    """Пробует применить простую команду без LLM.

    Возвращает обновлённый structured_data или None если не распознал.
    """
    text = user_text.strip()
    tasks = list(structured.get("tasks", []))
    if not tasks:
        return None

    # All done: «всё готово», «закрой все» → done=True для всех
    if _ALL_DONE_PATTERN.match(text):
        new_tasks = [{**t, "done": True} for t in tasks]
        return {**structured, "tasks": new_tasks}

    # Undone — проверяем ДО done чтобы «не готово» не сматчилось как «готово»
    m = _UNDONE_PATTERN.match(text)
    if m:
        group = m.group(1) or m.group(2)
        indices = _parse_indices(group)
        if not indices:
            return None
        if any(i < 0 or i >= len(tasks) for i in indices):
            return None
        for idx in indices:
            tasks[idx] = {**tasks[idx], "done": False}
        return {**structured, "tasks": tasks}

    # Done: «закрой 1», «закрой 1, 3», «выполни 2 и 4», «3 готово», «сделал 5».
    # ИДЕМПОТЕНТНО (set done=True, не toggle).
    m = _DONE_PATTERN.match(text)
    if m:
        group = m.group(1) or m.group(2)
        indices = _parse_indices(group)
        if not indices:
            return None
        if any(i < 0 or i >= len(tasks) for i in indices):
            return None
        for idx in indices:
            tasks[idx] = {**tasks[idx], "done": True}
        return {**structured, "tasks": tasks}

    # Remove: "удали 3", "удали 1, 3", "убери 2 и 4"
    m = _REMOVE_PATTERN.match(text)
    if m:
        indices = _parse_indices(m.group(1))
        if not indices:
            return None
        if any(i < 0 or i >= len(tasks) for i in indices):
            return None
        # Удаляем с конца, чтобы индексы не сдвигались
        for idx in sorted(indices, reverse=True):
            tasks.pop(idx)
        return {**structured, "tasks": tasks}

    # Add: "добавь X", "+ X"
    m = _ADD_PATTERN.match(text)
    if m:
        new_text = m.group(1).strip()
        if new_text:
            tasks.append({"text": new_text, "done": False, "deadline": None, "note": None})
            return {**structured, "tasks": tasks}
        return None

    # Deadline: "9 до завтра", "3 пятница", "9: до 08.05"
    m = _DEADLINE_PATTERN.match(text)
    if m:
        idx = int(m.group(1)) - 1
        date_text = m.group(2).strip()
        parsed = _parse_date(date_text)
        if parsed and 0 <= idx < len(tasks):
            tasks[idx] = {**tasks[idx], "deadline": parsed}
            return {**structured, "tasks": tasks}
        # Не смогли распарсить дату — пусть LLM попробует
        return None

    return None


async def _handle_delete_via_reply(
    message: Message, api, token: str, bid: str, store=None,
) -> None:
    """Удалить task_list целиком через reply-команду (silent mode аналог кнопки 🗑)."""
    replied = message.reply_to_message

    # Unpin
    if replied:
        try:
            await replied.unpin()
        except TelegramBadRequest:
            pass

    # Удалить bookmark в БД
    try:
        await api.delete_bookmark(token, bid)
    except Exception as e:
        logger.error(f"delete_bookmark via reply failed: {e}")

    # Удалить сообщение бота
    if replied:
        try:
            await replied.delete()
        except TelegramBadRequest:
            try:
                await replied.edit_text("🗑 Удалён", parse_mode=None, reply_markup=None)
            except TelegramBadRequest:
                pass

    # Удалить reply юзера
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    # Чистим Redis
    if store is not None and replied:
        try:
            await store.unbind_list_message(message.chat.id, replied.message_id)
        except Exception:
            pass


# ───────────────────── General dedup reply handler ─────────────────────

# Интент-парсинг для dedup: keyword matching (без LLM)
_DEDUP_OPEN = frozenset({
    "открой", "открыть", "покажи", "показать", "оригинал", "старую",
})
_DEDUP_SAVE_NEW = frozenset({
    "сохрани", "сохранить", "новая", "новую", "создай", "копию",
    "оставь", "оставить", "как новую", "сохрани как новую",
})
_DEDUP_DELETE = frozenset({
    "удали", "удалить", "удали дубль", "удалить дубль",
    "убери", "убрать", "не нужен", "не нужна",
})
# "обнови" / всё остальное → обновить оригинал


def _parse_dedup_intent(text: str) -> str:
    """Парсит намерение юзера из ответа на dedup-alert.

    Возвращает: 'open' | 'save_new' | 'delete' | 'update'
    """
    words = text.strip().lower()
    if words in _DEDUP_OPEN or any(w in words for w in ("открой", "покажи", "оригинал")):
        return "open"
    if words in _DEDUP_SAVE_NEW or any(w in words for w in ("сохрани", "новую", "новая", "копию", "оставь")):
        return "save_new"
    if words in _DEDUP_DELETE or any(w in words for w in ("удали", "удалить", "убери", "убрать", "не нужен")):
        return "delete"
    if any(w in words for w in ("обнови", "обновить", "замени", "заменить", "перезаписать")):
        return "update"
    return "unknown"


async def _show_updated_task_list_after_dedup_update(
    bot, chat_id: int, old_bid: str, old_bm: dict, store, silent: bool = False,
) -> bool:
    """После dedup intent='update' для task_list — показываем обновлённый
    старый список юзеру (он забыл и отправил новый, ожидает увидеть результат).

    Возвращает True если рендер успешен. False — если old_bm не task_list или
    Telegram refused render (тогда вызывающий код покажет «Оригинал обновлён»
    как fallback).

    См. docs/bugs/2026-05-11-task-list-duplicates-and-merge-ui.md (corner case 2).
    """
    structured = (old_bm or {}).get("structured_data") or {}
    if not isinstance(structured, dict) or structured.get("type") != "task_list":
        return False  # не task_list — re-render не нужен

    # Ищем старое сообщение списка по bid
    old_msg_id = None
    try:
        task_list_ids = await store.list_task_list_message_ids(chat_id)
        for mid in task_list_ids:
            bid = await store.get_list_bookmark(chat_id, mid)
            if bid == old_bid:
                old_msg_id = mid
                break
    except Exception as e:
        logger.warning(f"_show_updated_task_list: scan failed: {e}")

    if old_msg_id:
        try:
            await _rerender_at_bottom(
                bot, chat_id, old_msg_id, old_bm, store=store, silent=silent,
            )
            return True
        except Exception as e:
            logger.warning(f"_show_updated_task_list: _rerender failed: {e}")

    # Fallback: свежее сообщение со списком
    try:
        text = _render_text(old_bm.get("title"), structured, silent=silent)
        keyboard = None if silent else _build_keyboard(old_bid, structured)
        resp = await bot.send_message(
            chat_id, text, reply_markup=keyboard,
            parse_mode="HTML", disable_web_page_preview=True,
        )
        try:
            await store.bind_list_message(chat_id, resp.message_id, old_bid)
        except Exception as e:
            logger.debug(f"_show_updated_task_list: bind failed: {e}")
        return True
    except Exception as e:
        logger.error(f"_show_updated_task_list: send_message failed: {e}")
        return False


async def _apply_dedup_update(
    api, token: str, new_bid: str, old_bid: str,
) -> dict | None:
    """Общая логика intent='update' для всех 3 dedup flow:
    1. cb_dedup_merge (callback кнопки)
    2. _handle_general_dedup_reply (reply на alert)
    3. _handle_pending_dedup (следующее сообщение по ключевому слову)

    Семантика: переносит поля new → old, удаляет new, возвращает обновлённый old.
    None если что-то упало (вызывающий покажет error).

    См. bookmark-brain-4ag.
    """
    try:
        new_bm = await api.get_bookmark(token, new_bid)
    except Exception as e:
        logger.warning(f"_apply_dedup_update: get new {new_bid} failed: {e}")
        return None

    update_fields = {}
    for field in ("raw_text", "title", "summary", "structured_data"):
        if new_bm.get(field):
            update_fields[field] = new_bm[field]

    try:
        if update_fields:
            await api.update_bookmark(token, old_bid, update_fields)
        await api.delete_bookmark(token, new_bid)
    except Exception as e:
        logger.warning(f"_apply_dedup_update: patch/delete failed: {e}")
        return None

    try:
        return await api.get_bookmark(token, old_bid)
    except Exception as e:
        logger.warning(f"_apply_dedup_update: get updated old failed: {e}")
        return None


async def _handle_general_dedup_reply(
    message: Message, api, store, dedup: dict,
) -> None:
    """Обрабатывает reply на general dedup alert."""
    from bot.handlers.start import _ensure_user
    token = await _ensure_user(message, api)
    if not token:
        return

    replied = message.reply_to_message
    new_bid = dedup["new_bid"]
    old_bid = dedup["old_bid"]
    user_text = message.text or ""
    intent = _parse_dedup_intent(user_text)

    chat_id = message.chat.id

    if intent == "open":
        # Показываем оригинал, но НЕ удаляем дубль — юзер сам решит что с ним делать.
        # State сохраняем (не pop), чтобы reply на превью продолжил флоу.
        try:
            old_bm = await api.get_bookmark(token, old_bid)
            title = old_bm.get("title") or "Без названия"
            summary = old_bm.get("summary") or ""
            structured = old_bm.get("structured_data") or {}
            is_task_list = (
                isinstance(structured, dict)
                and structured.get("type") == "task_list"
            )

            lines = [f"📖 <b>{title}</b>"]
            if summary:
                lines.append(summary[:300])

            # Где найти оригинал
            lines.append("")
            if is_task_list:
                lines.append(
                    "<i>📋 Список уже в чате — прокрути выше до закреплённого "
                    "сообщения. Или /list — все списки и закладки.</i>"
                )
            else:
                lines.append(
                    "<i>📚 Все закладки — /list. "
                    "Поиск по смыслу — /search &lt;запрос&gt;.</i>"
                )

            # Что делать с дублем
            lines.append("")
            lines.append("<b>↩️ Reply что делать с новым дублем:</b>")
            lines.append("• <b>удали</b> — убрать дубль (старый останется)")
            lines.append("• <b>замени</b> — обновить старый данными нового")
            lines.append("• <b>оставь оба</b> — сохранить и старый, и новый")

            await replied.edit_text(
                "\n".join(lines),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            # Удаляем reply юзера («открой») — превью на его месте
            try:
                await message.delete()
            except TelegramBadRequest:
                pass
            # State НЕ pop — reply на превью продолжит обрабатываться этим же handler.
        except Exception as e:
            logger.debug(f"show original failed: {e}")
            await _ephemeral(message, "Не удалось показать оригинал. Попробуй /list")
        return  # Не идём в общий pop_general_dedup ниже

    elif intent == "delete":
        # Удаляем новый дубль, оригинал остаётся
        try:
            await api.delete_bookmark(token, new_bid)
        except Exception as e:
            logger.debug(f"delete new bookmark failed: {e}")
        try:
            await replied.edit_text(MSG_DUP_DELETED, parse_mode=None)
            asyncio.create_task(_delete_after(replied, 5.0))
        except TelegramBadRequest:
            pass

    elif intent == "save_new":
        # Оставляем оба — просто убираем alert
        try:
            await replied.edit_text(MSG_SAVED_NEW, parse_mode=None)
            asyncio.create_task(_delete_after(replied, 5.0))
        except TelegramBadRequest:
            pass

    elif intent == "update":
        # См. docs/bugs/2026-05-11-task-list-duplicates-and-merge-ui.md
        old_bm = await _apply_dedup_update(api, token, new_bid, old_bid)
        if old_bm is None:
            await _ephemeral(message, MSG_UPDATE_FAILED)
        else:
            from bot.handlers.settings import is_silent
            silent = await is_silent(api, token, message.from_user.id)
            rendered = await _show_updated_task_list_after_dedup_update(
                message.bot, chat_id, old_bid, old_bm, store, silent=silent,
            )
            if rendered:
                try:
                    await replied.delete()
                except TelegramBadRequest:
                    pass
            else:
                try:
                    await replied.edit_text(MSG_ORIGINAL_UPDATED, parse_mode=None)
                    asyncio.create_task(_delete_after(replied, 5.0))
                except TelegramBadRequest:
                    pass

    else:
        # Неизвестный интент — переспрашиваем
        await _ephemeral(
            message,
            "Не понял. Ответь или напиши:\n"
            "открой / удали / обнови / сохрани как новую",
            delay=10,
        )
        # Удаляем reply юзера, но НЕ чистим Redis — дать ещё попытку
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        return

    # Удаляем reply юзера
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    # Чистим Redis (atomic)
    await store.pop_general_dedup(chat_id, replied.message_id)
    await store.clear_pending_dedup(chat_id)


async def _handle_pending_dedup(
    message: Message, api, store, dedup: dict,
    intent: str, alert_msg_id: int,
) -> None:
    """Обработка dedup-ответа БЕЗ reply (следующее сообщение с ключевым словом).

    В отличие от _handle_general_dedup_reply, у нас нет replied message,
    поэтому alert редактируем через bot.edit_message_text.
    """
    from bot.handlers.start import _ensure_user
    token = await _ensure_user(message, api)
    if not token:
        return

    new_bid = dedup["new_bid"]
    old_bid = dedup["old_bid"]
    chat_id = message.chat.id
    bot = message.bot

    async def _edit_alert(text: str) -> None:
        try:
            await bot.edit_message_text(
                text, chat_id=chat_id, message_id=alert_msg_id, parse_mode=None,
            )
        except TelegramBadRequest:
            pass

    if intent == "open":
        try:
            await api.delete_bookmark(token, new_bid)
        except Exception:
            pass
        try:
            old_bm = await api.get_bookmark(token, old_bid)
            title = old_bm.get("title") or "Без названия"
            summary = old_bm.get("summary") or ""
            lines = [f"\U0001f4d6 {title}"]
            if summary:
                lines.append(summary[:300])
            await _edit_alert("\n".join(lines))
        except Exception:
            await _edit_alert("Дубль удалён, оригинал сохранён ✅")

    elif intent == "delete":
        try:
            await api.delete_bookmark(token, new_bid)
        except Exception:
            pass
        await _edit_alert(MSG_DUP_DELETED)
        asyncio.create_task(_delete_after_by_id(bot, chat_id, alert_msg_id, 5.0))

    elif intent == "save_new":
        await _edit_alert(MSG_SAVED_NEW)
        asyncio.create_task(_delete_after_by_id(bot, chat_id, alert_msg_id, 5.0))

    elif intent == "update":
        # См. docs/bugs/2026-05-11-task-list-duplicates-and-merge-ui.md
        old_bm = await _apply_dedup_update(api, token, new_bid, old_bid)
        if old_bm is None:
            await _edit_alert(MSG_UPDATE_FAILED)
        else:
            from bot.handlers.settings import is_silent
            silent = await is_silent(api, token, message.from_user.id)
            rendered = await _show_updated_task_list_after_dedup_update(
                bot, chat_id, old_bid, old_bm, store, silent=silent,
            )
            if rendered:
                try:
                    await bot.delete_message(chat_id, alert_msg_id)
                except TelegramBadRequest:
                    pass
            else:
                await _edit_alert(MSG_ORIGINAL_UPDATED)
                asyncio.create_task(_delete_after_by_id(bot, chat_id, alert_msg_id, 5.0))

    # Удаляем сообщение юзера
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    # Чистим Redis
    await store.pop_general_dedup(chat_id, alert_msg_id)
    await store.clear_pending_dedup(chat_id)


async def _delete_after_by_id(bot, chat_id: int, msg_id: int, delay: float) -> None:
    """Удаляет сообщение по ID через delay секунд."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, msg_id)
    except TelegramBadRequest:
        pass


# ───────────────────── Stale list nudge reply handler ──────────────

_NUDGE_TRANSFER = frozenset({
    "перенести", "перенеси", "переноси", "перенос",
    "да", "ок", "давай", "го",
})
_NUDGE_CLOSE = frozenset({
    "закрыть", "закрой", "готово", "сделано", "всё", "done",
})
_NUDGE_LEAVE = frozenset({
    "оставить", "оставь", "нет", "не надо", "пропустить", "пропусти", "скип",
})


def _parse_nudge_intent(text: str) -> str:
    """Парсит намерение из ответа на nudge.

    Возвращает: 'transfer' | 'close' | 'leave' | 'unknown'
    """
    words = text.strip().lower()
    if words in _NUDGE_TRANSFER or any(w in words for w in ("перенес", "перенос")):
        return "transfer"
    if words in _NUDGE_CLOSE or any(w in words for w in ("закрой", "закрыть", "готово", "сделано", "done")):
        return "close"
    if words in _NUDGE_LEAVE or any(w in words for w in ("оставь", "оставить", "не надо", "пропуст", "скип")):
        return "leave"
    return "unknown"


async def _handle_nudge_reply(
    message: Message, api, store, nudge: dict, nudge_msg_id: int,
) -> None:
    """Обрабатывает reply на stale list nudge."""
    from bot.handlers.start import _ensure_user
    from bot.handlers.settings import is_silent
    token = await _ensure_user(message, api)
    if not token:
        return

    bid = nudge["bookmark_id"]
    user_text = message.text or ""
    intent = _parse_nudge_intent(user_text)
    chat_id = message.chat.id

    async def _confirm_nudge() -> None:
        """Pop nudge key + edit nudge msg + delete user reply."""
        await store.pop_nudge(chat_id, nudge_msg_id)

    async def _edit_nudge(text: str, auto_delete: float = 5.0) -> None:
        try:
            await message.bot.edit_message_text(
                text, chat_id=chat_id, message_id=nudge_msg_id, parse_mode=None,
            )
            asyncio.create_task(_delete_after_by_id(message.bot, chat_id, nudge_msg_id, auto_delete))
        except TelegramBadRequest:
            pass

    async def _cleanup_on_error(error_text: str) -> None:
        """Cleanup nudge + user reply on API error."""
        await _edit_nudge(f"⚠️ {error_text}")
        try:
            await message.delete()
        except TelegramBadRequest:
            pass

    if intent == "transfer":
        # Создаём новый список из невыполненных, старый → archived
        try:
            old_bm = await api.get_bookmark(token, bid)
            old_sd = old_bm.get("structured_data") or {}
            old_tasks = old_sd.get("tasks", [])
            undone = [t for t in old_tasks if not t.get("done")]

            if not undone:
                await _confirm_nudge()
                await _edit_nudge("✅ Все задачи уже выполнены!")
            else:
                # Архивируем старый
                await api.update_bookmark(token, bid, {"is_archived": True})

                # Создаём новый с невыполненными задачами
                silent = await is_silent(api, token, message.from_user.id)
                raw_lines = [t.get("text", "") for t in undone]
                raw_text = "сделай список: " + ", ".join(raw_lines)

                await api.create_bookmark(
                    token=token,
                    raw_text=raw_text,
                    url=None,
                    source="nudge_transfer",
                    source_message_id=None,
                    notify_chat_id=chat_id,
                    notify_message_id=None,
                    silent=silent,
                )

                await _confirm_nudge()
                await _edit_nudge("✅ Невыполненные задачи перенесены в новый список")

        except Exception as e:
            logger.error(f"nudge transfer failed: {e}")
            await _confirm_nudge()
            await _cleanup_on_error("Не удалось перенести. Попробуй /todo заново.")
            return

    elif intent == "close":
        # Помечаем все задачи done + архивируем
        try:
            old_bm = await api.get_bookmark(token, bid)
            sd = old_bm.get("structured_data") or {}
            tasks = [{**t, "done": True} for t in sd.get("tasks", [])]
            await api.update_bookmark(token, bid, {
                "structured_data": {**sd, "tasks": tasks},
                "is_archived": True,
            })
            await _confirm_nudge()
            await _edit_nudge("✅ Список закрыт")
        except Exception as e:
            logger.error(f"nudge close failed: {e}")
            await _confirm_nudge()
            await _cleanup_on_error("Не удалось закрыть список.")
            return

    elif intent == "leave":
        await _confirm_nudge()
        await _edit_nudge("👌 Оставлено")

    else:
        # Неизвестный интент — НЕ pop'аем nudge, даём ещё попытку
        await _ephemeral(
            message,
            "Не понял. Ответь reply:\nперенести / закрыть / оставить",
            delay=10,
        )
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        return

    # Удаляем reply юзера
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


# ───────────────────── Reply-based NL editor ─────────────────────


@router.message(
    F.reply_to_message
    & F.reply_to_message.from_user.is_bot
    & F.text
    & ~F.text.startswith("/")
)
async def msg_nl_edit_on_reply(message: Message, api, store=None):
    """Пользователь ответил на сообщение бота текстом → NL-редактирование списка.

    Мы ловим ВСЕ reply на бота и проверяем через Redis-мапу, был ли этот
    message_id зарегистрирован как task_list. Если да — применяем NL-edit.
    Если нет — показываем ephemeral подсказку и ПОГЛОЩАЕМ сообщение
    (важно: иначе catch-all в start.py создаст из этого reply закладку).
    """
    replied = message.reply_to_message
    if not replied:
        return

    if store is None:
        # Без Redis мы всё равно не должны создать закладку из reply —
        # сообщение юзер адресовал боту, а не в пустоту. Съедаем и подсказываем.
        await _ephemeral(message, "Список пока нельзя редактировать. Попробуй позже.")
        return

    # General dedup: reply на "Похоже на..." alert
    dedup = await store.get_general_dedup(message.chat.id, replied.message_id)
    if dedup:
        await _handle_general_dedup_reply(message, api, store, dedup)
        return

    # Stale list nudge: reply на nudge alert (get, not pop — pop inside handler on confirmed intent)
    nudge = await store.get_nudge(message.chat.id, replied.message_id)
    if nudge:
        await _handle_nudge_reply(message, api, store, nudge, replied.message_id)
        return

    bid = await store.get_list_bookmark(message.chat.id, replied.message_id)
    if not bid:
        # Reply на бот-сообщение, но это не task_list и не dedup-alert.
        await _ephemeral(
            message,
            "Не нашёл этот список. Открой /list и попробуй заново.",
        )
        return

    from bot.handlers.start import _ensure_user
    from bot.handlers.settings import is_silent
    token = await _ensure_user(message, api)
    if not token:
        return

    # Мета-команды: «удали список», «удалить» — обрабатываем без LLM
    user_text = (message.text or "").strip().lower()
    if _is_delete_command(user_text):
        await _handle_delete_via_reply(message, api, token, bid, store)
        return

    silent = await is_silent(api, token, message.from_user.id)

    # Индикатор — редактируем само сообщение со списком, добавляя "✏️ обрабатываю..."
    try:
        bookmark = await api.get_bookmark(token, bid)
    except Exception:
        await _ephemeral(message, "Список не найден", delay=6)
        return

    structured = bookmark.get("structured_data") or {}

    # Fast-path: простые команды (deadline, toggle, add, remove) без LLM
    fast_result = _try_fast_edit(message.text or "", structured)
    if fast_result is not None:
        try:
            await api.update_bookmark(token, bid, {"structured_data": fast_result})
            updated = await api.get_bookmark(token, bid)
        except Exception as e:
            logger.error(f"fast_edit update failed: {e}")
            await _ephemeral(message, "Не удалось обновить список.", delay=6)
            return

        # Удаляем reply юзера + любые хвосты предыдущих неудачных попыток
        try:
            await message.delete()
        except TelegramBadRequest:
            pass

        if store:
            await _cleanup_failed_attempts(message.bot, message.chat.id, replied.message_id, store)
            await store.force_last_seen(message.chat.id, replied.message_id)

        await _rerender_at_bottom(
            message.bot, message.chat.id, replied.message_id,
            updated, store=store, silent=silent,
        )
        return

    # LLM path: сложные фразы
    busy_text = _render_text(bookmark.get("title"), structured, silent=silent) + "\n\n⏳ <i>Применяю…</i>"

    try:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=replied.message_id,
            text=busy_text,
            reply_markup=None,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except TelegramBadRequest:
        pass

    try:
        updated = await api.nl_edit_bookmark(token, bid, message.text)
    except Exception as e:
        logger.error(f"nl_edit failed: {e}")
        # Восстанавливаем исходный вид старого сообщения
        restore_text = _render_text(bookmark.get("title"), structured, silent=silent)
        restore_kb = None if silent else _build_keyboard(bid, structured)
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=replied.message_id,
                text=restore_text,
                reply_markup=restore_kb,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except TelegramBadRequest:
            pass
        # Видимая обратная связь: реакция 👎 на reply юзера + объяснение
        from bot.utils import safe_react
        await safe_react(message, "\U0001f44e")
        help_msg = await message.reply(
            "Не понял.\n"
            "Доступно: отметить готово/не готово, добавить, удалить, дедлайн.\n\n"
            "Примеры:\n"
            "• «10 готово» / «сделал 5» / «гтв 7»\n"
            "• «10 не готово» / «отмени 12»\n"
            "• «всё готово»\n"
            "• «закрой 1, 3» / «выполни 2 и 4»\n"
            "• «добавь купить хлеб»\n"
            "• «удали 2» / «удали список»\n"
            "• «3 до завтра» (дедлайн)",
            parse_mode=None,
        )
        # Трекаем «хвосты» — если следующий reply сработает, удалим оба.
        if store is not None:
            try:
                await store.track_cleanup_msg(message.chat.id, replied.message_id, message.message_id)
                await store.track_cleanup_msg(message.chat.id, replied.message_id, help_msg.message_id)
            except Exception as e:
                logger.debug(f"track_cleanup_msg failed: {e}")
        return

    # Удаляем reply юзера ДО отправки свежего списка.
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    # После удаления reply реальное "последнее" сообщение в чате — снова
    # сам список. Откатываем last_seen чтобы _rerender_at_bottom пошёл по
    # fast-path (edit-in-place) и не дёргал delete+send+pin зря.
    if store is not None:
        try:
            # Подчищаем «хвосты» предыдущих неудачных попыток (failed user
            # replies + bot help messages) — они трекаются в fail-path.
            await _cleanup_failed_attempts(message.bot, message.chat.id, replied.message_id, store)
            await store.force_last_seen(message.chat.id, replied.message_id)
        except Exception:
            pass

    await _rerender_at_bottom(
        message.bot, message.chat.id, replied.message_id,
        updated, store=store, silent=silent,
    )


async def _cleanup_failed_attempts(bot, chat_id: int, list_msg_id: int, store) -> None:
    """Удалить «хвосты» неудачных reply-попыток на этот task_list.

    Вызывается из success-path (fast-path и LLM-path). Если предыдущий reply
    был не понят, мы оставили в чате 👎-сообщение юзера + bot's «не понял».
    После успешной команды эти артефакты больше не нужны.

    Молча игнорирует ошибки — это best-effort cleanup, не критично.
    """
    try:
        msg_ids = await store.pop_cleanup_msgs(chat_id, list_msg_id)
    except Exception as e:
        logger.debug(f"pop_cleanup_msgs failed: {e}")
        return
    for mid in msg_ids:
        try:
            await bot.delete_message(chat_id, mid)
        except TelegramBadRequest:
            pass  # сообщение уже удалено или старше 48ч
        except Exception as e:
            logger.debug(f"cleanup delete {mid} failed: {e}")


# ───────────────────── Ephemeral helpers ─────────────────────


EPHEMERAL_DELAY = 8.0


async def _ephemeral(message: Message, text: str, delay: float = EPHEMERAL_DELAY) -> None:
    """Раньше автоудаляло сообщение через `delay` секунд. Теперь — НЕТ.

    Юзеру важно видеть что бот ответил, даже если это «не понял». Предыдущая
    эфемерность создавала впечатление что бот молчит. Имя и сигнатура
    сохранены для обратной совместимости со всеми вызовами в tasks.py.
    """
    await message.answer(text, parse_mode=None)


async def send_and_autodelete(message: Message, text: str, delay: float = EPHEMERAL_DELAY) -> None:
    """Backwards-compat для других модулей."""
    await _ephemeral(message, text, delay)


async def _delete_after(msg: Message, delay: float) -> None:
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except TelegramBadRequest:
        pass


# ───────────────────── /todo command ─────────────────────


@router.message(Command("todo"))
async def cmd_todo(message: Message, api):
    """`/todo пункт1, пункт2` — принудительно создать список."""
    from bot.handlers.start import _ensure_user
    token = await _ensure_user(message, api)
    if not token:
        return

    text = (message.text or "").split(maxsplit=1)
    if len(text) < 2 or not text[1].strip():
        await message.answer(
            "Напиши так: /todo купить молоко, позвонить маме, записаться к зубному",
            parse_mode=None,
        )
        return

    content = text[1].strip()
    raw_text = f"сделай список: {content}"

    from bot.handlers.settings import is_silent
    from bot.utils import safe_react, ephemeral_error
    silent = await is_silent(api, token, message.from_user.id)

    if silent:
        await safe_react(message, "\U0001f440")
        try:
            await api.create_bookmark(
                token=token,
                raw_text=raw_text,
                url=None,
                source="bot_command",
                source_message_id=message.message_id,
                notify_chat_id=message.chat.id,
                notify_message_id=message.message_id,
                silent=True,
            )
        except Exception as e:
            logger.error(f"/todo create failed: {e}")
            await safe_react(message, "\U0001f44e")
            await ephemeral_error(message, "Ошибка. Попробуй ещё раз.")
    else:
        status_msg = await message.answer("⏳ Обрабатываю...", parse_mode=None)
        try:
            await api.create_bookmark(
                token=token,
                raw_text=raw_text,
                url=None,
                source="bot_command",
                source_message_id=message.message_id,
                notify_chat_id=status_msg.chat.id,
                notify_message_id=status_msg.message_id,
            )
        except Exception as e:
            logger.error(f"/todo create failed: {e}")
            try:
                await status_msg.edit_text("Ошибка. Попробуй ещё раз.")
            except TelegramBadRequest:
                pass


# ───────────────────── /help command ─────────────────────
# Перенесён в bot/handlers/start.py:cmd_help — там полный, без авто-удаления.
# Старый handler здесь убит чтобы не перехватывать /help раньше нового.
