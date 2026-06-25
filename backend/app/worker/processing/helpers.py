"""Leaf helpers for the bookmark-processing job (processing split — djtn).

Reminder-intent detection, fire-and-forget task wrapper, semantic-link backfill
and the shared ``_PROCESS_MAX_TRIES`` constant. No Telegram I/O.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


# Единый источник правды для max_tries: WorkerSettings.max_tries импортирует
# эту константу. На последней попытке (job_try >= _PROCESS_MAX_TRIES) safety-net
# в process_bookmark_task ставит 👎 вместо застрявшего 👀.
_PROCESS_MAX_TRIES = 5


# Phase 2.7: формы reminder_decision, при которых сообщение — напоминание,
# а не закладка. Такие НЕ гоняем через general dedup: реминдер «купить хлеб
# завтра в 9» — действие во времени, а не дубль старой заметки про хлеб.
# Точные дубли реминдеров (тот же текст + минута) ловит E15 в create_reminder.
# Зеркалит исключение для task_list (_is_task_list_early). См. dedup×reminder bug.
_REMINDER_INTENT_FORMS = frozenset({
    "single_reminder",
    "composite_reminder",
    "needs_button_choice",
    "needs_hour",
    "strong_intent_3button",
})


def _has_reminder_intent(structured) -> bool:
    """True если у закладки есть reminder-intent (см. _REMINDER_INTENT_FORMS).

    Такие сообщения пропускают general dedup — иначе напоминание матчится
    как дубль старой заметки, реминдер не создаётся, а юзеру показывается
    бессмысленный алерт без даты/времени (bug 2026-05-24).
    """
    if not isinstance(structured, dict):
        return False
    decision = structured.get("reminder_decision")
    if not isinstance(decision, dict):
        return False
    return decision.get("form") in _REMINDER_INTENT_FORMS


def _spawn_bg(coro) -> None:
    """Fire-and-forget таск с логированием ошибок.

    Голый asyncio.create_task теряет исключение ("Task exception was never
    retrieved" в stderr, без записи в лог). Done-callback логирует фейл.
    """
    task = asyncio.create_task(coro)

    def _log_if_failed(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.warning("background task failed: %s", exc)

    task.add_done_callback(_log_if_failed)
async def _maybe_build_connections(session, bookmark) -> int:
    """Phase 5A: строит смысловые связи для заметки на сохранении (best-effort).

    0 вызовов LLM — чистый pgvector kNN (NFR-1). Эмбеддинг уже персистнут
    выше. Ошибка связывания НЕ должна влиять на обработку закладки. Возвращает
    число созданных рёбер (для логов/тестов).
    """
    if (
        bookmark is None
        or bookmark.embedding is None
        or bookmark.ai_status not in ("completed", "partial")
    ):
        return 0
    try:
        from app.services.connections import build_links_for_bookmark
        emb = (
            bookmark.embedding.tolist()
            if hasattr(bookmark.embedding, "tolist")
            else list(bookmark.embedding)
        )
        n = await build_links_for_bookmark(
            session, bookmark.id, bookmark.user_id, emb,
        )
        if n:
            await session.commit()
            logger.info(f"Connections: built {n} link(s) for {bookmark.id}")
        return n
    except Exception as e:  # noqa: BLE001 — best-effort, не валим обработку
        logger.debug(f"Connections link build failed: {e}")
        try:
            await session.rollback()
        except Exception:
            pass
        return 0
