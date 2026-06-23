"""Inline-callback handlers for Phase 2.5 reminders (q21 Step 3).

Callbacks:
- ``rsk:{bookmark_id}`` — accept «🔔 Создать напоминание?», ask for time
- ``rsn:{bookmark_id}`` — dismiss, clear pending state
- ``rdone:{reminder_id}`` — mark fired reminder as done (cancel via API)
- ``rsnz:{reminder_id}`` — snooze, ask for new time

Owns its own ``Router()``; aggregated by package ``__init__``.
"""
from __future__ import annotations

import logging

import httpx
from aiogram import F, Router
from aiogram.types import CallbackQuery

from .shared import _is_valid_uuid, _purge_reminder_dialog, _reply_prompt

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data.startswith("rsk:"))
async def cb_create_reminder(callback: CallbackQuery, api, store):
    """Юзер нажал «🔔 Создать напоминание?» — просим reply со временем.

    Bookmark_id мы НЕ берём из callback_data (хотя он там есть) — берём
    из Redis-ключа `reminder_pending:{chat_id}:{msg_id}` который ставит
    worker. Так не зависим от целостности callback_data.
    """
    try:
        await callback.message.edit_text(
            _reply_prompt("🔔 Когда напомнить?"),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.debug(f"cb_create_reminder: edit_text failed: {e}")
    # Redis key (reminder_pending:...) уже стоит — worker его поставил.
    # TTL 1ч хватит на ответ.
    try:
        await callback.answer("Жду время")
    except Exception:
        pass


@router.callback_query(F.data.startswith("rsn:"))
async def cb_dismiss_reminder(callback: CallbackQuery, api, store):
    """Юзер отказался от напоминания — убираем кнопки, чистим state."""
    chat_id = callback.message.chat.id
    msg_id = callback.message.message_id

    try:
        await callback.message.edit_text(
            "Окей, без напоминания.",
            parse_mode=None,
        )
    except Exception as e:
        logger.debug(f"cb_dismiss_reminder: edit_text failed: {e}")
    try:
        await store.delete_reminder_pending(chat_id, msg_id)
    except Exception as e:
        logger.debug(f"cb_dismiss_reminder: delete state failed: {e}")
    # Подметаем хвост диалога (обычно пуст), сохраняя edit-in-place «Окей…».
    await _purge_reminder_dialog(
        callback.message.bot, chat_id, msg_id, store, keep_msg_id=msg_id,
    )
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("rdone:"))
async def cb_done_reminder(callback: CallbackQuery, api, store):
    """«✅ Выполнено» на отправленном reminder — DELETE через API
    (status='cancelled') + edit message без кнопок."""
    from bot.common.auth import ensure_user

    chat_id = callback.message.chat.id
    msg_id = callback.message.message_id
    reminder_id = (callback.data or "").split(":", 1)[1] if ":" in (callback.data or "") else ""

    # H1: callback_data — attacker-controlled. Валидируем как UUID до API.
    if not _is_valid_uuid(reminder_id):
        try:
            await callback.answer("Сообщение устарело")
        except Exception:
            pass
        return

    token = await ensure_user(callback, api)
    if not token:
        return

    cancelled_ok = False
    try:
        await api.cancel_reminder(token, reminder_id)
        cancelled_ok = True
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            # Уже cancelled / auto_done / second click — считаем успехом.
            cancelled_ok = True
        else:
            logger.warning(f"cb_done_reminder: cancel 5xx: {e}")
    except Exception as e:
        logger.warning(f"cb_done_reminder: cancel failed: {e}")

    if not cancelled_ok:
        # Не редактируем сообщение и не чистим state — юзер сможет
        # повторить клик. Показываем popup.
        try:
            await callback.answer(
                "Не получилось отметить — попробуй ещё раз",
                show_alert=False,
            )
        except Exception:
            pass
        return

    try:
        await callback.message.edit_text("✅ Выполнено", parse_mode=None)
    except Exception as e:
        logger.debug(f"cb_done_reminder: edit_text failed: {e}")
    try:
        await store.delete_reminder_id(chat_id, msg_id)
    except Exception as e:
        logger.debug(f"cb_done_reminder: delete state failed: {e}")
    await _purge_reminder_dialog(
        callback.message.bot, chat_id, msg_id, store, keep_msg_id=msg_id,
    )
    try:
        await callback.answer("Готово")
    except Exception:
        pass


@router.callback_query(F.data.startswith("rsnz:"))
async def cb_snooze_reminder(callback: CallbackQuery, api, store):
    """«💤 Продлить» — сохраняем reminder_id в snooze-state, просим
    новое время через reply."""
    chat_id = callback.message.chat.id
    msg_id = callback.message.message_id
    reminder_id = (callback.data or "").split(":", 1)[1] if ":" in (callback.data or "") else ""

    # H1: validate UUID — иначе храним мусор в Redis и потом отдаём в API.
    if not _is_valid_uuid(reminder_id):
        try:
            await callback.answer("Сообщение устарело")
        except Exception:
            pass
        return

    # F4: invert order — edit_text first, store_snooze only on success.
    # Иначе: если edit упадёт, в Redis висит orphan reminder_snooze key
    # (TTL 1ч), и любой reply на этот msg_id будет ошибочно ловиться как
    # snooze-ответ.
    try:
        await callback.message.edit_text(
            _reply_prompt("💤 На сколько продлить?"),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"cb_snooze_reminder: edit_text failed, NOT storing state: {e}")
        try:
            await callback.answer("Не получилось — попробуй ещё раз")
        except Exception:
            pass
        return

    try:
        await store.store_reminder_snooze(chat_id, msg_id, reminder_id)
    except Exception as e:
        logger.warning(f"cb_snooze_reminder: store_snooze failed: {e}")

    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("rrok:"))
async def cb_recurring_ok(callback: CallbackQuery, api, store):
    """«✅ Ок» на регулярном срабатывании — принять этот раз, серия продолжается.

    Серверного действия не нужно: next_fire_at уже сдвинут материализатором.
    Просто убираем кнопки.
    """
    try:
        await callback.message.edit_text("✅", parse_mode=None)
    except Exception as e:
        logger.debug(f"cb_recurring_ok: edit_text failed: {e}")
    try:
        await callback.answer("Ок, напомню в следующий раз")
    except Exception:
        pass


@router.callback_query(F.data.startswith("rrstop:"))
async def cb_recurring_stop(callback: CallbackQuery, api, store):
    """«🛑 Больше не напоминать» — останавливаем серию через API."""
    from bot.common.auth import ensure_user

    recurring_id = (callback.data or "").split(":", 1)[1] if ":" in (callback.data or "") else ""

    # H1: callback_data — attacker-controlled. Валидируем как UUID до API.
    if not _is_valid_uuid(recurring_id):
        try:
            await callback.answer("Сообщение устарело")
        except Exception:
            pass
        return

    token = await ensure_user(callback, api)
    if not token:
        return

    stopped_ok = False
    try:
        await api.stop_recurring(token, recurring_id)
        stopped_ok = True
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 404:
            # Уже остановлена / повторный клик — считаем успехом.
            stopped_ok = True
        else:
            logger.warning(f"cb_recurring_stop: stop 5xx: {e}")
    except Exception as e:
        logger.warning(f"cb_recurring_stop: stop failed: {e}")

    if not stopped_ok:
        # 🛑 что молча не сработал = серия продолжит срабатывать. Делаем сбой
        # заметным: модальный alert (а не исчезающий тост) + error-лог.
        logger.error(
            "cb_recurring_stop: серия %s не остановлена — продолжит срабатывать",
            recurring_id,
        )
        try:
            await callback.answer(
                "Не получилось остановить — попробуй ещё раз", show_alert=True
            )
        except Exception:
            pass
        return

    try:
        await callback.message.edit_text("🛑 Больше не напоминаю", parse_mode=None)
    except Exception as e:
        logger.debug(f"cb_recurring_stop: edit_text failed: {e}")
    try:
        await callback.answer("Остановил")
    except Exception:
        pass
