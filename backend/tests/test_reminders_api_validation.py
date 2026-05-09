"""Unit tests для reminders API — без БД, фокус на валидацию.

Полные интеграционные тесты с реальной Postgres — отдельная задача.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.reminders import (
    REMINDER_KIND,
    cancel_reminder,
    create_reminder,
    list_upcoming,
    update_reminder,
)
from app.schemas import ReminderCreate, ReminderUpdate


# ──────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────


class TestReminderCreateSchema:
    def test_minimal_valid(self):
        r = ReminderCreate(fire_at=datetime(2030, 1, 1, tzinfo=timezone.utc))
        assert r.bookmark_id is None
        assert r.payload == {}

    def test_with_bookmark_and_payload(self):
        bid = uuid4()
        r = ReminderCreate(
            fire_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            bookmark_id=bid,
            payload={"snooze_count": 1},
        )
        assert r.bookmark_id == bid
        assert r.payload["snooze_count"] == 1

    def test_missing_fire_at_raises(self):
        with pytest.raises(ValidationError):
            ReminderCreate()  # type: ignore[call-arg]


class TestReminderUpdateSchema:
    def test_optional_fire_at(self):
        u = ReminderUpdate()
        assert u.fire_at is None

    def test_with_fire_at(self):
        u = ReminderUpdate(fire_at=datetime(2030, 1, 1, tzinfo=timezone.utc))
        assert u.fire_at is not None


# ──────────────────────────────────────────────────
# create_reminder — fire_at validation
# ──────────────────────────────────────────────────


@pytest.fixture
def user():
    u = MagicMock()
    u.id = uuid4()
    u.telegram_id = 999
    return u


@pytest.fixture
def session():
    s = AsyncMock()
    s.add = MagicMock()
    s.flush = AsyncMock()
    s.refresh = AsyncMock()
    return s


class TestCreateReminderValidation:
    async def test_rejects_past_fire_at(self, user, session):
        body = ReminderCreate(
            fire_at=datetime.now(timezone.utc) - timedelta(hours=1)
        )
        with pytest.raises(HTTPException) as exc:
            await create_reminder(body, user, session)
        assert exc.value.status_code == 400
        assert "future" in exc.value.detail.lower()

    async def test_rejects_now_exactly(self, user, session):
        # fire_at = now (без буфера) — отклоняем
        body = ReminderCreate(fire_at=datetime.now(timezone.utc))
        with pytest.raises(HTTPException) as exc:
            await create_reminder(body, user, session)
        assert exc.value.status_code == 400

    async def test_naive_datetime_treated_as_utc(self, user, session):
        # Naive future → допустим (бэкенд считает UTC)
        future_naive = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None)
        body = ReminderCreate(fire_at=future_naive)
        # Не должен упасть на валидации fire_at (хотя bookmark_id None — пройдёт)
        await create_reminder(body, user, session)
        session.add.assert_called_once()


# ──────────────────────────────────────────────────
# update_reminder — IDOR + fire_at validation
# ──────────────────────────────────────────────────


class TestUpdateReminderValidation:
    async def test_404_when_not_found(self, user, session):
        # _get_user_reminder вернёт 404
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc:
            await update_reminder(uuid4(), ReminderUpdate(), user, session)
        assert exc.value.status_code == 404

    async def test_404_when_belongs_to_other_user(self, user, session):
        # Reminder есть, но user_id фильтр в WHERE отдаёт None
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc:
            await update_reminder(uuid4(), ReminderUpdate(), user, session)
        assert exc.value.status_code == 404

    async def test_rejects_past_fire_at_on_update(self, user, session):
        # Reminder найден, но новый fire_at в прошлом
        existing = MagicMock()
        existing.id = uuid4()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=existing)
        session.execute = AsyncMock(return_value=result)

        body = ReminderUpdate(fire_at=datetime.now(timezone.utc) - timedelta(hours=1))
        with pytest.raises(HTTPException) as exc:
            await update_reminder(uuid4(), body, user, session)
        assert exc.value.status_code == 400


# ──────────────────────────────────────────────────
# list_upcoming — limit validation
# ──────────────────────────────────────────────────


class TestListUpcoming:
    """`limit` валидация теперь через FastAPI Query(ge=1, le=200) — 422 автоматом.
    Здесь тестируем только happy-path вызов функции."""

    async def test_valid_limit_calls_db(self, user, session):
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        session.execute = AsyncMock(return_value=result)

        response = await list_upcoming(user, session, limit=50)
        assert response.total == 0
        assert response.items == []
        session.execute.assert_called_once()


# ──────────────────────────────────────────────────
# Constant
# ──────────────────────────────────────────────────


def test_kind_is_reminder():
    """Защита от опечатки в const — kind должен быть 'reminder'."""
    assert REMINDER_KIND == "reminder"
