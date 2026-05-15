"""Explicit /remind command + T8 inline trigger (q21 Step 2).

Extracted from ``_legacy.py``. Owns its own ``Router()``.

Public API (re-exported via package ``__init__``):
- ``cmd_remind`` — /remind aiogram handler
- ``process_explicit_remind_args`` — shared body (Phase 2.6 T8 inline trigger)
- ``extract_explicit_remind_body`` — detects «сделай напоминание ...» prefix
- ``_split_remind_text_and_time`` — heuristic splitter
- ``REMIND_HELP_TEXT``
- ``_EXPLICIT_REMIND_PREFIX_RE``
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ._legacy import (
    DEFAULT_TZ,
    TIME_EXAMPLES,
    _cap_text,
    _format_fire_at,
    _get_user_tz_name,
    _reply_prompt,
    _safe,
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


def _split_remind_text_and_time(
    args: str, user_tz: str = DEFAULT_TZ,
) -> tuple[str, str | None]:
    """Разделяет аргументы /remind на текст напоминания и временную часть.

    Стратегия: пробуем парсить ВСЁ как время — если ParseStatus.OK,
    значит времени нет (всё - время). Иначе ищем временную фразу с конца:
    последние 2-5 токенов отдаём парсеру, если OK — это время, остальное
    — текст. Если ничего не парсится — весь ввод считается текстом без
    времени.

    Возвращает (text, time_part_or_None).
    """
    from bot.services.nl_date import ParseStatus, parse

    args = args.strip()
    if not args:
        return "", None

    tokens = args.split()
    n = len(tokens)

    # Эвристика: пробуем БÓЛЬШЕЕ окно с конца (5..1 токенов).
    # Учитываем OK И IN_PAST как «time match» — иначе «вчера в 9» (3 токена)
    # пропускается потому что «в 9» (2 токена) парсится в OK раньше.
    # IN_PAST потом ловится в cmd_remind с осмысленным сообщением юзеру.
    valid_statuses = (ParseStatus.OK, ParseStatus.IN_PAST)
    for window in range(min(5, n), 0, -1):
        time_part = " ".join(tokens[n - window:])
        text_part = " ".join(tokens[: n - window])
        result = parse(time_part, user_tz=user_tz)
        if result.status in valid_statuses and text_part:
            return text_part.strip(), time_part.strip()

    # Время не найдено — весь ввод как текст.
    return args, None


# Phase 2.6 T8: префикс explicit-команды «сделай напоминание <body>» / «напомни <body>».
# Используется и start.handle_text (inline trigger), и могут быть будущие
# точки входа. Капчуем сам префикс с группой 'body' через extract_explicit_body().
#
# Принципы:
# - Только начало строки (^) — слово в середине предложения НЕ триггер
# - После триггера требуем whitespace или конец строки — «напомни-ка» НЕ матчится
#   (защита от частицы «-ка» которая иначе попала бы в body)
# - «напомнить/напоминаешь/напоминалось» (другие формы глагола) — не матчятся
#   потому что после «напомни» стоит word-char, граница \b не срабатывает
_EXPLICIT_REMIND_PREFIX_RE = re.compile(
    r"^(?:сделай\s+напомин\w+|поставь\s+(?:напомин\w+|reminder)|"
    r"напомни(?:\s+мне)?|создай\s+напомин\w+)"
    r"(?=\s|$|[:,.])"   # дальше пробел/конец/допустимая пунктуация — НЕ дефис/буква
    r"[\s:,.]*",        # съедаем разделитель (без дефиса)
    re.IGNORECASE,
)


def extract_explicit_remind_body(text: str) -> str | None:
    """Если text начинается с «сделай напоминание …» — возвращает «...» (что напомнить).

    Возвращает None если префикс не матчится.
    Возвращает пустую строку если префикс есть, но body пустой («напомни») —
    caller сам спросит юзера что напомнить.
    """
    if not text:
        return None
    m = _EXPLICIT_REMIND_PREFIX_RE.match(text.strip())
    if m is None:
        return None
    return text.strip()[m.end():].strip()


async def process_explicit_remind_args(
    message: Message, args: str, api, store,
) -> None:
    """Общая логика explicit-remind (Phase 2.5 cmd_remind body, Phase 2.6 T8 trigger).

    Принимает уже извлечённые args (без префикса команды/триггера). Создаёт
    reminder если время есть, иначе просит Reply со временем.
    """
    from bot.handlers.start import _ensure_user
    from bot.services.nl_date import ParseStatus, parse

    args = args.strip()
    if not args:
        await message.answer(REMIND_HELP_TEXT, parse_mode="HTML")
        return

    token = await _ensure_user(message, api)
    if not token:
        return

    user_tz_name = await _get_user_tz_name(api, token)
    text_part, time_part = _split_remind_text_and_time(args, user_tz_name)

    if time_part is None:
        display_text = _cap_text(text_part or args, limit=200)
        prompt = await message.answer(
            _reply_prompt(f"🔔 Когда напомнить «<b>{_safe(display_text)}</b>»?"),
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
            await api.create_reminder(
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
        )
        return

    parse_result = parse(time_part, user_tz=user_tz_name)

    if parse_result.status == ParseStatus.IN_PAST:
        await message.answer(
            "Это в прошлом. Назначь время в будущем.", parse_mode=None,
        )
        return

    if parse_result.status == ParseStatus.NEEDS_HOUR:
        await message.answer(
            "Уточни время (например «в 9»). " + TIME_EXAMPLES,
            parse_mode="HTML",
        )
        return

    if parse_result.status == ParseStatus.UNPARSEABLE or parse_result.dt is None:
        await message.answer(
            f"Не понял время «{_safe(time_part)}». " + TIME_EXAMPLES,
            parse_mode="HTML",
        )
        return

    if parse_result.status == ParseStatus.FALLBACK_DEFAULT:
        proposed = _format_fire_at(parse_result.dt, user_tz_name)
        prompt = await message.answer(
            f"Не понял точное время. Поставить «<b>{_safe(text_part)}</b>» на "
            f"<b>{_safe(proposed)}</b>?\n<b>Reply «да»</b> или укажи точнее.",
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
        await api.create_reminder(
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
