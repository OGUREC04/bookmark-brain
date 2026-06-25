"""Reminders dispatcher + cron jobs (Phase 2.5) — package facade (split djtn).

Was a single 855-LOC ``scheduled.py``; split into focused submodules with the
public API preserved via re-export, so ``from app.worker.scheduled import X``
and ``from app.worker import X`` keep working unchanged:

- ``dispatcher.py``  — scheduled_dispatcher / auto_done_reminders + reminder
                       constants & text/keyboard helpers
- ``maintenance.py`` — nightly retries + one-shot backfill/reembed jobs
- ``nudge.py``       — stale_list_nudge (stale task-list morning ping)
- ``analytics.py``   — analytics_partition_maintenance (monthly partitions)

NOTE on ``mock.patch``: a patched name resolves where it is *looked up*, i.e. in
the submodule that performs the call — dispatcher-flow patches target
``app.worker.scheduled.dispatcher.*``, nudge patches ``...nudge.*``. Re-exporting
here does NOT make ``app.worker.scheduled.<name>`` a valid patch point.
"""

from __future__ import annotations

from .analytics import (
    ANALYTICS_RETENTION_MONTHS,
    _month_partition,
    analytics_partition_maintenance,
)
from .dispatcher import (
    AUTO_DONE_HOURS,
    DISPATCH_BATCH_SIZE,
    MAX_REMINDER_RETRIES,
    REMINDER_REDIS_TTL_SEC,
    REMINDER_RETRY_DELAY_MIN,
    STUCK_SENDING_THRESHOLD_MIN,
    _format_recurring_text,
    _format_reminder_text,
    _recurring_reminder_buttons,
    _reminder_buttons,
    _save_reminder_redis_state,
    auto_done_reminders,
    scheduled_dispatcher,
)
from .maintenance import (
    backfill_bookmark_links,
    reembed_all_bookmarks,
    reembed_bookmark_task,
    retry_failed_task,
    retry_partial_embeddings,
)
from .nudge import (
    _MAX_NUDGES_PER_USER_PER_RUN,
    stale_list_nudge,
)

__all__ = [
    "ANALYTICS_RETENTION_MONTHS",
    "AUTO_DONE_HOURS",
    "DISPATCH_BATCH_SIZE",
    "MAX_REMINDER_RETRIES",
    "REMINDER_REDIS_TTL_SEC",
    "REMINDER_RETRY_DELAY_MIN",
    "STUCK_SENDING_THRESHOLD_MIN",
    "_MAX_NUDGES_PER_USER_PER_RUN",
    "_format_recurring_text",
    "_format_reminder_text",
    "_month_partition",
    "_recurring_reminder_buttons",
    "_reminder_buttons",
    "_save_reminder_redis_state",
    "analytics_partition_maintenance",
    "auto_done_reminders",
    "backfill_bookmark_links",
    "reembed_all_bookmarks",
    "reembed_bookmark_task",
    "retry_failed_task",
    "retry_partial_embeddings",
    "scheduled_dispatcher",
    "stale_list_nudge",
]
