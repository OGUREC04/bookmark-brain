"""Materializer регулярных напоминаний (/repeat) — worker cron.

Каждую минуту берёт серии recurring_reminders, у которых next_fire_at наступил,
и кладёт одноразовую копию в scheduled_messages (payload.recurring_id). Доставку
делает штатный scheduled_dispatcher — диспетчер не знает про серии, только про
обычные reminder-строки.

Concurrency: CAS-advance next_fire_at (UPDATE … WHERE next_fire_at = old) — при
наложении cron-ранов копию материализует ровно один (корнер-кейс #13).

``async_session`` берётся из этого модуля — worker-тесты патчат
``app.worker.recurring.async_session``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.database import async_session
from app.services.recurring_service import next_fire_utc

logger = logging.getLogger(__name__)

# Сколько серий материализуем за один тик.
RECURRING_BATCH_SIZE = 50


async def materialize_recurring(ctx: dict) -> None:
    """Cron (каждую минуту): материализуем due-серии в очередь scheduled_messages."""
    from sqlalchemy import text as sa_text

    async with async_session() as session:
        due = await session.execute(sa_text(
            """
            SELECT rr.id, rr.user_id, rr.text, rr.hour, rr.minute,
                   rr.next_fire_at, u.timezone
            FROM recurring_reminders rr
            JOIN users u ON u.id = rr.user_id
            WHERE rr.active = true
              AND rr.next_fire_at <= NOW()
            ORDER BY rr.next_fire_at
            LIMIT :limit
            """
        ).bindparams(limit=RECURRING_BATCH_SIZE))
        rows = due.mappings().all()
        if not rows:
            return

        now = datetime.now(timezone.utc)
        materialized = 0

        for row in rows:
            h, m = row["hour"], row["minute"]
            # Defense-in-depth: невалидное время (прямой DB-write/дрейф схемы)
            # иначе уронило бы next_fire_utc и весь батч этого тика для ВСЕХ.
            if not (0 <= h <= 23 and 0 <= m <= 59):
                logger.error(
                    "materialize_recurring: некорректное время серии %s (h=%s m=%s), пропуск",
                    row["id"], h, m,
                )
                continue
            old_next = row["next_fire_at"]
            new_next = next_fire_utc(h, m, row["timezone"], now)

            # CAS-advance: продвигаем серию только если next_fire_at не менялся
            # (защита от наложения cron-ранов). Кто выиграл — материализует.
            cas = await session.execute(sa_text(
                """
                UPDATE recurring_reminders
                SET next_fire_at = :new_next, last_fired_at = NOW()
                WHERE id = :id AND next_fire_at = :old_next AND active = true
                RETURNING id
                """
            ).bindparams(id=row["id"], new_next=new_next, old_next=old_next))
            if cas.scalar_one_or_none() is None:
                continue  # другой ран уже продвинул эту серию

            # Кладём одноразовую копию — доставит штатный dispatcher.
            await session.execute(sa_text(
                """
                INSERT INTO scheduled_messages (user_id, kind, fire_at, status, payload)
                VALUES (
                    :uid, 'reminder', :fire_at, 'pending',
                    jsonb_build_object(
                        'text', CAST(:text AS text),
                        'source', 'recurring',
                        'recurring_id', CAST(:rid AS text)
                    )
                )
                """
            ).bindparams(
                uid=row["user_id"], fire_at=old_next, text=row["text"],
                rid=str(row["id"]),
            ))
            await session.commit()
            materialized += 1

        if materialized:
            logger.info(
                "materialize_recurring: queued %d occurrence(s)", materialized
            )
