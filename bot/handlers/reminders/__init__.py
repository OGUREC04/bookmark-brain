"""Reminders handlers package (Phase 2.6 q21 split — complete).

Public facade. All historic external imports keep working:

    from bot.handlers.reminders import router, cmd_remind, strong_router, ...

Internal layout:
- ``shared.py``   — reminders-internal helpers (uuid validation, reply-prompt,
                    Telegram date_time entity extraction, MAX_* constants).
                    Cross-package infra (HTML-escape, tz / fire_at formatters,
                    NL splitters, TIME_EXAMPLES) lives in ``bot.common``.
- ``list.py``     — ``/reminders`` command + NL-reply (cancel/reschedule/history)
- ``explicit.py`` — ``/remind`` command + T8 inline trigger
- ``callbacks.py``— inline-button callbacks (rsk / rsn / rdone / rsnz)
- ``reply.py``    — reply-handler dispatch (fallback-confirm, pending, snooze)
- ``strong.py``   — T13 strong-intent flow (3-button «🔔 / 📝 / ✕») with
                    its OWN ``strong_router`` (registered separately in
                    ``bot/main.py`` before ``start.router``)

Each sub-file owns its own ``Router()``; the package-level ``router`` aggregates
all of them via ``include_router`` (native aiogram 3.x pattern).

See ``~/.claude/rules/common/coding-style.md`` (Migration of existing 1500+ LOC file)
and ``D:/brain/wiki/концепции/декомпозиция-больших-файлов.md`` for the rationale.
"""

from aiogram import Router as _Router

from .callbacks import (
    cb_create_reminder,
    cb_dismiss_reminder,
    cb_done_reminder,
    cb_recurring_ok,
    cb_recurring_stop,
    cb_snooze_reminder,
)
from .callbacks import router as _callbacks_router
from .explicit import (
    cmd_remind,
    process_explicit_remind_args,
)
from .explicit import router as _explicit_router
from .list import cmd_reminders, handle_reminders_list_reply
from .list import router as _list_router
from .repeat import cmd_repeat
from .repeat import router as _repeat_router
from .reply import handle_reminder_reply
from .reply import router as _reply_router
from .shared import (
    MAX_REMINDER_TEXT_LEN,
    _cap_text,
    _is_valid_uuid,
    extract_first_datetime_entity,
)
from .strong import (
    cb_strong_choice,
    handle_strong_intent_message,
    is_strong_intent,
    strong_router,
)

# Aggregate: each sub-file owns its Router; the package-level `router`
# includes them all via the native aiogram 3.x mechanism.
router = _Router()
router.include_router(_list_router)
router.include_router(_explicit_router)
router.include_router(_repeat_router)
router.include_router(_callbacks_router)
router.include_router(_reply_router)
# NOTE: strong_router is registered SEPARATELY in bot/main.py BEFORE start.router
# (it needs to intercept strong-intent before the regular text flow). Do NOT
# include it here, otherwise it would be invoked twice.

__all__ = [
    "MAX_REMINDER_TEXT_LEN",
    "_cap_text",
    "_is_valid_uuid",
    "cb_create_reminder",
    "cb_dismiss_reminder",
    "cb_done_reminder",
    "cb_recurring_ok",
    "cb_recurring_stop",
    "cb_snooze_reminder",
    "cb_strong_choice",
    "cmd_remind",
    "cmd_reminders",
    "cmd_repeat",
    "extract_first_datetime_entity",
    "handle_reminder_reply",
    "handle_reminders_list_reply",
    "handle_strong_intent_message",
    "is_strong_intent",
    "process_explicit_remind_args",
    "router",
    "strong_router",
]
