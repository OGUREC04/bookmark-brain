"""Каскад reminder'ов при изменении `bookmark.structured_data` (task_list).

Вызывается из двух мест с одним и тем же контрактом old→new diff:
  • NL-edit (`POST /bookmarks/{id}/nl-edit`)
  • PATCH `/bookmarks/{id}` (Mini App редактирует дедлайны/пункты)

Реконсиляция:
  • Удалили пункт где висел reminder → cancel reminder
  • Добавили пункт с deadline → создаём новый reminder (fire_at = deadline + 9:00 user_tz)
  • Изменили deadline у пункта → переставляем fire_at у reminder'а
  • Сняли deadline у живого пункта → cancel reminder, НО только если он был
    создан каскадом (`source == "cascade_added"`); вручную поставленные
    напоминания не трогаем

Match по нормализованному тексту пункта (lowercase + strip), потому что
`item_index` в payload — снапшот старой позиции, который сдвигается при
del/add. Текст — единственный стабильный ключ для item'а.

Default-час для deadline-only: 9:00 в user_tz. Юзер может настроить через
переписку с reminder'ом отдельно — это MVP-эвристика.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ScheduledMessage

logger = logging.getLogger(__name__)

REMINDER_KIND = "reminder"
DEFAULT_DEADLINE_HOUR = 9  # 9:00 утра в user_tz


@dataclass
class CascadeResult:
    """Сумма побочек cascade'а — для confirmation message в reply."""

    cancelled: list[UUID] = field(default_factory=list)
    rescheduled: list[UUID] = field(default_factory=list)
    created: list[UUID] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.cancelled or self.rescheduled or self.created)

    def summary(self) -> str:
        """Короткая строка для бота. Пустая если нет изменений."""
        parts: list[str] = []
        if self.created:
            n = len(self.created)
            parts.append(f"+{n} напомин" + _plural(n))
        if self.rescheduled:
            n = len(self.rescheduled)
            parts.append(f"перенёс {n} напомин" + _plural(n))
        if self.cancelled:
            n = len(self.cancelled)
            parts.append(f"отменил {n} напомин" + _plural(n))
        return ", ".join(parts)


def _plural(n: int) -> str:
    """«1 напоминание / 2 напоминания / 5 напоминаний»."""
    if n % 10 == 1 and n % 100 != 11:
        return "ание"
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return "ания"
    return "аний"


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def cascade_signature(structured: dict | None) -> set[tuple[str, str]]:
    """Сигнатура task_list для дешёвого guard'а перед cascade.

    Множество `(нормализованный текст, deadline)` по всем пунктам. Если
    сигнатура не изменилась — cascade можно пропустить целиком (например,
    переключили только галочку `done`, текст и дедлайны прежние).
    """
    if not isinstance(structured, dict):
        return set()
    out: set[tuple[str, str]] = set()
    for t in structured.get("tasks", []) or []:
        norm = _norm(t.get("text"))
        if norm:
            out.add((norm, t.get("deadline") or ""))
    return out


def _parse_deadline_to_utc(deadline_str: str, user_tz: str) -> datetime | None:
    """`YYYY-MM-DD` → UTC datetime в 09:00 user_tz. None если невалидно / в прошлом."""
    if not deadline_str:
        return None
    try:
        d = date.fromisoformat(deadline_str)
    except (ValueError, TypeError):
        return None
    try:
        zone = ZoneInfo(user_tz)
    except Exception as e:
        logger.warning(
            "cascade: invalid user_tz %r, falling back to Europe/Moscow (%s)",
            user_tz, e,
        )
        zone = ZoneInfo("Europe/Moscow")
    local_dt = datetime.combine(d, time(DEFAULT_DEADLINE_HOUR, 0), tzinfo=zone)
    utc_dt = local_dt.astimezone(timezone.utc)
    if utc_dt <= datetime.now(timezone.utc):
        return None
    return utc_dt


async def apply_cascade(
    session: AsyncSession,
    *,
    bookmark_id: UUID,
    user_id: UUID,
    old_structured: dict | None,
    new_structured: dict | None,
    user_tz: str = "Europe/Moscow",
) -> CascadeResult:
    """Применить cascade к pending reminder'ам task_list.

    Args:
        session: открытая sqla-сессия, caller отвечает за commit
        bookmark_id: id task_list bookmark'а
        user_id: владелец (для IDOR-фильтра выборки reminder'ов)
        old_structured: structured_data ДО NL-edit (или None)
        new_structured: structured_data ПОСЛЕ NL-edit (или None)
        user_tz: IANA timezone юзера для расчёта deadline-default
    """
    result = CascadeResult()
    if not isinstance(new_structured, dict):
        return result

    old_tasks = (old_structured or {}).get("tasks", []) if isinstance(old_structured, dict) else []
    new_tasks = new_structured.get("tasks", []) or []

    old_by_text: dict[str, dict] = {}
    for t in old_tasks:
        norm = _norm(t.get("text"))
        if norm:
            old_by_text[norm] = t

    new_by_text: dict[str, dict] = {}
    for t in new_tasks:
        norm = _norm(t.get("text"))
        if norm:
            new_by_text[norm] = t

    # Выбираем pending reminder'ы, относящиеся к этому task_list.
    # JSONB фильтр `payload->>'task_list_id' = '<uuid>'`.
    rems_result = await session.execute(sa_text(
        """
        SELECT id, fire_at, payload, status
        FROM scheduled_messages
        WHERE kind = 'reminder'
          AND status = 'pending'
          AND user_id = CAST(:uid AS uuid)
          AND payload->>'task_list_id' = :bid
        """
    ).bindparams(
        uid=str(user_id),
        bid=str(bookmark_id),
    ))
    rems = list(rems_result.mappings().all())

    # Pass 1: для каждого reminder'а — что с пунктом?
    for rem in rems:
        rid = rem["id"]
        payload = rem["payload"] or {}
        rem_text_norm = _norm(payload.get("text"))
        new_item = new_by_text.get(rem_text_norm)

        if new_item is None:
            # Пункт удалён / переименован за пределы norm-match → cancel
            await session.execute(sa_text(
                """
                UPDATE scheduled_messages
                SET status = 'cancelled', cancelled_at = NOW()
                WHERE id = :id AND status = 'pending'
                """
            ).bindparams(id=rid))
            result.cancelled.append(rid)
            continue

        # Пункт жив — проверяем deadline
        new_deadline = new_item.get("deadline")
        if not new_deadline:
            # Дедлайн сняли у живого пункта → отменяем напоминание, но только
            # если оно создано каскадом из дедлайна. Вручную поставленные
            # (source != "cascade_added") не трогаем — они не привязаны к дедлайну.
            if payload.get("source") == "cascade_added":
                await session.execute(sa_text(
                    """
                    UPDATE scheduled_messages
                    SET status = 'cancelled', cancelled_at = NOW()
                    WHERE id = :id AND status = 'pending'
                    """
                ).bindparams(id=rid))
                result.cancelled.append(rid)
                logger.info(
                    "cascade: cancelled reminder %s on bookmark %s (deadline cleared)",
                    rid, bookmark_id,
                )
            continue

        new_fire_at = _parse_deadline_to_utc(new_deadline, user_tz)
        if new_fire_at is None:
            continue  # невалидный/прошедший deadline — не трогаем
        # Если час совпадает с текущим fire_at — пропускаем
        current_fire_at = rem["fire_at"]
        if current_fire_at and abs((current_fire_at - new_fire_at).total_seconds()) < 60:
            continue
        await session.execute(sa_text(
            """
            UPDATE scheduled_messages
            SET fire_at = :fire_at, status = 'pending', sent_at = NULL
            WHERE id = :id AND status = 'pending'
            """
        ).bindparams(id=rid, fire_at=new_fire_at))
        result.rescheduled.append(rid)
        logger.info(
            "cascade: rescheduled reminder %s on bookmark %s → %s",
            rid, bookmark_id, new_fire_at.isoformat(),
        )

    # Pass 2: новые пункты с deadline'ом, у которых ещё нет reminder'а.
    # Получаем актуальные text'ы reminder'ов (после Pass 1 они могут быть cancelled).
    existing_after_pass1 = await session.execute(sa_text(
        """
        SELECT payload->>'text' AS rtext
        FROM scheduled_messages
        WHERE kind = 'reminder'
          AND status = 'pending'
          AND user_id = CAST(:uid AS uuid)
          AND payload->>'task_list_id' = :bid
        """
    ).bindparams(uid=str(user_id), bid=str(bookmark_id)))
    existing_texts = {_norm(r[0]) for r in existing_after_pass1.all()}

    for idx, new_t in enumerate(new_tasks):
        norm = _norm(new_t.get("text"))
        if not norm:
            continue
        if norm in existing_texts:
            continue
        deadline = new_t.get("deadline")
        if not deadline:
            continue
        fire_at = _parse_deadline_to_utc(deadline, user_tz)
        if fire_at is None:
            continue
        rem = ScheduledMessage(
            user_id=user_id,
            bookmark_id=bookmark_id,
            kind=REMINDER_KIND,
            fire_at=fire_at,
            status="pending",
            payload={
                "text": new_t.get("text", ""),
                "source": "cascade_added",
                "task_list_id": str(bookmark_id),
                "item_index": idx,
            },
        )
        session.add(rem)
        await session.flush()
        result.created.append(rem.id)
        # text здесь — пользовательский контент (PII): логируем в DEBUG,
        # на INFO оставляем только counts (см. summary в конце).
        logger.debug(
            "cascade: created reminder %s on bookmark %s for new item %r",
            rem.id, bookmark_id, new_t.get("text"),
        )

    if result.has_changes:
        logger.info(
            "cascade summary for bookmark %s: created=%d rescheduled=%d cancelled=%d",
            bookmark_id, len(result.created),
            len(result.rescheduled), len(result.cancelled),
        )

    return result
