"""Explicit /remind command + T8 inline trigger (q21 Step 2).

Extracted from ``_legacy.py``. Owns its own ``Router()``.

Public API (re-exported via package ``__init__``):
- ``cmd_remind`` — /remind aiogram handler
- ``process_explicit_remind_args`` — shared body (Phase 2.6 T8 inline trigger)
- ``REMIND_HELP_TEXT``

NL helpers (``split_remind_text_and_time``, ``extract_explicit_remind_body``,
``EXPLICIT_REMIND_PREFIX_RE``) now live in ``bot.common.nl`` — the single
public source. Imported here, not redefined.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.common import (
    HOUR_EXAMPLES,
    TIME_EXAMPLES,
    format_fire_at,
    get_user_tz_name,
    safe,
    split_remind_text_and_time,
)

from .shared import (
    _cap_text,
    _reply_prompt,
    _send_reminder_confirmation_with_chip,
    extract_first_datetime_entity,
)

logger = logging.getLogger(__name__)

router = Router()


REMIND_HELP_TEXT = (
    "❓ <b>Создание напоминания</b>\n\n"
    "<code>/remind &lt;текст&gt; &lt;когда&gt;</code>\n\n"
    "<b>Пример:</b>\n"
    "<code>/remind купить хлеб завтра в 9</code>\n"
    "<code>/remind позвонить маме в субботу</code>\n"
    "<code>/remind заплатить за квартиру 15.05</code>\n\n"
    "💡 <b>Когда:</b> завтра, через час, в субботу, 15.05, в 18:00, "
    "утром / вечером / ночью\n\n"
    "📋 <code>/reminders</code> — список активных + история"
)


async def process_explicit_remind_args(
    message: Message, args: str, api, store,
) -> None:
    """Общая логика explicit-remind (Phase 2.5 cmd_remind body, Phase 2.6 T8 trigger).

    Принимает уже извлечённые args (без префикса команды/триггера). Создаёт
    reminder если время есть, иначе просит Reply со временем.
    """
    from bot.common.auth import ensure_user
    from bot.services.nl_date import ParseStatus, parse

    args = args.strip()
    if not args:
        await message.answer(REMIND_HELP_TEXT, parse_mode="HTML")
        return

    token = await ensure_user(message, api)
    if not token:
        return

    user_tz_name = await get_user_tz_name(api, token)
    text_part, time_part = split_remind_text_and_time(args, user_tz_name)

    # E5: дата есть, текста нет («Напомни 25 мая») → спрашиваем «про что?»,
    # запоминаем дату; reply-текст реконструирует «<текст> <дата>».
    if time_part is not None and not text_part:
        prompt = await message.answer(
            _reply_prompt(
                f"📝 Про что напомнить <b>{safe(time_part)}</b>?",
                examples=None,
            ),
            parse_mode="HTML",
        )
        if prompt is not None and getattr(prompt, "message_id", None) is not None:
            try:
                await store.store_reminder_pending_need_text(
                    message.chat.id, prompt.message_id, _cap_text(time_part),
                )
            except Exception as e:
                logger.warning(f"explicit_remind need_text save failed: {e}")
        return

    if time_part is None:
        display_text = _cap_text(text_part or args, limit=200)
        prompt = await message.answer(
            _reply_prompt(f"🔔 Когда напомнить «<b>{safe(display_text)}</b>»?"),
            parse_mode="HTML",
        )
        if prompt is not None and getattr(prompt, "message_id", None) is not None:
            try:
                await store.store_reminder_pending_explicit(
                    message.chat.id, prompt.message_id,
                    _cap_text(text_part or args),
                )
                logger.info(
                    f"explicit_remind: pending saved chat={message.chat.id} "
                    f"msg={prompt.message_id} text={_cap_text(text_part or args, limit=40)!r}"
                )
            except Exception as e:
                logger.warning(f"explicit_remind: failed to save pending state: {e}")
        return

    entity_dt = extract_first_datetime_entity(message)
    if entity_dt is not None:
        now_utc = datetime.now(timezone.utc)
        if entity_dt < now_utc - timedelta(seconds=30):
            await message.answer(
                "Это в прошлом. Назначь время в будущем.", parse_mode=None,
            )
            return
        try:
            created = await api.create_reminder(
                token, entity_dt.isoformat(),
                bookmark_id=None,
                payload={"text": text_part, "source": "explicit_remind"},
            )
        except Exception as e:
            logger.warning(f"explicit_remind entity create failed: {e}")
            await message.answer(
                "Не получилось создать напоминание. Попробуй ещё раз.",
                parse_mode=None,
            )
            return
        await _send_reminder_confirmation_with_chip(
            message, entity_dt, text_part, user_tz_name,
            deduplicated=bool((created or {}).get("deduplicated")),
        )
        return

    parse_result = parse(time_part, user_tz=user_tz_name)

    if parse_result.status == ParseStatus.IN_PAST:
        await message.answer(
            "Это в прошлом. Назначь время в будущем.", parse_mode=None,
        )
        return

    if parse_result.status == ParseStatus.NEEDS_HOUR:
        # Дата есть (time_part = «25 мая» / «в субботу»), но без часа.
        # Сохраняем pending с date_phrase — reply «в 9» скомбинируется в
        # «<date> в 9». Иначе reply со временем терял бы дату и текст.
        display = _cap_text(text_part or args, limit=200)
        prompt = await message.answer(
            _reply_prompt(
                f"🔔 Напоминание <b>{safe(time_part)}</b>: "
                f"«<b>{safe(display)}</b>».\nВо сколько напомнить?",
                examples=HOUR_EXAMPLES,
            ),
            parse_mode="HTML",
        )
        if prompt is not None and getattr(prompt, "message_id", None) is not None:
            try:
                await store.store_reminder_pending_explicit(
                    message.chat.id, prompt.message_id,
                    _cap_text(text_part or args),
                    date_phrase=time_part,
                )
            except Exception as e:
                logger.warning(
                    f"explicit_remind NEEDS_HOUR pending save failed: {e}"
                )
        return

    if parse_result.status == ParseStatus.UNPARSEABLE or parse_result.dt is None:
        await message.answer(
            f"Не понял время «{safe(time_part)}». " + TIME_EXAMPLES,
            parse_mode="HTML",
        )
        return

    if parse_result.status == ParseStatus.FALLBACK_DEFAULT:
        proposed = format_fire_at(parse_result.dt, user_tz_name)
        prompt = await message.answer(
            f"Не понял точное время. Поставить «<b>{safe(text_part)}</b>» на "
            f"<b>{safe(proposed)}</b>?\n<b>Reply «да»</b> или укажи точнее.",
            parse_mode="HTML",
        )
        if prompt is not None and getattr(prompt, "message_id", None) is not None:
            try:
                await store.store_reminder_fallback(
                    message.chat.id, prompt.message_id,
                    kind="explicit_create",
                    target_id=_cap_text(text_part),
                    proposed_dt_iso=parse_result.dt.isoformat(),
                )
            except Exception as e:
                logger.warning(f"store_reminder_fallback failed: {e}")
        return

    try:
        created = await api.create_reminder(
            token,
            parse_result.dt.isoformat(),
            bookmark_id=None,
            payload={"text": text_part, "source": "explicit_remind"},
        )
    except Exception as e:
        logger.warning(f"explicit_remind create failed: {e}")
        await message.answer(
            "Не получилось создать напоминание. Попробуй ещё раз.",
            parse_mode=None,
        )
        return

    await _send_reminder_confirmation_with_chip(
        message, parse_result.dt, text_part, user_tz_name,
        deduplicated=bool((created or {}).get("deduplicated")),
    )


@router.message(Command("remind"))
async def cmd_remind(message: Message, command: CommandObject, api, store):
    """T11: explicit команда /remind для создания напоминания без AI/закладки.

    Phase 2.6: тело вынесено в `process_explicit_remind_args` для переиспользования
    в T8 inline-trigger из start.handle_text.
    """
    args = (command.args or "").strip()
    if not args:
        await message.answer(REMIND_HELP_TEXT, parse_mode="HTML")
        return
    await process_explicit_remind_args(message, args, api, store)
