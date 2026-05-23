"""Reply-handler — парсинг времени и dispatch (q21 Step 4).

Перехватываем reply-сообщения, направленные на reminder-prompt-ы
(«Когда напомнить?» / «На сколько продлить?» / fallback-confirm).

Owns its own ``Router()`` with a catch-all reply-message handler.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.types import Message

from bot.common import TIME_EXAMPLES, format_fire_at, get_user_tz_name, safe

from .list import handle_reminders_list_reply
from .shared import (
    _cap_text,
    extract_first_datetime_entity,
)

logger = logging.getLogger(__name__)

router = Router()


_FALLBACK_CONFIRM_YES = ("да", "ага", "ок", "окей", "yes", "y", "+", "подтверждаю")


async def _resave_pending(
    store, chat_id: int, new_msg_id, snooze_rid, pending_bid,
) -> None:
    """#7a: pending снимается GETDEL'ом ДО парсинга. Если время не
    распозналось — перекладываем тот же pending под сообщение-ошибку,
    чтобы reply со скорректированным временем на него снова сработал
    (раньше юзер застревал: «Не нашёл этот список»).
    """
    if not new_msg_id:
        return
    try:
        if snooze_rid:
            await store.store_reminder_snooze(chat_id, new_msg_id, snooze_rid)
        elif isinstance(pending_bid, dict):
            if pending_bid.get("kind") == "explicit":
                await store.store_reminder_pending_explicit(
                    chat_id, new_msg_id, pending_bid.get("text", ""),
                )
            else:
                await store.restore_reminder_pending(
                    chat_id, new_msg_id, pending_bid,
                )
    except Exception as e:
        logger.warning(f"_resave_pending failed: {e}")


async def handle_reminder_reply(message: Message, api, store) -> bool:
    """Обработка reply'я когда чат ждёт время от юзера.

    Возвращает True если reply распознан как reminder-related (не важно
    успешно или с ошибкой — просто чтобы вызывающий код не передавал в
    catch-all). False — этот reply нас не касается.
    """
    rt = message.reply_to_message
    if rt is None:
        return False

    chat_id = message.chat.id
    reply_to_id = rt.message_id

    # F2: confirm-state имеет приоритет над snooze/pending.
    fallback_state = None
    try:
        fallback_state = await store.get_reminder_fallback(chat_id, reply_to_id)
    except Exception as e:
        logger.debug(f"handle_reminder_reply: get_fallback failed: {e}")

    if fallback_state is not None:
        return await _handle_fallback_confirm_reply(
            message, api, store, fallback_state, reply_to_id,
        )

    snooze_rid = None
    try:
        snooze_rid = await store.pop_reminder_snooze(chat_id, reply_to_id)
    except Exception as e:
        logger.warning(f"handle_reminder_reply: pop_snooze failed: {e}")

    pending_bid = None
    if not snooze_rid:
        try:
            pending_bid = await store.pop_reminder_pending(chat_id, reply_to_id)
        except Exception as e:
            logger.warning(f"handle_reminder_reply: pop_pending failed: {e}")

    if snooze_rid or pending_bid:
        logger.info(
            f"handle_reminder_reply: matched chat={chat_id} reply_to={reply_to_id} "
            f"snooze={bool(snooze_rid)} pending_kind={pending_bid.get('kind') if isinstance(pending_bid, dict) else None}"
        )

    if not snooze_rid and not pending_bid:
        rt_text = (rt.text or rt.caption or "") if rt else ""
        looks_like_reminder_prompt = bool(
            rt_text and (
                "Когда напомнить" in rt_text
                or "На сколько продлить" in rt_text
                or "🔔" in rt_text
                or "💤" in rt_text
            )
        )
        logger.info(
            f"handle_reminder_reply: no state for chat={chat_id} reply_to={reply_to_id} "
            f"looks_like_prompt={looks_like_reminder_prompt} "
            f"user_text={(message.text or '')[:60]!r}"
        )
        if looks_like_reminder_prompt:
            await message.answer(
                "⏱ Это сообщение устарело (state протух или бот был "
                "перезапущен).\n\nПопробуй заново: <code>/remind &lt;текст&gt; "
                "&lt;когда&gt;</code> или /reminders.",
                parse_mode="HTML",
            )
            return True
        return False

    from bot.common.auth import ensure_user

    token = await ensure_user(message, api)
    if not token:
        logger.warning(
            f"handle_reminder_reply: ensure_user returned None for "
            f"chat={chat_id} user={message.from_user.id if message.from_user else None}"
        )
        await message.answer(
            "⚠️ Не удалось авторизоваться (backend недоступен?). "
            "Попробуй ещё раз через минуту.",
            parse_mode=None,
        )
        return True

    text = (message.text or "").strip()
    if not text:
        m = await message.answer(
            "Не понял время. " + TIME_EXAMPLES, parse_mode="HTML",
        )
        await _resave_pending(
            store, chat_id, getattr(m, "message_id", None),
            snooze_rid, pending_bid,
        )
        return True

    user_tz_name = await get_user_tz_name(api, token)
    entity_dt = extract_first_datetime_entity(message)
    if entity_dt is not None:
        now_utc = datetime.now(timezone.utc)
        if entity_dt < now_utc - timedelta(seconds=30):
            m = await message.answer(
                "Это в прошлом. Назначь время в будущем.", parse_mode=None,
            )
            await _resave_pending(
                store, chat_id, getattr(m, "message_id", None),
                snooze_rid, pending_bid,
            )
            return True
        if snooze_rid:
            kind_arg, target_arg = "snooze", snooze_rid
        elif isinstance(pending_bid, dict) and pending_bid.get("kind") == "explicit":
            kind_arg, target_arg = "explicit_create", pending_bid.get("text", "")
        else:
            kind_arg = "create"
            target_arg = (
                pending_bid.get("bookmark_id")
                if isinstance(pending_bid, dict) else None
            )
        return await _apply_reminder_action(
            message, api, store,
            kind=kind_arg,
            target_id=target_arg,
            fire_at_iso=entity_dt.isoformat(),
            user_tz_name=user_tz_name,
            confirm_msg_id=reply_to_id,
        )

    from bot.services.nl_date import ParseStatus, parse
    # Если pending несёт date_phrase («напомни 25 мая» без часа) — reply это
    # ЧАС; комбинируем «<date_phrase> <reply>» чтобы собрать полный момент.
    date_phrase = (
        pending_bid.get("date_phrase")
        if isinstance(pending_bid, dict) else None
    )
    parse_input = f"{date_phrase} {text}" if date_phrase else text
    result = parse(parse_input, user_tz=user_tz_name)

    if result.status == ParseStatus.UNPARSEABLE:
        m = await message.answer(
            "Не понял время. " + TIME_EXAMPLES, parse_mode="HTML",
        )
        await _resave_pending(
            store, chat_id, getattr(m, "message_id", None),
            snooze_rid, pending_bid,
        )
        return True
    if result.status == ParseStatus.IN_PAST:
        m = await message.answer(
            "Это в прошлом. Назначь время в будущем.",
            parse_mode=None,
        )
        await _resave_pending(
            store, chat_id, getattr(m, "message_id", None),
            snooze_rid, pending_bid,
        )
        return True
    if result.status == ParseStatus.NEEDS_TIME:
        m = await message.answer(
            "Уточни время (например «в 9» или «в 18:30»). " + TIME_EXAMPLES,
            parse_mode="HTML",
        )
        await _resave_pending(
            store, chat_id, getattr(m, "message_id", None),
            snooze_rid, pending_bid,
        )
        return True

    if result.status == ParseStatus.FALLBACK_DEFAULT and result.dt is not None:
        if snooze_rid:
            kind, target_id = "snooze", snooze_rid
        elif isinstance(pending_bid, dict) and pending_bid.get("kind") == "explicit":
            kind, target_id = "explicit_create", pending_bid.get("text", "")
        else:
            kind = "create"
            target_id = (
                pending_bid.get("bookmark_id")
                if isinstance(pending_bid, dict) else None
            )
        proposed = format_fire_at(result.dt, user_tz_name)
        prompt = await message.answer(
            f"Не понял точное время. Поставить на <b>{safe(proposed)}</b>?\n"
            f"<b>Reply «да»</b> — подтверждаю, или укажи время точнее "
            f"(например «через час», «завтра в 9»).",
            parse_mode="HTML",
        )
        if prompt is not None and getattr(prompt, "message_id", None) is not None:
            try:
                await store.store_reminder_fallback(
                    chat_id, prompt.message_id,
                    kind=kind, target_id=target_id,
                    proposed_dt_iso=result.dt.isoformat(),
                )
            except Exception as e:
                logger.warning(f"store_reminder_fallback failed: {e}")
        return True

    if result.dt is None:
        m = await message.answer(
            "Не понял время. " + TIME_EXAMPLES, parse_mode="HTML",
        )
        await _resave_pending(
            store, chat_id, getattr(m, "message_id", None),
            snooze_rid, pending_bid,
        )
        return True

    fire_at_iso = result.dt.isoformat()

    if snooze_rid:
        try:
            await api.update_reminder(token, snooze_rid, fire_at_iso)
        except Exception as e:
            logger.warning(f"update_reminder failed: {e}")
            await message.answer(
                "Не получилось продлить — нажми «💤 Продлить» ещё раз.",
                parse_mode=None,
            )
            return True

        await message.answer(
            f"💤 Продлено до <b>{safe(format_fire_at(result.dt, user_tz_name))}</b>",
            parse_mode="HTML",
        )
        return True

    explicit_text = None
    actual_bid = None
    if isinstance(pending_bid, dict):
        if pending_bid.get("kind") == "explicit":
            explicit_text = pending_bid.get("text", "")
        else:
            actual_bid = pending_bid.get("bookmark_id")

    payload = {
        "text": explicit_text if explicit_text else text,
        "source": "explicit_remind" if explicit_text else "implicit_weak",
    }

    try:
        await api.create_reminder(
            token,
            fire_at_iso,
            bookmark_id=actual_bid,
            payload=payload,
        )
    except Exception as e:
        logger.warning(f"create_reminder failed: {e}")
        await message.answer(
            "Не получилось создать напоминание — попробуй ещё раз через /remind.",
            parse_mode=None,
        )
        return True

    await message.answer(
        f"🔔 Напомню <b>{safe(format_fire_at(result.dt, user_tz_name))}</b>",
        parse_mode="HTML",
    )
    return True


async def _handle_fallback_confirm_reply(
    message: Message, api, store,
    fallback_state: dict,
    reply_to_id: int,
) -> bool:
    """F2: юзер reply'ит на «поставить на 11.05 22:00? да / уточни»."""
    from bot.common.auth import ensure_user
    from bot.services.nl_date import ParseStatus, parse

    chat_id = message.chat.id
    text = (message.text or "").strip()
    text_lower = text.lower()

    token = await ensure_user(message, api)
    if not token:
        return True

    kind = fallback_state.get("kind")
    target_id = fallback_state.get("target_id")
    dt_iso = fallback_state.get("dt_iso")

    if not target_id or not dt_iso or kind not in ("create", "snooze", "explicit_create"):
        try:
            await store.pop_reminder_fallback(chat_id, reply_to_id)
        except Exception:
            pass
        return True

    user_tz_name = await get_user_tz_name(api, token)

    is_confirm = any(text_lower == w or text_lower.startswith(w + " ") for w in _FALLBACK_CONFIRM_YES)

    if is_confirm:
        return await _apply_reminder_action(
            message, api, store, kind, target_id, dt_iso, user_tz_name,
            confirm_msg_id=reply_to_id,
        )

    result = parse(text, user_tz=user_tz_name)
    if result.status == ParseStatus.OK and result.dt is not None:
        return await _apply_reminder_action(
            message, api, store, kind, target_id, result.dt.isoformat(), user_tz_name,
            confirm_msg_id=reply_to_id,
        )

    if result.status == ParseStatus.IN_PAST:
        await message.answer("Это в прошлом. Назначь время в будущем.", parse_mode=None)
        return True

    if result.status == ParseStatus.NEEDS_TIME:
        await message.answer(
            "Уточни время (например «в 9» или «в 18:30»). " + TIME_EXAMPLES,
            parse_mode="HTML",
        )
        return True

    if result.status == ParseStatus.FALLBACK_DEFAULT and result.dt is not None:
        proposed = format_fire_at(result.dt, user_tz_name)
        prompt = await message.answer(
            f"Снова не понял. Поставить на <b>{safe(proposed)}</b>?\n"
            f"<b>Reply «да»</b> или укажи точнее.",
            parse_mode="HTML",
        )
        if prompt is not None and getattr(prompt, "message_id", None) is not None:
            try:
                await store.store_reminder_fallback(
                    chat_id, prompt.message_id,
                    kind=kind, target_id=target_id,
                    proposed_dt_iso=result.dt.isoformat(),
                )
                await store.pop_reminder_fallback(chat_id, reply_to_id)
            except Exception as e:
                logger.warning(f"fallback re-store failed: {e}")
        return True

    await message.answer(
        "Не понял. " + TIME_EXAMPLES + "\nИли reply «да» чтобы согласиться с прошлым временем.",
        parse_mode="HTML",
    )
    return True


async def _apply_reminder_action(
    message: Message, api, store,
    kind: str, target_id: str, fire_at_iso: str, user_tz_name: str,
    confirm_msg_id: int,
) -> bool:
    """Финальный create/update reminder + чистка fallback-state."""
    chat_id = message.chat.id

    from bot.common.auth import ensure_user
    token = await ensure_user(message, api)
    if not token:
        return True

    text_payload = _cap_text((message.text or "").strip())

    try:
        if kind == "snooze":
            await api.update_reminder(token, target_id, fire_at_iso)
        elif kind == "explicit_create":
            await api.create_reminder(
                token, fire_at_iso,
                bookmark_id=None,
                payload={"text": target_id, "source": "explicit_remind"},
            )
        else:  # create (implicit_weak fallback confirm)
            await api.create_reminder(
                token, fire_at_iso,
                bookmark_id=target_id,
                payload={"text": text_payload, "source": "implicit_weak"},
            )
    except Exception as e:
        logger.warning(f"_apply_reminder_action {kind} failed: {e}")
        await message.answer(
            "Не получилось — попробуй ещё раз.",
            parse_mode=None,
        )
        return True

    try:
        await store.pop_reminder_fallback(chat_id, confirm_msg_id)
    except Exception as e:
        logger.debug(f"pop_reminder_fallback failed: {e}")

    try:
        dt = datetime.fromisoformat(fire_at_iso)
    except Exception:
        dt = None

    when = format_fire_at(dt, user_tz_name) if dt else fire_at_iso
    label = "💤 Продлено до" if kind == "snooze" else "🔔 Напомню"
    await message.answer(f"{label} <b>{safe(when)}</b>", parse_mode="HTML")
    return True


@router.message(F.reply_to_message & F.text & ~F.text.startswith("/"))
async def _reply_dispatch(message: Message, api, store):
    """Перехватываем reply ДО tasks/start. Проверяем по приоритету:
    1. /reminders list NL-reply (отмени/перенеси/история по номеру)
    2. Reminder reply (создание/snooze/fallback-confirm)
    3. SkipHandler — событие падает дальше на tasks/start.
    """
    from aiogram.dispatcher.event.bases import SkipHandler

    try:
        handled = await handle_reminders_list_reply(message, api, store)
        if handled:
            return

        handled = await handle_reminder_reply(message, api, store)
        if handled:
            return
    except SkipHandler:
        raise
    except Exception as e:
        logger.exception(f"_reply_dispatch: handler raised: {e}")
        try:
            await message.answer(
                "⚠️ Внутренняя ошибка при обработке reply. Попробуй ещё раз "
                "или используй <code>/remind &lt;текст&gt; &lt;когда&gt;</code>.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        return

    raise SkipHandler()
