"""Dedup flows for task lists (3po split).

merge / keep callbacks, intent parsing, the shared dedup-update logic, and
both reply-based and pending (next-message) dedup handlers. Owns its own
Router.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message, ReactionTypeEmoji

from .shared import (
    MSG_DUP_DELETED,
    MSG_LIST_MERGED,
    MSG_MERGE_FAILED,
    MSG_ORIGINAL_UPDATED,
    MSG_SAVED_NEW,
    MSG_UPDATE_FAILED,
    _build_keyboard,
    _delete_after,
    _delete_after_by_id,
    _ephemeral,
    _render_text,
    _rerender_at_bottom,
)

logger = logging.getLogger(__name__)

router = Router()


async def _react_src(bot, chat_id: int, src_msg_id, emoji: str) -> None:
    """#10: вернуть реакцию на исходное сообщение юзера.

    В silent-режиме near-dup снимает 👀 (worker processing.py). Без этого
    после «сохрани как новую»/«обнови» юзер не видит вообще никакого
    фидбэка — кажется, что ничего не сохранилось. Best-effort.
    """
    if not src_msg_id:
        return
    try:
        await bot.set_message_reaction(
            chat_id, src_msg_id, [ReactionTypeEmoji(emoji=emoji)],
        )
    except Exception as e:
        logger.debug(f"_react_src failed for {src_msg_id}: {e}")


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
        await callback.answer("Предложение устарело.", show_alert=True)
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        return

    from bot.common.auth import ensure_user
    from bot.handlers.settings import is_silent
    token = await ensure_user(callback, api)
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


def parse_dedup_intent(text: str) -> str:
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
    3. handle_pending_dedup (следующее сообщение по ключевому слову)

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
    from bot.common.auth import ensure_user
    token = await ensure_user(message, api)
    if not token:
        return

    replied = message.reply_to_message
    new_bid = dedup["new_bid"]
    old_bid = dedup["old_bid"]
    src_msg_id = dedup.get("src_msg_id")
    user_text = message.text or ""
    intent = parse_dedup_intent(user_text)

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
        # #10: вернуть фидбэк на исходное сообщение (silent снял 👀)
        await _react_src(message.bot, chat_id, src_msg_id, "\U0001f44d")

    elif intent == "update":
        # См. docs/bugs/2026-05-11-task-list-duplicates-and-merge-ui.md
        old_bm = await _apply_dedup_update(api, token, new_bid, old_bid)
        if old_bm is None:
            await _ephemeral(message, MSG_UPDATE_FAILED)
        else:
            # #10: вернуть фидбэк на исходное сообщение (silent снял 👀)
            await _react_src(message.bot, chat_id, src_msg_id, "\U0001f44d")
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


async def handle_pending_dedup(
    message: Message, api, store, dedup: dict,
    intent: str, alert_msg_id: int,
) -> None:
    """Обработка dedup-ответа БЕЗ reply (следующее сообщение с ключевым словом).

    В отличие от _handle_general_dedup_reply, у нас нет replied message,
    поэтому alert редактируем через bot.edit_message_text.
    """
    from bot.common.auth import ensure_user
    token = await ensure_user(message, api)
    if not token:
        return

    new_bid = dedup["new_bid"]
    old_bid = dedup["old_bid"]
    src_msg_id = dedup.get("src_msg_id")
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
        await _react_src(bot, chat_id, src_msg_id, "\U0001f44d")

    elif intent == "update":
        # См. docs/bugs/2026-05-11-task-list-duplicates-and-merge-ui.md
        old_bm = await _apply_dedup_update(api, token, new_bid, old_bid)
        if old_bm is None:
            await _edit_alert(MSG_UPDATE_FAILED)
        else:
            await _react_src(bot, chat_id, src_msg_id, "\U0001f44d")
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
