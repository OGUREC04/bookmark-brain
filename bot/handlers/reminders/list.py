"""`/reminders` command — list active + history + NL-reply management (T12 v2.1).

Extracted from ``_legacy.py`` as part of q21 Step 1.

Owns its own ``Router()``; aggregated by the package ``__init__`` via
``include_router``. Shared helpers (``_safe``, ``_format_fire_at``,
``_get_user_tz_name``, ``MAX_PARSE_INPUT_LEN``, ``TIME_EXAMPLES``) are still
imported from ``._legacy`` and will move to ``shared.py`` in a later step.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

import httpx
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ._legacy import (
    MAX_PARSE_INPUT_LEN,
    TIME_EXAMPLES,
    _format_fire_at,
    _get_user_tz_name,
    _safe,
)

logger = logging.getLogger(__name__)

router = Router()


def _format_reminder_short(rem: dict, tz_name: str) -> str:
    """Одна строка для /reminders: «купить хлеб — 11.05 09:00».

    Возвращает HTML-safe строку — текст напоминания экранирован
    (он может прийти из юзерского ввода и попасть в parse_mode=HTML).
    """
    payload = rem.get("payload") or {}
    text = (payload.get("text") or "").strip() or "(без текста)"
    if len(text) > 60:
        text = text[:57] + "..."
    fire_at_iso = rem.get("fire_at") or ""
    when = ""
    try:
        dt = datetime.fromisoformat(fire_at_iso.replace("Z", "+00:00"))
        when = _format_fire_at(dt, tz_name)
    except Exception:
        when = fire_at_iso
    return f"{_safe(text)} — {_safe(when)}"


@router.message(Command("reminders"))
async def cmd_reminders(message: Message, command: CommandObject, api, store):
    """T12: список активных reminder'ов или история (с аргументом «история»)."""
    from bot.handlers.start import _ensure_user

    token = await _ensure_user(message, api)
    if not token:
        return

    arg = (command.args or "").strip().lower()
    show_history = arg in ("история", "history")

    user_tz_name = await _get_user_tz_name(api, token)

    if show_history:
        try:
            data = await api.list_reminder_history(token, limit=20, days=30)
        except Exception as e:
            logger.warning(f"cmd_reminders history failed: {e}")
            await message.answer("Не получилось получить историю.", parse_mode=None)
            return
        items = data.get("items", []) if isinstance(data, dict) else []
        if not items:
            await message.answer(
                "📋 История пуста (за последние 30 дней).", parse_mode=None,
            )
            return
        lines = ["📋 <b>История</b> (последние 30 дней):\n"]
        for i, rem in enumerate(items, 1):
            status_icon = "✅" if rem.get("status") == "done" else "✕"
            lines.append(f"{i}. {status_icon} {_format_reminder_short(rem, user_tz_name)}")
        await message.answer("\n".join(lines), parse_mode="HTML")
        return

    # Активные
    try:
        data = await api.list_upcoming_reminders(token, limit=50)
    except Exception as e:
        logger.warning(f"cmd_reminders upcoming failed: {e}")
        await message.answer("Не получилось получить список.", parse_mode=None)
        return

    items = data.get("items", []) if isinstance(data, dict) else []
    if not items:
        await message.answer(
            "🔔 Активных напоминаний нет.\n\n"
            "Создать: <code>/remind &lt;текст&gt; &lt;когда&gt;</code>",
            parse_mode="HTML",
        )
        return

    lines = ["🔔 <b>Активные напоминания:</b>\n"]
    for i, rem in enumerate(items, 1):
        lines.append(f"{i}. {_format_reminder_short(rem, user_tz_name)}")
    lines.append(
        "\n<i>Reply на это сообщение:</i>\n"
        "• «отмени 1»\n"
        "• «перенеси 2 на завтра в 9»\n"
        "• «история» — выполненные"
    )

    sent = await message.answer("\n".join(lines), parse_mode="HTML")
    if sent is not None and getattr(sent, "message_id", None) is not None:
        # Snapshot IDs — порядок фиксируется
        ids = [str(rem.get("id")) for rem in items]
        try:
            await store.store_reminders_list_snapshot(
                message.chat.id, sent.message_id, ids,
            )
        except Exception as e:
            logger.warning(f"store_reminders_list_snapshot failed: {e}")


# Regex для NL-reply на /reminders
_REMINDERS_CANCEL_RE = re.compile(
    r"^\s*(?:отмен[ия]|удали)\s+(\d+)\s*$",
    re.IGNORECASE,
)
_REMINDERS_RESCHEDULE_RE = re.compile(
    r"^\s*(?:перенеси|продли|снузни|snooze)\s+(\d+)\s+на\s+(.+?)\s*$",
    re.IGNORECASE,
)
_REMINDERS_HISTORY_RE = re.compile(
    r"^\s*(?:истори[яю]|history)\s*$",
    re.IGNORECASE,
)


async def handle_reminders_list_reply(
    message: Message, api, store,
) -> bool:
    """NL-reply на сообщение /reminders.

    Returns True если обработано (наш reply), False иначе.
    """
    rt = message.reply_to_message
    if rt is None:
        return False

    chat_id = message.chat.id
    reply_to_id = rt.message_id

    snapshot = None
    try:
        snapshot = await store.get_reminders_list_snapshot(chat_id, reply_to_id)
    except Exception as e:
        logger.debug(f"get_reminders_list_snapshot failed: {e}")

    if not snapshot:
        return False  # не наш reply

    text = (message.text or "").strip()
    if len(text) > MAX_PARSE_INPUT_LEN:
        # Слишком длинный reply — точно не «отмени 1» / «перенеси 2 на ...».
        # Защита от M2 (длинный ввод в dateparser).
        return False

    # «история» — переключиться на историю
    if _REMINDERS_HISTORY_RE.match(text):
        from aiogram.filters import CommandObject as _CO
        # Эмулируем команду /reminders история
        fake_cmd = _CO(prefix="/", command="reminders", args="история")
        await cmd_reminders(message, fake_cmd, api, store)
        return True

    # «отмени N»
    m = _REMINDERS_CANCEL_RE.match(text)
    if m:
        idx = int(m.group(1)) - 1
        if idx < 0 or idx >= len(snapshot):
            await message.answer(
                f"Нет пункта {idx + 1} в списке. Сделай /reminders заново.",
                parse_mode=None,
            )
            return True
        rid = snapshot[idx]
        from bot.handlers.start import _ensure_user
        token = await _ensure_user(message, api)
        if not token:
            return True
        try:
            await api.cancel_reminder(token, rid)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                await message.answer(
                    "Этот пункт уже отменён или выполнен.", parse_mode=None,
                )
                return True
            await message.answer("Не получилось отменить.", parse_mode=None)
            return True
        except Exception:
            await message.answer("Не получилось отменить.", parse_mode=None)
            return True
        await message.answer(f"✕ Отменено: пункт {idx + 1}", parse_mode=None)
        return True

    # «перенеси N на ...»
    m = _REMINDERS_RESCHEDULE_RE.match(text)
    if m:
        idx = int(m.group(1)) - 1
        time_part = m.group(2).strip()[:MAX_PARSE_INPUT_LEN]  # M2 защита
        if idx < 0 or idx >= len(snapshot):
            await message.answer(
                f"Нет пункта {idx + 1} в списке.", parse_mode=None,
            )
            return True
        rid = snapshot[idx]
        from bot.handlers.start import _ensure_user
        from bot.services.nl_date import ParseStatus, parse
        token = await _ensure_user(message, api)
        if not token:
            return True
        user_tz_name = await _get_user_tz_name(api, token)
        result = parse(time_part, user_tz=user_tz_name)
        if result.status == ParseStatus.IN_PAST:
            await message.answer("Это в прошлом.", parse_mode=None)
            return True
        if result.status not in (ParseStatus.OK, ParseStatus.FALLBACK_DEFAULT) or result.dt is None:
            await message.answer(
                f"Не понял время «{_safe(time_part)}». " + TIME_EXAMPLES,
                parse_mode="HTML",
            )
            return True
        try:
            await api.update_reminder(token, rid, result.dt.isoformat())
        except Exception:
            await message.answer("Не получилось перенести.", parse_mode=None)
            return True
        when = _format_fire_at(result.dt, user_tz_name)
        await message.answer(
            f"💤 Перенесено на <b>{_safe(when)}</b>",
            parse_mode="HTML",
        )
        return True

    # Неизвестная команда — показываем подсказку, считаем reply нашим
    await message.answer(
        "Не понял. Reply: «отмени N» / «перенеси N на завтра в 9» / «история»",
        parse_mode=None,
    )
    return True
