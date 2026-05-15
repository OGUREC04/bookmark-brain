"""Phase 2.6 — фабрика reminder'ов из RouterDecision.

Покрывает 3 кейса создания (T5, T6, SINGLE_REMINDER auto):

  • `create_per_item_reminders` — TASK_LIST_WITH_REMINDERS:
      по одному ScheduledMessage на каждый item с fire_at != None.
      payload = {text, task_list_id, item_index, source='task_list_per_item'}
  • `create_composite_reminder` — COMPOSITE_REMINDER:
      один ScheduledMessage с полным текстом сообщения.
      payload = {text, source='composite_reminder'}
  • `create_single_reminder` — SINGLE_REMINDER:
      один ScheduledMessage с текстом item'а.
      payload = {text, source}

Все функции — pure save: коммитом управляет caller. Idempotency предполагается
на уровне caller'а (worker запускается на каждом bookmark один раз через arq).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bookmark, ScheduledMessage
from app.services.reminder_router import ResolvedItem, RouterDecision

logger = logging.getLogger(__name__)

REMINDER_KIND = "reminder"

# Допуск на латентность парсинга / round-trip от AI до БД. Без него reminder'ы
# созданные «через минуту» рискуют попасть в условие fire_at<=now к моменту
# первого SELECT из dispatcher'а.
_VALIDATE_FUTURE_TOLERANCE = timedelta(seconds=5)


def _validate_future(fire_at: datetime, now: datetime) -> bool:
    """fire_at должен быть в будущем (минус 5 сек tolerance)."""
    if fire_at.tzinfo is None:
        # Defense in depth: route() возвращает UTC-aware, но если кто-то
        # передал naive — не создаём, чтобы не положить в БД мусор.
        return False
    return fire_at > now - _VALIDATE_FUTURE_TOLERANCE


def _build_per_item_payload(
    *,
    text: str,
    task_list_id: UUID,
    item_index: int,
) -> dict:
    return {
        "text": text,
        "source": "task_list_per_item",
        "task_list_id": str(task_list_id),
        "item_index": item_index,
    }


def _build_composite_payload(*, text: str) -> dict:
    return {"text": text, "source": "composite_reminder"}


def _build_single_payload(*, text: str, source: str) -> dict:
    return {"text": text, "source": source}


async def create_per_item_reminders(
    session: AsyncSession,
    bookmark: Bookmark,
    decision: RouterDecision,
    *,
    now: datetime,
) -> list[ScheduledMessage]:
    """Для TASK_LIST_WITH_REMINDERS: создаём по reminder'у на каждый item с датой.

    `decision.items` сохраняет порядок из AI → item_index = позиция в массиве.
    Пункты без fire_at пропускаются, item_index у них тоже не задаётся
    (cascade в T9 ищет по task_list_id + item_index среди items с reminder'ом).

    Returns: список созданных ScheduledMessage (для логирования).
    """
    created: list[ScheduledMessage] = []
    for idx, item in enumerate(decision.items):
        if item.fire_at is None:
            continue
        if not _validate_future(item.fire_at, now):
            logger.warning(
                "create_per_item: skipping item[%d] of bookmark %s — "
                "fire_at %s not in future (now=%s)",
                idx, bookmark.id, item.fire_at, now,
            )
            continue
        payload = _build_per_item_payload(
            text=item.text,
            task_list_id=bookmark.id,
            item_index=idx,
        )
        reminder = ScheduledMessage(
            user_id=bookmark.user_id,
            bookmark_id=bookmark.id,
            kind=REMINDER_KIND,
            fire_at=item.fire_at,
            status="pending",
            payload=payload,
        )
        session.add(reminder)
        created.append(reminder)
    if created:
        await session.flush()
    return created


async def create_composite_reminder(
    session: AsyncSession,
    bookmark: Bookmark,
    *,
    fire_at: datetime,
    now: datetime,
    text: str | None = None,
) -> ScheduledMessage | None:
    """Для COMPOSITE_REMINDER: один reminder с полным текстом исходного сообщения.

    `text` опционален — если None, берём `bookmark.raw_text`.
    Текст обрезается до 2000 символов в payload чтобы не раздувать JSONB
    (Telegram-сообщение всё равно ≤ 4096).
    """
    if not _validate_future(fire_at, now):
        logger.warning(
            "create_composite: skip bookmark %s — fire_at %s not in future",
            bookmark.id, fire_at,
        )
        return None
    payload_text = (text or bookmark.raw_text or "")[:2000].strip()
    payload = _build_composite_payload(text=payload_text)
    reminder = ScheduledMessage(
        user_id=bookmark.user_id,
        bookmark_id=bookmark.id,
        kind=REMINDER_KIND,
        fire_at=fire_at,
        status="pending",
        payload=payload,
    )
    session.add(reminder)
    await session.flush()
    return reminder


async def create_single_reminder(
    session: AsyncSession,
    bookmark: Bookmark,
    item: ResolvedItem,
    *,
    now: datetime,
    source: str = "single_reminder_auto",
) -> ScheduledMessage | None:
    """Для SINGLE_REMINDER: один reminder с текстом item'а.

    Используется в save-flow роутера (auto-create когда AI уверенно распознал
    одну задачу с временем) и в explicit-trigger flow (T7/T8).
    """
    if item.fire_at is None or not _validate_future(item.fire_at, now):
        logger.warning(
            "create_single: skip bookmark %s — fire_at invalid (%s)",
            bookmark.id, item.fire_at,
        )
        return None
    payload = _build_single_payload(text=item.text, source=source)
    reminder = ScheduledMessage(
        user_id=bookmark.user_id,
        bookmark_id=bookmark.id,
        kind=REMINDER_KIND,
        fire_at=item.fire_at,
        status="pending",
        payload=payload,
    )
    session.add(reminder)
    await session.flush()
    return reminder
