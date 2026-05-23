"""T16 v2.1: Integration-tier тесты для reminders на ЖИВОЙ Postgres.

Цель: ловить класс багов которые моки не видят (например PR #9 ENUM
mismatch). Тесты делают реальный INSERT/UPDATE/DELETE через
SQLAlchemy ORM в локальный docker-compose Postgres.

Запуск:
    pytest backend/tests/integration -m integration

Требования:
- Postgres+Redis запущены через docker-compose
- DATABASE_URL валидный (читается из .env)
- Миграции применены (`alembic upgrade head`)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# Skip всех тестов если Postgres недоступен — например в CI без docker
pytestmark = pytest.mark.integration


_TG_ID_COUNTER = 7700000


@pytest.fixture
async def db_user_id():
    """Создать тестового юзера с уникальным telegram_id (счётчик), отдать UUID.
    Cleanup после теста. Уникальный TG_ID избегает гонки между параллельными
    тестами и проблем с event-loop scoping в pytest-asyncio."""
    global _TG_ID_COUNTER
    _TG_ID_COUNTER += 1
    tg_id = _TG_ID_COUNTER

    from app.database import async_session
    from app.models import ScheduledMessage, User
    from sqlalchemy import delete

    async with async_session() as session:
        u = User(
            telegram_id=tg_id,
            telegram_username=f"t16_{tg_id}",
            telegram_first_name="Integration",
            timezone="Europe/Moscow",
        )
        session.add(u)
        await session.flush()
        await session.refresh(u)
        user_id = u.id
        await session.commit()

    yield user_id

    # Cleanup (CASCADE на scheduled_messages.user_id удалит всё связанное)
    try:
        async with async_session() as session:
            await session.execute(
                delete(User).where(User.id == user_id)
            )
            await session.commit()
    except Exception:
        # cleanup best-effort — следующий тест получит уникальный tg_id
        pass


# ──────────────────────────────────────────────────
# Regression: PR #9 ENUM bug
# ──────────────────────────────────────────────────


class TestEnumRegression:
    """Воспроизводит сценарий PR #9 — INSERT через ORM на ENUM-колонках."""

    async def test_orm_insert_with_enum_kind_and_status(self, db_user_id):
        """ORM session.add(reminder) → flush должен пройти без
        DatatypeMismatchError. Если эта ошибка вернётся — модель опять
        декларирована как String вместо postgresql.ENUM."""
        from app.database import async_session
        from app.models import ScheduledMessage

        async with async_session() as session:
            r = ScheduledMessage(
                user_id=db_user_id,
                kind="reminder",
                fire_at=datetime.now(timezone.utc) + timedelta(hours=1),
                status="pending",
                payload={"text": "T16 regression test"},
            )
            session.add(r)
            await session.flush()
            await session.refresh(r)
            rid = r.id
            await session.commit()

        # Verify roundtrip
        from sqlalchemy import select
        async with async_session() as session:
            result = await session.execute(
                select(ScheduledMessage).where(ScheduledMessage.id == rid)
            )
            row = result.scalar_one_or_none()
            assert row is not None
            assert row.kind == "reminder"
            assert row.status == "pending"
            assert row.payload == {"text": "T16 regression test"}

        # Cleanup
        from sqlalchemy import delete
        async with async_session() as session:
            await session.execute(
                delete(ScheduledMessage).where(ScheduledMessage.id == rid)
            )
            await session.commit()


# ──────────────────────────────────────────────────
# Worker SQL queries on real DB
# ──────────────────────────────────────────────────


class TestWorkerSQLOnRealDB:
    """SQL-запросы воркера должны работать на реальной Postgres
    (включая ENUM, jsonb_build_object, partial index)."""

    async def test_select_due_reminder_query(self, db_user_id):
        """SELECT due из scheduled_dispatcher с JOIN users."""
        from app.database import async_session
        from app.models import ScheduledMessage
        from sqlalchemy import delete
        from sqlalchemy import text as sa_text

        async with async_session() as session:
            # Создать due reminder
            r = ScheduledMessage(
                user_id=db_user_id,
                kind="reminder",
                fire_at=datetime.now(timezone.utc) - timedelta(seconds=30),
                status="pending",
                payload={"text": "due test"},
            )
            session.add(r)
            await session.flush()
            await session.refresh(r)
            await session.commit()
            rid = r.id

        # Запрос-же что в worker.scheduled_dispatcher
        async with async_session() as session:
            result = await session.execute(sa_text("""
                SELECT sm.id, sm.user_id, u.telegram_id, sm.bookmark_id,
                       sm.fire_at, sm.retry_count, sm.payload
                FROM scheduled_messages sm
                JOIN users u ON u.id = sm.user_id
                WHERE sm.status = 'pending'
                  AND sm.kind = 'reminder'
                  AND sm.fire_at <= NOW()
                ORDER BY sm.fire_at
                LIMIT 50
            """))
            rows = result.all()
            assert any(row[0] == rid for row in rows)

        # CAS update
        async with async_session() as session:
            cas_result = await session.execute(sa_text("""
                UPDATE scheduled_messages
                SET status = 'sending'
                WHERE id = :id AND status = 'pending'
                RETURNING id, payload, retry_count
            """).bindparams(id=rid))
            locked = cas_result.scalar_one_or_none()
            assert locked is not None
            await session.commit()

        # Cleanup
        async with async_session() as session:
            await session.execute(
                delete(ScheduledMessage).where(ScheduledMessage.id == rid)
            )
            await session.commit()

    async def test_auto_done_query_with_fire_at_guard(self, db_user_id):
        """F5 regression: auto_done не трогает snoozed reminder с
        fire_at в будущем."""
        from app.database import async_session
        from app.models import ScheduledMessage
        from sqlalchemy import delete, select
        from sqlalchemy import text as sa_text

        # Создать «снуженный» reminder: status='sent', sent_at=сутки назад,
        # но fire_at в будущем (юзер продлил после первой отправки).
        async with async_session() as session:
            r = ScheduledMessage(
                user_id=db_user_id,
                kind="reminder",
                fire_at=datetime.now(timezone.utc) + timedelta(hours=6),
                status="sent",
                payload={"text": "snoozed"},
            )
            session.add(r)
            await session.flush()
            await session.refresh(r)
            rid = r.id

            # Backdate sent_at руками
            await session.execute(sa_text(
                "UPDATE scheduled_messages SET sent_at = NOW() - INTERVAL '25 hours' WHERE id = :id"
            ).bindparams(id=rid))
            await session.commit()

        # Запустить auto_done query (тот же что в worker)
        async with async_session() as session:
            result = await session.execute(sa_text("""
                UPDATE scheduled_messages
                SET status = 'done',
                    payload = COALESCE(payload, '{}'::jsonb)
                              || jsonb_build_object('auto_done', true)
                WHERE kind = 'reminder'
                  AND status = 'sent'
                  AND sent_at < NOW() - (:hours || ' hours')::interval
                  AND fire_at <= NOW()
            """).bindparams(hours="24"))
            await session.commit()

        # Verify: reminder ещё в status='sent' (не задет)
        async with async_session() as session:
            result = await session.execute(
                select(ScheduledMessage).where(ScheduledMessage.id == rid)
            )
            row = result.scalar_one_or_none()
            assert row is not None
            assert row.status == "sent", (
                f"F5 regression: snoozed reminder marked done (status={row.status})"
            )

        # Cleanup
        async with async_session() as session:
            await session.execute(
                delete(ScheduledMessage).where(ScheduledMessage.id == rid)
            )
            await session.commit()

    async def test_auto_done_cleans_old_sent_with_past_fire_at(self, db_user_id):
        """F5: auto_done корректно cleanup'ит старые sent с fire_at в прошлом."""
        from app.database import async_session
        from app.models import ScheduledMessage
        from sqlalchemy import delete, select
        from sqlalchemy import text as sa_text

        async with async_session() as session:
            r = ScheduledMessage(
                user_id=db_user_id,
                kind="reminder",
                fire_at=datetime.now(timezone.utc) - timedelta(hours=25),
                status="sent",
                payload={"text": "old"},
            )
            session.add(r)
            await session.flush()
            await session.refresh(r)
            rid = r.id

            await session.execute(sa_text(
                "UPDATE scheduled_messages SET sent_at = NOW() - INTERVAL '25 hours' WHERE id = :id"
            ).bindparams(id=rid))
            await session.commit()

        async with async_session() as session:
            await session.execute(sa_text("""
                UPDATE scheduled_messages
                SET status = 'done',
                    payload = COALESCE(payload, '{}'::jsonb)
                              || jsonb_build_object('auto_done', true)
                WHERE kind = 'reminder'
                  AND status = 'sent'
                  AND sent_at < NOW() - (:hours || ' hours')::interval
                  AND fire_at <= NOW()
            """).bindparams(hours="24"))
            await session.commit()

        async with async_session() as session:
            result = await session.execute(
                select(ScheduledMessage).where(ScheduledMessage.id == rid)
            )
            row = result.scalar_one_or_none()
            assert row.status == "done"
            assert row.payload.get("auto_done") is True

        async with async_session() as session:
            await session.execute(
                delete(ScheduledMessage).where(ScheduledMessage.id == rid)
            )
            await session.commit()


# ──────────────────────────────────────────────────
# API end-to-end
# ──────────────────────────────────────────────────


class TestRemindersAPIRealDB:
    """POST/PATCH/DELETE/GET через реальную Postgres."""

    async def test_create_list_cancel_full_flow(self, db_user_id):
        """API integration test."""
        from app.api.reminders import (
            cancel_reminder,
            create_reminder,
            list_upcoming,
        )
        from app.database import async_session
        from app.models import ScheduledMessage, User
        from app.schemas import ReminderCreate
        from sqlalchemy import delete, select

        async with async_session() as session:
            user_result = await session.execute(
                select(User).where(User.id == db_user_id)
            )
            user = user_result.scalar_one()

            # Create
            body = ReminderCreate(
                fire_at=datetime.now(timezone.utc) + timedelta(hours=2),
                payload={"text": "API e2e test", "source": "explicit_remind"},
            )
            created = await create_reminder(body, user, session)
            await session.commit()
            assert created.kind == "reminder"
            assert created.status == "pending"
            rid = created.id

        # List upcoming
        async with async_session() as session:
            user_result = await session.execute(
                select(User).where(User.id == db_user_id)
            )
            user = user_result.scalar_one()
            response = await list_upcoming(user, session, limit=50)
            assert any(item.id == rid for item in response.items)

        # Cancel
        async with async_session() as session:
            user_result = await session.execute(
                select(User).where(User.id == db_user_id)
            )
            user = user_result.scalar_one()
            await cancel_reminder(rid, user, session)
            await session.commit()

        # Verify cancelled
        async with async_session() as session:
            result = await session.execute(
                select(ScheduledMessage).where(ScheduledMessage.id == rid)
            )
            row = result.scalar_one_or_none()
            assert row.status == "cancelled"
            assert row.cancelled_at is not None

        # Cleanup
        async with async_session() as session:
            await session.execute(
                delete(ScheduledMessage).where(ScheduledMessage.id == rid)
            )
            await session.commit()
