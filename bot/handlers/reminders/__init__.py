"""
Reminders handlers package (Phase 2.6 q21 split — Step 0).

This package is a facade over the legacy monolithic ``reminders.py`` (now
``_legacy.py``). All external imports keep working unchanged:

    from bot.handlers.reminders import router, cmd_remind, ...

Step 0 only creates the package shell; no code has moved yet. Subsequent
steps will extract domains into sub-modules (strong / explicit / callbacks
/ reply / list / keyboards / shared) and update the re-exports here.

See ``D:/projects/bookmark-brain/.beads/issues.jsonl`` issue ``q21``
and ``~/.claude/rules/common/coding-style.md`` "Migration of existing
1500+ LOC file" for the migration pattern.
"""

from ._legacy import (
    MAX_REMINDER_TEXT_LEN,
    _cap_text,
    _is_valid_uuid,
    _safe,
    cb_create_reminder,
    cb_dismiss_reminder,
    cb_done_reminder,
    cb_snooze_reminder,
    cb_strong_choice,
    extract_first_datetime_entity,
    handle_reminder_reply,
    handle_strong_intent_message,
    is_strong_intent,
)
from ._legacy import router as _legacy_router
from .explicit import (
    _split_remind_text_and_time,
    cmd_remind,
    extract_explicit_remind_body,
    process_explicit_remind_args,
)
from .explicit import router as _explicit_router
from .list import cmd_reminders, handle_reminders_list_reply
from .list import router as _list_router

# Aggregate: parent router includes legacy + sub-domain routers.
# This is the native aiogram 3.x pattern (each sub-file owns its Router).
from aiogram import Router as _Router

router = _Router()
router.include_router(_legacy_router)
router.include_router(_list_router)
router.include_router(_explicit_router)

__all__ = [
    "MAX_REMINDER_TEXT_LEN",
    "_cap_text",
    "_is_valid_uuid",
    "_safe",
    "_split_remind_text_and_time",
    "process_explicit_remind_args",
    "cb_create_reminder",
    "cb_dismiss_reminder",
    "cb_done_reminder",
    "cb_snooze_reminder",
    "cb_strong_choice",
    "cmd_remind",
    "cmd_reminders",
    "extract_explicit_remind_body",
    "extract_first_datetime_entity",
    "handle_reminder_reply",
    "handle_reminders_list_reply",
    "handle_strong_intent_message",
    "is_strong_intent",
    "router",
]
