"""Task-list handlers package (3po split — complete).

Public facade. All historic external imports keep working:

    from bot.handlers.tasks import router, cmd_todo, _try_fast_edit, ...

Internal layout:
- ``shared.py``         — UI rendering, keyboards, re-render-at-bottom,
                          ephemeral helpers, MSG_* constants (no router)
- ``fast_edit.py``      — regex fast-path NL edits + delete-list reply
                          (no router; called by nl_edit)
- ``commands.py``       — ``/todo`` command (own Router)
- ``task_callbacks.py`` — inline callbacks tg/tldm/tlds/tback/td/tn +
                          pinned-service-message cleaner (own Router)
- ``dedup.py``          — dm/dk callbacks, dedup intent + reply/pending
                          handlers (own Router)
- ``nl_edit.py``        — stale-list nudge, composite-reminder-on-list,
                          main reply NL-edit dispatcher (own Router)

Each sub-file owns its own ``Router()``; the package-level ``router``
aggregates them via ``include_router`` (native aiogram 3.x pattern).

See ``~/.claude/rules/common/coding-style.md`` (Migration of existing
1500+ LOC file) and ``bot/handlers/reminders/__init__.py`` for the
finished reference pattern.

Callback схема (лимит 64 байта):
  tg:{id}:{idx}   — toggle одной задачи
  tldm:{id}       — меню сроков (для всего списка)
  tlds:{id}:{c}   — установить срок всему списку (t/tm/w/n)
  tback:{id}      — вернуться из подменю
  td:{id}         — удалить весь список (bookmark + сообщение бота)
  tn:{id}         — (legacy) "не список" — откатить к обычной закладке
  dm:{id}         — dedup merge
  dk:{id}         — dedup keep
  tlc:{id}        — подтвердить создание списка (Да)
  tlx:{id}        — отказ: оставить обычной закладкой (Нет)
"""

from aiogram import Router as _Router

from .commands import cmd_todo, cmd_unpin_all
from .commands import router as _commands_router
from .confirm import cb_tasklist_confirm, cb_tasklist_decline
from .confirm import router as _confirm_router
from .convert import (
    cb_convert_to_list,
    cb_convert_to_reminder,
    saved_new_keyboard,
)
from .convert import router as _convert_router
from .dedup import (
    _apply_dedup_update,
    _handle_general_dedup_reply,
    _show_updated_task_list_after_dedup_update,
    cb_dedup_keep,
    cb_dedup_merge,
    handle_pending_dedup,
    parse_dedup_intent,
)
from .dedup import router as _dedup_router
from .fast_edit import (
    _handle_delete_via_reply,
    _is_delete_command,
    _parse_date,
    _parse_indices,
    _try_fast_edit,
)
from .lists import cb_lists_page, cmd_lists
from .lists import router as _lists_router
from .nl_edit import (
    _cleanup_failed_attempts,
    _handle_nudge_reply,
    _handle_remind_on_task_list,
    _parse_nudge_intent,
    msg_nl_edit_on_reply,
)
from .nl_edit import router as _nl_edit_router
from .shared import (
    EPHEMERAL_DELAY,
    MSG_DUP_DELETED,
    MSG_LIST_MERGED,
    MSG_MERGE_FAILED,
    MSG_ORIGINAL_UPDATED,
    MSG_SAVED_NEW,
    MSG_UPDATE_FAILED,
    _build_keyboard,
    _delete_after,
    _delete_after_by_id,
    _render_text,
    _rerender_at_bottom,
    send_and_autodelete,
)
from .task_callbacks import (
    cb_back,
    cb_delete_list,
    cb_list_deadline_menu,
    cb_list_deadline_set,
    cb_not_a_list,
    cb_toggle_task,
    on_pin_service_message,
)
from .task_callbacks import router as _task_callbacks_router

# Aggregate: each sub-file owns its Router; the package-level `router`
# includes them all via the native aiogram 3.x mechanism.
router = _Router()
router.include_router(_confirm_router)
router.include_router(_convert_router)
router.include_router(_task_callbacks_router)
router.include_router(_dedup_router)
router.include_router(_nl_edit_router)
router.include_router(_commands_router)
router.include_router(_lists_router)

__all__ = [
    "EPHEMERAL_DELAY",
    "MSG_DUP_DELETED",
    "MSG_LIST_MERGED",
    "MSG_MERGE_FAILED",
    "MSG_ORIGINAL_UPDATED",
    "MSG_SAVED_NEW",
    "MSG_UPDATE_FAILED",
    "_apply_dedup_update",
    "_build_keyboard",
    "_cleanup_failed_attempts",
    "_delete_after",
    "_delete_after_by_id",
    "_handle_delete_via_reply",
    "_handle_general_dedup_reply",
    "_handle_nudge_reply",
    "_handle_remind_on_task_list",
    "_is_delete_command",
    "_parse_date",
    "_parse_indices",
    "_parse_nudge_intent",
    "_render_text",
    "_rerender_at_bottom",
    "_show_updated_task_list_after_dedup_update",
    "_try_fast_edit",
    "cb_back",
    "cb_convert_to_list",
    "cb_convert_to_reminder",
    "cb_dedup_keep",
    "cb_dedup_merge",
    "cb_delete_list",
    "cb_lists_page",
    "cb_tasklist_confirm",
    "cb_tasklist_decline",
    "cb_list_deadline_menu",
    "cb_list_deadline_set",
    "cb_not_a_list",
    "cb_toggle_task",
    "cmd_lists",
    "cmd_todo",
    "cmd_unpin_all",
    "handle_pending_dedup",
    "msg_nl_edit_on_reply",
    "saved_new_keyboard",
    "on_pin_service_message",
    "parse_dedup_intent",
    "router",
    "send_and_autodelete",
]
