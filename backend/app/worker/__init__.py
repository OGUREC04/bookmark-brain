"""Worker package (0dj split — complete).

Public facade for the arq worker. All historic external imports keep working:

    from app.worker import WorkerSettings, process_bookmark_task, ...

Internal layout (facade-with-re-export pattern, same as
``bot/handlers/tasks/`` and ``bot/handlers/reminders/``):

- ``telegram.py``          — low-level Telegram Bot API + Redis helpers
                             (``aioredis_from_url``, ``_send_message``, …)
- ``dedup.py``             — dedup-alert + first-task-list-tip helpers
- ``reminder_offer.py``    — T8 legacy «Создать напоминание?» offer
- ``reminder_decision.py`` — Phase 2.6 reminder_decision dispatch
- ``scheduled.py``         — cron jobs (dispatcher / auto-done / retries /
                             nudge) + reminder constants
- ``processing.py``        — the main arq job ``process_bookmark_task``

The arq entrypoint is ``WorkerSettings`` (defined here, wiring the actual
coroutine objects imported from the sub-modules).

NOTE on ``mock.patch``: tests patch INTERNAL names on this package
(``app.worker._send_message``, ``app.worker.async_session``,
``app.worker.aioredis_from_url``). Python resolves patched names where they
are *looked up*, not where re-exported. After the split, worker-test patches
were retargeted to the sub-module that performs the call, e.g.
``app.worker.scheduled._send_message`` /
``app.worker.reminder_offer.aioredis_from_url``. See the test files for the
exact retargets.
"""

from __future__ import annotations

from arq import cron
from arq.connections import RedisSettings

from app.config import get_settings

from .dedup import (
    _build_dedup_alert,
    _maybe_send_first_task_list_tip,
    _store_dedup_alert,
    _store_general_dedup,
)
from .processing import (
    _PROCESS_MAX_TRIES,
    _result_buttons,
    process_bookmark_task,
    redispatch_reminder_task,
)
from .reminder_decision import (
    _ask_hour_text,
    _auto_create_per_item,
    _auto_create_single,
    _choice_buttons,
    _choice_text,
    _confirmation_text_per_item,
    _confirmation_text_single,
    _dispatch_reminder_decision,
    _format_fire_at_local,
    _mark_decision_applied_cas,
    _send_choice_ui,
    _send_hour_ask,
)
from .reminder_offer import (
    REMINDER_PENDING_TTL_SEC,
    _maybe_offer_reminder,
    _reminder_offer_buttons,
    _reminder_offer_text,
)
from .scheduled import (
    AUTO_DONE_HOURS,
    DISPATCH_BATCH_SIZE,
    MAX_REMINDER_RETRIES,
    REMINDER_REDIS_TTL_SEC,
    REMINDER_RETRY_DELAY_MIN,
    STUCK_SENDING_THRESHOLD_MIN,
    _format_reminder_text,
    _reminder_buttons,
    _save_reminder_redis_state,
    analytics_partition_maintenance,
    auto_done_reminders,
    backfill_bookmark_links,
    retry_failed_task,
    retry_partial_embeddings,
    scheduled_dispatcher,
    stale_list_nudge,
)
from .telegram import (
    BOT_API,
    _bind_task_list_message,
    _delete_message,
    _edit_message,
    _pin_message,
    _send_ephemeral,
    _send_message,
    _set_reaction,
    aioredis_from_url,
)

settings = get_settings()


class WorkerSettings:
    functions = [
        process_bookmark_task,
        redispatch_reminder_task,
        backfill_bookmark_links,  # Phase 5A one-shot (enqueue вручную)
    ]
    cron_jobs = [
        cron(retry_failed_task, hour=3, minute=0),
        cron(retry_partial_embeddings, hour=5, minute=0),
        cron(stale_list_nudge, hour=settings.NUDGE_HOUR_UTC, minute=0),
        # Phase 2.5 Reminders MVP
        # Каждую минуту проверяем due reminder'ы. set() = «каждую минуту любого часа».
        cron(scheduled_dispatcher, minute=set(range(60)), run_at_startup=False),
        # Раз в час, в :15 (чтобы не совпадало с пиком dispatcher на :00)
        cron(auto_done_reminders, minute={15}, run_at_startup=False),
        # Phase M1: катим месячные партиции analytics_events + retention.
        # run_at_startup=True — гарантируем что партиции есть сразу.
        cron(analytics_partition_maintenance, hour=4, minute=30, run_at_startup=True),
    ]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 5
    # Явно задаём (а не полагаемся на дефолт arq): safety-net в processing.py
    # ставит 👎 на попытке job_try >= _PROCESS_MAX_TRIES. Единый источник правды.
    max_tries = _PROCESS_MAX_TRIES
    job_timeout = 120


__all__ = [
    "AUTO_DONE_HOURS",
    "BOT_API",
    "DISPATCH_BATCH_SIZE",
    "MAX_REMINDER_RETRIES",
    "REMINDER_PENDING_TTL_SEC",
    "REMINDER_REDIS_TTL_SEC",
    "REMINDER_RETRY_DELAY_MIN",
    "STUCK_SENDING_THRESHOLD_MIN",
    "WorkerSettings",
    "_ask_hour_text",
    "_auto_create_per_item",
    "_auto_create_single",
    "_bind_task_list_message",
    "_build_dedup_alert",
    "_choice_buttons",
    "_choice_text",
    "_confirmation_text_per_item",
    "_confirmation_text_single",
    "_delete_message",
    "_dispatch_reminder_decision",
    "_edit_message",
    "_format_fire_at_local",
    "_format_reminder_text",
    "_mark_decision_applied_cas",
    "_maybe_offer_reminder",
    "_maybe_send_first_task_list_tip",
    "_pin_message",
    "_reminder_buttons",
    "_reminder_offer_buttons",
    "_reminder_offer_text",
    "_result_buttons",
    "_save_reminder_redis_state",
    "_send_choice_ui",
    "_send_ephemeral",
    "_send_hour_ask",
    "_send_message",
    "_set_reaction",
    "_store_dedup_alert",
    "_store_general_dedup",
    "aioredis_from_url",
    "analytics_partition_maintenance",
    "auto_done_reminders",
    "backfill_bookmark_links",
    "process_bookmark_task",
    "redispatch_reminder_task",
    "retry_failed_task",
    "retry_partial_embeddings",
    "scheduled_dispatcher",
    "stale_list_nudge",
]
