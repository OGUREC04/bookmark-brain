"""Reply-based NL editor for task lists (3po split).

Stale-list nudge handling, the composite-reminder-on-task-list flow, the
main reply NL-edit dispatcher (msg_nl_edit_on_reply) and failed-attempt
cleanup. Owns its own Router.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from .dedup import _handle_general_dedup_reply
from .fast_edit import _handle_delete_via_reply, _is_delete_command, _try_fast_edit
from .shared import (
    _build_keyboard,
    _delete_after_by_id,
    _ephemeral,
    _render_text,
    _rerender_with_autounpin,
)

logger = logging.getLogger(__name__)

router = Router()


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
    from bot.common.auth import ensure_user
    from bot.handlers.settings import is_silent
    token = await ensure_user(message, api)
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


async def _handle_remind_on_task_list(
    message: Message, api, token: str, bookmark_id: str, body: str,
) -> None:
    """Phase 2.6 T7: создаём composite reminder на task_list по reply'ю.

    `body` — текст после «сделай напоминание …» (только время, либо
    «<текст> <время>» — text игнорируется, потому что reminder привязан к
    task_list'у, источник текста = title/summary списка).
    """
    from bot.common import (
        TIME_EXAMPLES,
        format_fire_at,
        get_user_tz_name,
        safe,
        split_remind_text_and_time,
    )
    from bot.services.nl_date import ParseStatus, parse

    user_tz_name = await get_user_tz_name(api, token)
    body_clean = body.strip()
    if not body_clean:
        await message.answer(
            "Когда напомнить? Например: <code>завтра в 9</code>, "
            "<code>в пятницу в 18</code>, <code>через час</code>",
            parse_mode="HTML",
        )
        return

    # Разделяем body на (текст, время). Для task_list текст игнорим, нужно
    # только время. Если время не нашли — всё тело = время (юзер написал
    # просто «в пятницу в 9»).
    _text_part, time_part = split_remind_text_and_time(body_clean, user_tz_name)
    if time_part is None:
        time_part = body_clean

    pr = parse(time_part, user_tz=user_tz_name)
    if pr.status == ParseStatus.IN_PAST:
        await message.answer("Это в прошлом. Назначь время в будущем.", parse_mode=None)
        return
    if pr.status == ParseStatus.NEEDS_HOUR:
        await message.answer(
            "Уточни время (например <code>в 9</code>). " + TIME_EXAMPLES,
            parse_mode="HTML",
        )
        return
    if pr.status == ParseStatus.UNPARSEABLE or pr.dt is None:
        await message.answer(
            f"Не понял время «{safe(time_part)}». " + TIME_EXAMPLES,
            parse_mode="HTML",
        )
        return

    # Composite reminder: text = bookmark.title (или fallback). Создаём
    # через стандартный create_reminder API (НЕ apply-decision — для уже
    # существующего task_list decision может отсутствовать или быть
    # уже применённой).
    #
    # IDOR: get_bookmark на backend'е фильтрует по current_user.id (см.
    # backend/app/api/bookmarks.py:233). Чужой bookmark вернёт 404 → юзер
    # увидит «Не нашёл этот список». get_list_bookmark в Redis даёт chat-
    # scoped lookup, плюс этот server-side guard — двойной фильтр.
    try:
        bookmark = await api.get_bookmark(token, bookmark_id)
    except Exception as e:
        logger.warning(f"T7: get_bookmark failed for {bookmark_id}: {e}")
        await message.answer("Не нашёл этот список.", parse_mode=None)
        return
    reminder_text = (bookmark.get("title") or bookmark.get("summary") or "Список задач")[:200]

    try:
        await api.create_reminder(
            token,
            pr.dt.isoformat(),
            bookmark_id=bookmark_id,
            payload={
                "text": reminder_text,
                "source": "reply_remind_task_list",
                "task_list_id": bookmark_id,
            },
        )
    except Exception as e:
        logger.warning(f"T7: create_reminder failed for {bookmark_id}: {e}")
        await message.answer(
            "Не получилось создать напоминание. Попробуй ещё раз.",
            parse_mode=None,
        )
        return

    fire_str = format_fire_at(pr.dt, user_tz_name)
    await message.answer(
        f"🔔 Напомню про список <b>{safe(reminder_text)}</b> — {safe(fire_str)}",
        parse_mode="HTML",
    )


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

    from bot.common.auth import ensure_user
    from bot.handlers.settings import is_silent
    token = await ensure_user(message, api)
    if not token:
        return

    # Мета-команды: «удали список», «удалить» — обрабатываем без LLM
    user_text = (message.text or "").strip().lower()
    if _is_delete_command(user_text):
        await _handle_delete_via_reply(message, api, token, bid, store)
        return

    # Phase 2.6 T7: explicit remind trigger в reply на task_list.
    # «сделай напоминание завтра в 9» / «напомни в пятницу» / «напомни через час»
    # → создаём composite reminder привязанный к этому task_list.
    from bot.common import extract_explicit_remind_body
    explicit_body = extract_explicit_remind_body(message.text or "")
    if explicit_body is not None:
        await _handle_remind_on_task_list(message, api, token, bid, explicit_body)
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

        await _rerender_with_autounpin(
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

    await _rerender_with_autounpin(
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
