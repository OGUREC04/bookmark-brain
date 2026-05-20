"""Task-list confirmation callbacks — «Сделать список?» Да/Нет.

Worker (``app.worker.task_list_offer``) вместо немедленного создания+пина
шлёт offer с кнопками. Здесь по «Да» список реально создаётся, биндится
и пинится; по «Нет» закладка остаётся обычной (structured_data=None —
заодно закрывает «вернуть не список»).

State: Redis ``task_list_pending:{chat}:{offer_msg}`` (writer — worker),
читается атомарным GETDEL (защита от double-tap). Owns its own Router.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message, ReactionTypeEmoji

from .shared import _build_keyboard, _render_text

logger = logging.getLogger(__name__)

router = Router()


async def _create_and_pin_task_list(
    bot, chat_id: int, token: str, api, store,
    bookmark_id: str, *, silent: bool,
    src_msg_id: int | None = None, is_media_src: bool = False,
) -> int | None:
    """Создать + забиндить + запинить task_list по подтверждённому
    bookmark_id. Используется из:
      - cb_tasklist_confirm («Да» на offer)
      - general dedup «сохрани как новую» когда new — task_list
        (юзер уже опт-инул через резолюцию near-dup, повторный
        offer не нужен).

    Возвращает message_id отправленного списка, либо None при сбое.
    """
    try:
        bookmark = await api.get_bookmark(token, bookmark_id)
    except Exception as e:
        logger.warning(f"_create_and_pin_task_list: get_bookmark {bookmark_id} failed: {e}")
        return None

    structured = bookmark.get("structured_data") or {}
    text = _render_text(bookmark.get("title"), structured, silent=silent)
    keyboard = None if silent else _build_keyboard(bookmark_id, structured)

    try:
        sent = await bot.send_message(
            chat_id, text, reply_markup=keyboard,
            parse_mode="HTML", disable_web_page_preview=True,
        )
    except Exception as e:
        logger.error(f"_create_and_pin_task_list: send list failed: {e}")
        return None

    # bind ПЕРЕД pin — иначе on_pin_service_message не найдёт.
    try:
        await store.bind_list_message(chat_id, sent.message_id, bookmark_id)
    except Exception as e:
        logger.debug(f"bind failed: {e}")
    try:
        await bot.pin_chat_message(chat_id, sent.message_id, disable_notification=True)
    except TelegramBadRequest as e:
        logger.debug(f"pin failed: {e.message}")

    try:
        await api.update_bookmark(token, bookmark_id, {"is_favorite": True})
    except Exception as e:
        logger.debug(f"set favorite failed: {e}")

    # Удаляем исходный текстовый дубль (silent). Медиа — не трогаем.
    if silent and src_msg_id and not is_media_src:
        try:
            await bot.delete_message(chat_id, src_msg_id)
        except TelegramBadRequest:
            pass

    return sent.message_id


@router.callback_query(F.data.startswith("tlc:"))
async def cb_tasklist_confirm(callback: CallbackQuery, api, store=None):
    """«✅ Да» — создаём, биндим и пиним список."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return
    if store is None:
        await callback.answer("Ошибка", show_alert=True)
        return

    chat_id = callback.message.chat.id
    pending = await store.pop_task_list_pending(chat_id, callback.message.message_id)
    if not pending:
        await callback.answer("Предложение устарело.", show_alert=True)
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        return

    from bot.common.auth import ensure_user
    token = await ensure_user(callback, api)
    if not token:
        return

    bid = pending["bookmark_id"]
    src_msg_id = pending.get("src_msg_id")
    silent = bool(pending.get("silent"))
    is_media_src = bool(pending.get("is_media_src"))

    new_msg_id = await _create_and_pin_task_list(
        callback.message.bot, chat_id, token, api, store, bid,
        silent=silent, src_msg_id=src_msg_id, is_media_src=is_media_src,
    )
    if new_msg_id is None:
        await callback.answer("Не удалось создать список.", show_alert=True)
        return

    # Чистим offer — список сам себе фидбэк.
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass

    # Post-confirm dedup-alert: worker нашёл похожий список ДО offer и
    # прокинул его в pending; теперь спрашиваем про объединение.
    similar = pending.get("similar")
    if similar and isinstance(similar, dict) and similar.get("id"):
        await _send_dedup_alert(
            callback.message.bot, chat_id, bid, new_msg_id, similar, store,
        )

    await callback.answer("Список создан ✅")


async def _send_general_dedup_alert(
    bot, chat_id: int, new_bid: str, src_msg_id, general_dup: dict, store,
) -> None:
    """Отложенный general near-dup при «Нет» на offer списка.
    Зеркало worker'овской ветки: тот же текст, тот же state, тот же
    reply-флоу (`dedup._handle_general_dedup_reply` подхватит)."""
    title = general_dup.get("title") or "Без названия"
    dup_type = "список" if general_dup.get("is_task_list") else "закладку"
    created = general_dup.get("created_at")
    date_str = ""
    if created:
        try:
            from datetime import datetime as _dt
            dt = _dt.fromisoformat(created) if isinstance(created, str) else created
            date_str = f" от {dt.strftime('%d.%m')}"
        except Exception:
            pass
    similarity = float(general_dup.get("similarity") or 0.0)
    prefix = "⚠️ Уже есть почти такая же" if similarity >= 0.95 else "🔄 Похожая запись уже сохранялась"
    alert_text = (
        f"{prefix} {dup_type}: <b>{title}</b>{date_str}\n\n"
        f"Что делаем с новой? Ответь reply на это сообщение:\n"
        f"• <b>открой</b> — покажу старую\n"
        f"• <b>удали</b> — удалю новую (старая останется)\n"
        f"• <b>обнови</b> — заменю старую новой\n"
        f"• <b>сохрани как новую</b> — оставлю обе"
    )
    gen_id = general_dup.get("id")
    if gen_id is None:
        logger.warning(
            f"_send_general_dedup_alert: payload missing 'id': "
            f"{list(general_dup.keys())}"
        )
        return
    try:
        sent = await bot.send_message(
            chat_id, alert_text, parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await store.store_general_dedup(
            chat_id, sent.message_id, new_bid, str(gen_id),
            src_msg_id=src_msg_id,
        )
    except Exception as e:
        logger.debug(f"_send_general_dedup_alert failed: {e}")


async def _send_dedup_alert(
    bot, chat_id: int, new_bid: str, new_msg_id: int,
    similar: dict, store,
) -> None:
    """Отправляет «🔄 Похожий список — объединить?» после подтверждения
    создания. Зеркало worker._build_dedup_alert + _store_dedup_alert."""
    title = similar.get("title") or "Список задач"
    done = similar.get("done_count", 0)
    total = similar.get("total_count", 0)
    created = similar.get("created_at")
    date_str = ""
    if created:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(created) if isinstance(created, str) else created
            date_str = f" от {dt.strftime('%d.%m')}"
        except Exception:
            pass
    text = (
        f"🔄 Похожий список <b>{title}</b>{date_str}\n"
        f"({done}/{total} выполнено)\n\n"
        f"Объединить новые задачи в него?"
    )
    sim_id = similar.get("id")
    if sim_id is None:
        logger.warning(
            f"_send_dedup_alert: similar payload missing 'id': "
            f"{list(similar.keys())}"
        )
        return
    buttons = {"inline_keyboard": [[
        {"text": "🔗 Объединить", "callback_data": f"dm:{new_bid}"},
        {"text": "📋 Отдельно", "callback_data": f"dk:{new_bid}"},
    ]]}
    try:
        await bot.send_message(
            chat_id, text, reply_markup=buttons,
            parse_mode="HTML", disable_web_page_preview=True,
        )
        await store.store_dedup_alert(chat_id, new_bid, sim_id, new_msg_id)
    except Exception as e:
        logger.debug(f"_send_dedup_alert failed: {e}")


@router.callback_query(F.data.startswith("tlx:"))
async def cb_tasklist_decline(callback: CallbackQuery, api, store=None):
    """«✕ Нет» — оставляем обычной закладкой (structured_data=None)."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return
    if store is None:
        await callback.answer("Ошибка", show_alert=True)
        return

    chat_id = callback.message.chat.id
    pending = await store.pop_task_list_pending(chat_id, callback.message.message_id)
    if not pending:
        await callback.answer("Предложение устарело.", show_alert=True)
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        return

    from bot.common.auth import ensure_user
    token = await ensure_user(callback, api)
    if not token:
        return

    bid = pending["bookmark_id"]
    src_msg_id = pending.get("src_msg_id")
    silent = bool(pending.get("silent"))
    general_dup = pending.get("general_dup")

    try:
        bookmark = await api.update_bookmark(token, bid, {"structured_data": None})
    except Exception as e:
        logger.warning(f"cb_tasklist_decline: update {bid} failed: {e}")
        await callback.answer("Ошибка", show_alert=True)
        return

    # Отложенный general near-dup: worker нашёл похожую запись ДО offer,
    # но не показал — ждали решения «Это список?». Юзер сказал «Нет» —
    # закладка обычная, теперь самое время спросить про дубль.
    if general_dup and isinstance(general_dup, dict) and general_dup.get("id"):
        # Чистим offer-сообщение, потом шлём near-dup alert.
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        await _send_general_dedup_alert(
            callback.message.bot, chat_id, bid, src_msg_id,
            general_dup, store,
        )
        await callback.answer()
        return

    if silent:
        # Тихий режим: убираем offer, ставим 👍 на исходное сообщение —
        # как у обычной закладки.
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        if src_msg_id:
            try:
                await callback.message.bot.set_message_reaction(
                    chat_id, src_msg_id, [ReactionTypeEmoji(emoji="\U0001f44d")],
                )
            except Exception as e:
                logger.debug(f"cb_tasklist_decline: react failed: {e}")
        await callback.answer("Сохранил как закладку")
        return

    # Verbose: offer → карточка обычной закладки.
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
    await callback.answer("Сохранил как закладку")
