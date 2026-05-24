"""Phase 2.6 — dispatch по reminder_decision (router output) (0dj).

No arq entrypoint. Used by ``processing.py`` before the legacy
``_maybe_offer_reminder`` fallback.

``_send_message`` / ``aioredis_from_url`` are looked up in THIS module;
``async_session`` is imported here too — worker-test patches that touch
this flow target ``app.worker.reminder_decision.*``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from app.config import get_settings
from app.database import async_session

from .reminder_offer import REMINDER_PENDING_TTL_SEC
from .telegram import _delete_message, _send_message, aioredis_from_url

logger = logging.getLogger(__name__)
settings = get_settings()


def _format_fire_at_local(fire_at: datetime, user_tz: str) -> str:
    """UTC datetime → строка `dd.MM HH:mm` в user_tz. Совпадает с /reminders."""
    from zoneinfo import ZoneInfo
    try:
        zone = ZoneInfo(user_tz)
    except Exception:
        zone = ZoneInfo("Europe/Moscow")
    local = fire_at.astimezone(zone)
    return local.strftime("%d.%m %H:%M")


def _confirmation_text_single(
    text: str, fire_at_local: str, deduplicated: bool = False,
) -> str:
    # E15: на дубле напоминание не создаётся заново — пишем «Уже напомню».
    prefix = "👌 Уже напомню" if deduplicated else "🔔 Напомню"
    return f"{prefix} «{(text or '').strip()[:80]}» — {fire_at_local}"


def _confirmation_text_per_item(count: int) -> str:
    word = "напоминание" if count == 1 else ("напоминания" if count < 5 else "напоминаний")
    return f"✅ Создал {count} {word} по пунктам списка."


def _choice_buttons(bookmark_id: str) -> dict:
    """3-button «📋 Список / 🔔 Напоминание / ✕» для NEEDS_BUTTON_CHOICE (T4).

    callback префиксы:
      rch_list:{bid}  — оставить как task_list + per-item reminder на dated
      rch_rem:{bid}   — composite reminder на весь текст
      rch_x:{bid}     — отмена, просто bookmark
    """
    return {
        "inline_keyboard": [
            [
                {"text": "📋 Список", "callback_data": f"rch_list:{bookmark_id}"},
                {"text": "🔔 Напоминание", "callback_data": f"rch_rem:{bookmark_id}"},
                {"text": "✕", "callback_data": f"rch_x:{bookmark_id}"},
            ]
        ]
    }


def _choice_text() -> str:
    return (
        "🤔 В сообщении одна дата, но несколько пунктов. Как лучше?\n\n"
        "• <b>📋 Список</b> — оставлю чекбоксы, напомню только по пункту с датой\n"
        "• <b>🔔 Напоминание</b> — одно напоминание про весь текст\n"
        "• <b>✕</b> — ничего, просто закладка"
    )


def _ask_hour_text() -> str:
    return (
        "🕘 Дата есть, но не указано время. Во сколько напомнить?\n\n"
        "↩️ <b>Сделай Reply</b> на это сообщение со временем "
        "(зажми/свайпни сообщение → «Ответить»).\n\n"
        "Примеры: <code>в 9</code>, <code>в 18:30</code>, <code>утром</code>, <code>вечером</code>"
    )


async def _mark_decision_applied_cas(session, bookmark_id, user_id) -> bool:
    """Атомарно выставляет `reminder_decision_applied=true` через CAS.

    Возвращает True если флаг был выставлен этим вызовом (т.е. мы первые
    обработчики). False если кто-то конкурентно успел раньше — caller'у
    нужно откатить создание reminder'ов чтобы не было дублей.

    Защищает от race между worker auto-create и API apply-decision на
    тот же bookmark (например, если retry'нувшийся worker догнал
    юзера-кликнувшего-3button).
    """
    from sqlalchemy import text as _sa_text
    res = await session.execute(_sa_text(
        """
        UPDATE bookmarks
        SET structured_data = COALESCE(structured_data, '{}'::jsonb)
                              || jsonb_build_object('reminder_decision_applied', true)
        WHERE id = CAST(:bid AS uuid)
          AND user_id = CAST(:uid AS uuid)
          AND COALESCE(structured_data->>'reminder_decision_applied', 'false') <> 'true'
        RETURNING id
        """
    ).bindparams(bid=str(bookmark_id), uid=str(user_id)))
    return res.scalar_one_or_none() is not None


async def _dispatch_reminder_decision(
    *,
    bookmark,
    chat_id: int | None,
) -> bool:
    """Phase 2.6: читает `structured_data.reminder_decision` и роутит в
    auto-create / 3-button UI / Reply-ask flow.

    Returns:
        True если decision был обработан (caller пропускает legacy
        `_maybe_offer_reminder`); False иначе.
    """
    if chat_id is None:
        return False

    structured = getattr(bookmark, "structured_data", None) or {}
    if not isinstance(structured, dict):
        return False
    raw_decision = structured.get("reminder_decision")
    if not isinstance(raw_decision, dict):
        return False

    # Idempotency: после успешного auto-create или apply-decision выставляется
    # флаг. Если bookmark ре-обрабатывается (retry_failed_task / manual reprocess),
    # не создаём дубли.
    if structured.get("reminder_decision_applied"):
        logger.info(
            "Phase 2.6 dispatch: decision already applied for bookmark %s, skipping",
            bookmark.id,
        )
        return True  # уже применено — legacy offer тоже не нужен

    form = raw_decision.get("form")
    items = raw_decision.get("items") or []
    dated = [i for i in items if i.get("fire_at_utc")]
    bookmark_id = str(bookmark.id)

    # ── AUTO-CREATE: TASK_LIST_WITH_REMINDERS ─────────────────────
    if form == "task_list_with_reminders":
        return await _auto_create_per_item(bookmark, chat_id, dated)

    # ── AUTO-CREATE: SINGLE_REMINDER ──────────────────────────────
    if form == "single_reminder" and dated:
        return await _auto_create_single(bookmark, chat_id, dated[0])

    # ── UI: NEEDS_BUTTON_CHOICE (3-button 📋/🔔/✕) ────────────────
    if form == "needs_button_choice":
        return await _send_choice_ui(bookmark_id, chat_id, raw_decision)

    # ── ASK: NEEDS_HOUR (Reply со временем) ───────────────────────
    if form == "needs_hour":
        return await _send_hour_ask(bookmark_id, chat_id)

    # STRONG_INTENT_3BUTTON / TASK_LIST_NO_REMINDERS / NONE — не наш кейс
    return False


async def _auto_create_per_item(bookmark, chat_id: int, dated: list[dict]) -> bool:
    """T5 auto: создаём по reminder'у на каждый dated item.

    Используем reminder_creator (см. backend/app/services/reminder_creator.py).
    Открываем отдельную сессию — process_bookmark_task уже закоммитил свою.
    """
    if not dated:
        return False
    from datetime import datetime, timezone

    from app.services.nl_date import ParseStatus
    from app.services.reminder_creator import create_per_item_reminders
    from app.services.reminder_router import ReminderForm, ResolvedItem, RouterDecision

    # Reconstruct decision из persisted dict (минимально для creator'а)
    resolved: list[ResolvedItem] = []
    for raw in dated:
        try:
            dt = datetime.fromisoformat(raw["fire_at_utc"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except (ValueError, KeyError):
            continue
        resolved.append(ResolvedItem(
            text=raw.get("text", ""),
            raw_date_phrase=raw.get("raw_date_phrase"),
            fire_at=dt,
            status=ParseStatus.OK,
        ))
    if not resolved:
        return False
    decision = RouterDecision(form=ReminderForm.TASK_LIST_WITH_REMINDERS, items=resolved)

    try:
        async with async_session() as session:
            # Reload bookmark в этой сессии. Дополнительный user_id-filter —
            # defense-in-depth (даже если job-id когда-то будет user-controlled).
            from app.models import Bookmark as _Bookmark
            res = await session.execute(
                select(_Bookmark).where(
                    _Bookmark.id == bookmark.id,
                    _Bookmark.user_id == bookmark.user_id,
                )
            )
            bm = res.scalar_one_or_none()
            if bm is None:
                return False
            # CAS-захват idempotency-флага ДО создания reminder'ов: если кто-то
            # уже применил decision (API endpoint / retry'нувшийся worker) —
            # выходим без создания, чтобы не плодить дубли.
            claimed = await _mark_decision_applied_cas(session, bm.id, bm.user_id)
            if not claimed:
                logger.info(
                    "auto per-item: bookmark %s already applied, skipping",
                    bm.id,
                )
                return True  # уже применено — dispatch handled
            created = await create_per_item_reminders(
                session, bm, decision, now=datetime.now(timezone.utc),
            )
            await session.commit()
        if created:
            asyncio.create_task(
                _send_message(chat_id, _confirmation_text_per_item(len(created)))
            )
            logger.info(
                "Phase 2.6 auto per-item: created %d reminders for bookmark %s",
                len(created), bookmark.id,
            )
        return True
    except Exception as e:
        logger.warning("auto per-item create failed for %s: %s", bookmark.id, e)
        return False


async def _auto_create_single(bookmark, chat_id: int, dated: dict) -> bool:
    """T-Phase2.6 auto: SINGLE_REMINDER без 3-button."""
    from datetime import datetime, timezone

    from app.services.nl_date import ParseStatus
    from app.services.reminder_creator import create_single_reminder
    from app.services.reminder_router import ResolvedItem

    try:
        dt = datetime.fromisoformat(dated["fire_at_utc"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, KeyError):
        return False

    item = ResolvedItem(
        text=dated.get("text", ""),
        raw_date_phrase=dated.get("raw_date_phrase"),
        fire_at=dt,
        status=ParseStatus.OK,
    )

    try:
        async with async_session() as session:
            from app.models import Bookmark as _Bookmark
            from app.services.reminder_creator import find_duplicate_reminder
            res = await session.execute(
                select(_Bookmark).where(
                    _Bookmark.id == bookmark.id,
                    _Bookmark.user_id == bookmark.user_id,
                )
            )
            bm = res.scalar_one_or_none()
            if bm is None:
                return False
            # E15: до создания проверяем, не дубль ли (тот же текст+минута) —
            # чтобы подтверждение было «👌 Уже напомню…», а не «🔔 Напомню…».
            is_dup = (await find_duplicate_reminder(
                session, bm.user_id, item.text, item.fire_at,
            )) is not None
            # CAS-захват флага до создания reminder'а (см. _auto_create_per_item).
            claimed = await _mark_decision_applied_cas(session, bm.id, bm.user_id)
            if not claimed:
                logger.info("auto single: bookmark %s already applied, skipping", bm.id)
                return True
            reminder = await create_single_reminder(
                session, bm, item,
                now=datetime.now(timezone.utc),
                source="single_reminder_auto",
            )
            # Поднимаем timezone в этой же сессии для confirmation message
            from app.models import User as _User
            tz_res = await session.execute(
                select(_User.timezone).where(_User.id == bm.user_id)
            )
            user_tz = tz_res.scalar_one_or_none() or "Europe/Moscow"
            await session.commit()
        if reminder is None:
            return False
        asyncio.create_task(_send_message(
            chat_id,
            _confirmation_text_single(
                item.text, _format_fire_at_local(dt, user_tz), deduplicated=is_dup,
            ),
        ))
        logger.info(
            "Phase 2.6 auto single: created reminder %s for bookmark %s",
            reminder.id, bookmark.id,
        )
        return True
    except Exception as e:
        logger.warning("auto single create failed for %s: %s", bookmark.id, e)
        return False


async def _send_choice_ui(bookmark_id: str, chat_id: int, raw_decision: dict) -> bool:
    """T4: шлём 3-button «📋/🔔/✕» и сохраняем state в Redis для click handler'а.

    Bot reads `reminder_choice:{chat_id}:{msg_id}` → bookmark_id и POSTит
    apply-decision endpoint.
    """
    text = _choice_text()
    buttons = _choice_buttons(bookmark_id)
    sent = await _send_message(chat_id, text, buttons)
    if not sent or not sent.get("message_id"):
        # Send упал — фоллбэкаемся на legacy offer, чтобы юзер хоть что-то
        # увидел.  Возврат False сигналит dispatcher'у запустить
        # _maybe_offer_reminder.
        return False
    msg_id = sent["message_id"]
    try:
        import json as _json
        r = aioredis_from_url(settings.REDIS_URL)
        try:
            # Сохраняем bookmark_id + items для composite_fire_at fallback
            payload = {
                "bookmark_id": bookmark_id,
                "items": raw_decision.get("items", []),
            }
            await r.set(
                f"reminder_choice:{chat_id}:{msg_id}",
                _json.dumps(payload),
                ex=REMINDER_PENDING_TTL_SEC,
            )
        finally:
            await r.aclose()
        logger.info(
            "Phase 2.6 NEEDS_BUTTON_CHOICE: sent 3-button for bookmark %s, msg %d",
            bookmark_id, msg_id,
        )
    except Exception as e:
        logger.warning("send_choice_ui: Redis state save failed for %s: %s", bookmark_id, e)
        # Если state не сохранён — кнопка broken. Удаляем сообщение.
        try:
            await _delete_message(chat_id, msg_id)
        except Exception:
            pass
    return True


async def _send_hour_ask(bookmark_id: str, chat_id: int) -> bool:
    """NEEDS_HOUR: шлём ask-message + сохраняем reminder_pending для reply-handler.

    Bot's `handle_reminder_reply` уже умеет читать reminder_pending state
    (Phase 2.5), мы переиспользуем тот же ключ.
    """
    text = _ask_hour_text()
    sent = await _send_message(chat_id, text)
    if not sent or not sent.get("message_id"):
        return False  # fallback в legacy offer (см. _send_choice_ui)
    msg_id = sent["message_id"]
    try:
        import json as _json
        r = aioredis_from_url(settings.REDIS_URL)
        try:
            await r.set(
                f"reminder_pending:{chat_id}:{msg_id}",
                _json.dumps({"kind": "bookmark", "bookmark_id": bookmark_id}),
                ex=REMINDER_PENDING_TTL_SEC,
            )
        finally:
            await r.aclose()
        logger.info(
            "Phase 2.6 NEEDS_HOUR: sent ask for bookmark %s, msg %d",
            bookmark_id, msg_id,
        )
    except Exception as e:
        logger.warning("send_hour_ask: Redis state save failed for %s: %s", bookmark_id, e)
        try:
            await _delete_message(chat_id, msg_id)
        except Exception:
            pass
    return True
