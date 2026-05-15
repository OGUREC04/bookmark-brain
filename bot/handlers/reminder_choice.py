"""Phase 2.6 T4 — callbacks 3-button «📋 Список / 🔔 Напоминание / ✕».

Worker отправляет эти кнопки когда router вернул form=needs_button_choice
(1 дата + multi-item). State хранится в Redis ключом
`reminder_choice:{chat_id}:{msg_id}` со shape:
    {"bookmark_id": "<uuid>", "items": [{...resolved}]}

Юзер кликает:
  • rch_list:{bid}  — оставить task_list + per-item reminder на dated item
  • rch_rem:{bid}   — composite reminder на весь текст
  • rch_x:{bid}     — отмена, просто bookmark

Все 3 ветки идут через POST /api/v1/reminders/apply-decision/{bid}?form=...
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)

router = Router()


def _is_valid_uuid(s: str | None) -> bool:
    """Защита от инъекции в callback_data — строгая валидация UUID.

    Использует stdlib `uuid.UUID()` чтобы:
      - проверить структуру 8-4-4-4-12 с дефисами на правильных позициях
      - отсечь «36 дефисов» / «36 нулей в hex» которые проходят простой regex
    """
    if not s or len(s) != 36:
        return False
    import uuid as _uuid
    try:
        _uuid.UUID(s)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


async def _pop_choice_state(store, chat_id: int, msg_id: int) -> dict | None:
    """Atomic GETDEL state для chat:msg. None если нет / истёк."""
    try:
        return await store.pop_reminder_choice(chat_id, msg_id)
    except Exception as e:
        logger.warning("reminder_choice state pop failed: %s", e)
        return None


def _first_fire_at_iso(items: list[dict]) -> str | None:
    """Берём fire_at_utc первого item с датой."""
    for it in items or []:
        fa = it.get("fire_at_utc")
        if fa:
            return fa
    return None


@router.callback_query(F.data.startswith("rch_list:"))
async def cb_choice_list(callback: CallbackQuery, api, store):
    """📋 Список → apply-decision form=task_list_with_reminders."""
    await _handle_choice(callback, api, store, form="task_list_with_reminders")


@router.callback_query(F.data.startswith("rch_rem:"))
async def cb_choice_reminder(callback: CallbackQuery, api, store):
    """🔔 Напоминание → apply-decision form=composite_reminder.

    composite_fire_at = первый dated item из state (router положил туда).
    """
    await _handle_choice(callback, api, store, form="composite_reminder")


@router.callback_query(F.data.startswith("rch_x:"))
async def cb_choice_dismiss(callback: CallbackQuery, api, store):
    """✕ → ничего не создаём, удаляем prompt."""
    if not callback.message:
        await callback.answer()
        return
    try:
        await _pop_choice_state(store, callback.message.chat.id, callback.message.message_id)
    except Exception as e:
        logger.debug("rch_x: pop state failed: %s", e)
    try:
        await callback.message.delete()
    except Exception as e:
        logger.debug("rch_x: delete prompt failed: %s", e)
    await callback.answer("Ок, без напоминания")


async def _handle_choice(callback: CallbackQuery, api, store, *, form: str) -> None:
    """Общая обработка 📋/🔔 — читаем state, POST apply-decision, edit prompt."""
    from bot.handlers.start import _ensure_user

    if callback.message is None or callback.data is None:
        await callback.answer()
        return

    chat_id = callback.message.chat.id
    msg_id = callback.message.message_id
    bookmark_id = callback.data.split(":", 1)[1] if ":" in callback.data else ""
    if not _is_valid_uuid(bookmark_id):
        logger.warning("rch: bad bookmark_id in callback_data: %r", callback.data)
        await callback.answer("Странный bookmark_id, попробуй заново")
        return

    # Atomic pop state (anti-double-click)
    state = await _pop_choice_state(store, chat_id, msg_id)
    if state is None:
        await callback.answer("Состояние устарело, попробуй ещё раз через /todo")
        try:
            await callback.message.delete()
        except Exception:
            pass
        return

    # bookmark_id из state — авторитативный источник; callback_data —
    # доп. проверка (защита от click на чужой prompt в случае race).
    if state.get("bookmark_id") != bookmark_id:
        logger.warning(
            "rch: bookmark_id mismatch state=%s callback=%s",
            state.get("bookmark_id"), bookmark_id,
        )
        await callback.answer("Mismatch state")
        return

    # Token + apply-decision
    token = await _ensure_user(callback.message, api)
    if not token:
        await callback.answer("Не получилось авторизоваться")
        return

    composite_fire_at = None
    if form == "composite_reminder":
        from datetime import datetime as _dt
        raw_fire = _first_fire_at_iso(state.get("items", []))
        if raw_fire:
            try:
                _dt.fromisoformat(raw_fire)  # validate, не сохраняем результат
                composite_fire_at = raw_fire
            except ValueError:
                logger.warning(
                    "rch: bad composite_fire_at %r in state for %s",
                    raw_fire, bookmark_id,
                )
                await callback.answer("Дата повреждена, попробуй создать через /remind")
                return

    try:
        result = await api.apply_reminder_decision(
            token=token,
            bookmark_id=bookmark_id,
            form=form,
            composite_fire_at=composite_fire_at,
        )
    except Exception as e:
        logger.warning("rch: apply-decision failed for %s: %s", bookmark_id, e)
        await callback.answer("Не получилось создать напоминание")
        return

    created_count = result.get("total", 0) if isinstance(result, dict) else 0
    label = "📋 Список" if form == "task_list_with_reminders" else "🔔 Напоминание"
    try:
        await callback.message.edit_text(
            f"✅ {label} — создал {created_count} напомин"
            + ("ание" if created_count == 1 else ("ания" if created_count < 5 else "аний"))
            + ".",
            reply_markup=None,
        )
    except Exception as e:
        logger.debug("rch: edit_text failed: %s", e)
    await callback.answer()
