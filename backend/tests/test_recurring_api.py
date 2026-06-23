"""Unit-тесты recurring API — без БД, фокус на парсинг/валидацию/дедуп.

Полный путь с реальной Postgres (JSONB-отмена копий при stop) — интеграционно.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.api.recurring import create_recurring, stop_recurring
from app.models import RecurringReminder
from app.schemas import RecurringCreate
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def user():
    u = MagicMock()
    u.id = uuid4()
    u.timezone = "UTC"
    return u


def _exec_scalars(rows):
    res = MagicMock()
    res.scalars.return_value = rows
    return res


def _session(*results, active_count=0, flush_error=None):
    s = AsyncMock()
    s.add = MagicMock()
    s.flush = AsyncMock(side_effect=flush_error)
    s.refresh = AsyncMock()
    s.scalar = AsyncMock(return_value=active_count)  # кап активных серий
    s.execute = AsyncMock(side_effect=list(results))
    # begin_nested() → async-context-manager (SAVEPOINT)
    nested = MagicMock()
    nested.__aenter__ = AsyncMock(return_value=None)
    nested.__aexit__ = AsyncMock(return_value=False)
    s.begin_nested = MagicMock(return_value=nested)
    return s


def _series(**over):
    base = dict(
        id=uuid4(), user_id=uuid4(), text="полить цветы", rule="daily",
        hour=10, minute=0, next_fire_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        active=True, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    base.update(over)
    return RecurringReminder(**base)


class TestRecurringCreateSchema:
    def test_requires_raw(self):
        with pytest.raises(ValidationError):
            RecurringCreate()  # type: ignore[call-arg]


class TestCreateRecurring:
    @pytest.mark.parametrize(
        "raw",
        [
            "полить цветы",                      # NO_SCHEDULE
            "полить цветы каждый день",          # NO_TIME
            "ежедневно в 9",                     # NO_TEXT
            "полить цветы каждый день в 25:00",  # BAD_TIME
        ],
    )
    async def test_parse_errors_422(self, user, raw):
        session = _session()  # до execute дойти не должно
        with pytest.raises(HTTPException) as exc:
            await create_recurring(RecurringCreate(raw=raw), user, session)
        assert exc.value.status_code == 422

    async def test_success_creates_series(self, user):
        session = _session(_exec_scalars([]))  # дедуп: ничего не нашли
        await create_recurring(
            RecurringCreate(raw="полить цветы каждый день в 10:00"), user, session
        )
        session.add.assert_called_once()
        added = session.add.call_args[0][0]
        assert isinstance(added, RecurringReminder)
        assert added.text == "полить цветы"
        assert (added.hour, added.minute) == (10, 0)
        assert added.rule == "daily"
        assert added.next_fire_at > datetime.now(timezone.utc)

    async def test_dedup_returns_existing_not_added(self, user):
        existing = _series(user_id=user.id, text="полить цветы", hour=10, minute=0)
        session = _session(_exec_scalars([existing]))
        result = await create_recurring(
            RecurringCreate(raw="Полить  Цветы каждый день в 10:00"), user, session
        )
        assert result.deduplicated is True
        session.add.assert_not_called()

    async def test_cap_exceeded_422(self, user):
        # дедуп пуст, но активных серий уже на лимите → 422, без вставки
        session = _session(_exec_scalars([]), active_count=50)
        with pytest.raises(HTTPException) as exc:
            await create_recurring(
                RecurringCreate(raw="полить цветы каждый день в 10:00"), user, session
            )
        assert exc.value.status_code == 422
        session.add.assert_not_called()

    async def test_integrity_race_returns_existing(self, user):
        # гонка: unique-индекс отверг INSERT (flush → IntegrityError) →
        # повторный SELECT находит серию, созданную параллельным запросом.
        existing = _series(user_id=user.id, text="полить цветы", hour=10, minute=0)
        session = _session(
            _exec_scalars([]),          # дедуп: пусто
            _exec_scalars([existing]),  # повторный SELECT после IntegrityError
            flush_error=IntegrityError("stmt", {}, Exception("dup")),
        )
        result = await create_recurring(
            RecurringCreate(raw="полить цветы каждый день в 10:00"), user, session
        )
        assert result.deduplicated is True


class TestStopRecurring:
    async def test_404_when_missing(self, user):
        res = MagicMock()
        res.scalar_one_or_none.return_value = None
        session = _session(res)
        with pytest.raises(HTTPException) as exc:
            await stop_recurring(uuid4(), user, session)
        assert exc.value.status_code == 404

    async def test_stops_active_series(self, user):
        series = _series(user_id=user.id, active=True)
        sel = MagicMock()
        sel.scalar_one_or_none.return_value = series
        upd = MagicMock()  # результат UPDATE-отмены копий (не читаем)
        session = _session(sel, upd)
        await stop_recurring(series.id, user, session)
        assert series.active is False
        assert series.cancelled_at is not None
