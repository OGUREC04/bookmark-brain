"""Unit tests для reminders API — без БД, фокус на валидацию.

Полные интеграционные тесты с реальной Postgres — отдельная задача.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.api.reminders import (
    REMINDER_KIND,
    cancel_reminder,
    create_reminder,
    list_upcoming,
    update_reminder,
)
from app.schemas import ReminderCreate, ReminderUpdate
from fastapi import HTTPException
from pydantic import ValidationError

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
        assert u.text is None

    def test_with_fire_at(self):
        u = ReminderUpdate(fire_at=datetime(2030, 1, 1, tzinfo=timezone.utc))
        assert u.fire_at is not None

    def test_with_text(self):
        # 8uu: text — опциональное поле, можно слать без fire_at
        u = ReminderUpdate(text="купить молоко")
        assert u.text == "купить молоко"
        assert u.fire_at is None


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
        # За пределами grace (1 час назад) — всё ещё 400.
        body = ReminderCreate(
            fire_at=datetime.now(timezone.utc) - timedelta(hours=1)
        )
        with pytest.raises(HTTPException) as exc:
            await create_reminder(body, user, session)
        assert exc.value.status_code == 400
        assert "future" in exc.value.detail.lower()

    async def test_now_exactly_clamped_not_rejected(self, user, session):
        """bookmark-brain-bne: fire_at = now в пределах grace → НЕ 400,
        поджимается к now+буфер и создаётся. Раньше строгий <= now давал
        400 на граничном/чуть-просроченном времени из бота."""
        body = ReminderCreate(fire_at=datetime.now(timezone.utc))
        await create_reminder(body, user, session)
        session.add.assert_called_once()

    async def test_marginally_past_within_grace_clamped(self, user, session):
        """fire_at на 20с в прошлом (толерантность nl_date.parse) → clamp,
        не 400."""
        body = ReminderCreate(
            fire_at=datetime.now(timezone.utc) - timedelta(seconds=20)
        )
        await create_reminder(body, user, session)
        session.add.assert_called_once()

    async def test_naive_datetime_treated_as_utc(self, user, session):
        # Naive future → допустим (бэкенд считает UTC)
        future_naive = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None)
        body = ReminderCreate(fire_at=future_naive)
        # Не должен упасть на валидации fire_at (хотя bookmark_id None — пройдёт)
        await create_reminder(body, user, session)
        session.add.assert_called_once()

    async def test_dedup_returns_existing_with_flag(self, user, session):
        """E15: повтор (тот же текст+минута) → existing + deduplicated=True,
        новый ScheduledMessage НЕ добавляется. Бот по флагу пишет «Уже напомню»."""
        from unittest.mock import patch

        from app.api import reminders as rem
        from app.schemas import ReminderResponse

        existing = MagicMock()
        base = ReminderResponse(
            id=uuid4(), bookmark_id=None, kind="reminder",
            fire_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            status="pending", payload={"text": "купить хлеб"},
            created_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )
        body = ReminderCreate(
            fire_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            payload={"text": "купить хлеб"},
        )
        with (
            patch("app.services.reminder_creator.find_duplicate_reminder",
                  AsyncMock(return_value=existing)),
            patch.object(rem, "_to_reminder_response", return_value=base),
        ):
            out = await create_reminder(body, user, session)

        assert out.deduplicated is True
        session.add.assert_not_called()  # дубль не создан


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


class TestUpdateReminderText:
    """8uu: правка текста напоминания через PATCH (text → payload['text'])."""

    def _existing(self, session, *, status_val="pending", payload=None):
        existing = MagicMock()
        existing.id = uuid4()
        existing.status = status_val
        existing.payload = payload if payload is not None else {}
        existing.fire_at = datetime(2030, 1, 1, tzinfo=timezone.utc)
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=existing)
        session.execute = AsyncMock(return_value=result)
        return existing

    async def test_text_only_edit_keeps_time_and_status(self, user, session):
        existing = self._existing(
            session, payload={"text": "старый", "snooze_count": 2}
        )
        out = await update_reminder(uuid4(), ReminderUpdate(text="новый текст"), user, session)
        assert out is existing
        assert existing.payload["text"] == "новый текст"
        assert existing.payload["snooze_count"] == 2  # прочий payload сохранён
        assert existing.status == "pending"
        assert existing.fire_at == datetime(2030, 1, 1, tzinfo=timezone.utc)  # время не тронуто

    async def test_text_is_trimmed(self, user, session):
        existing = self._existing(session)
        await update_reminder(uuid4(), ReminderUpdate(text="  с пробелами  "), user, session)
        assert existing.payload["text"] == "с пробелами"

    async def test_payload_reassigned_not_mutated_in_place(self, user, session):
        # JSONB-grab: payload должен стать НОВЫМ объектом (иначе ORM не запишет)
        original_payload = {"text": "старый"}
        existing = self._existing(session, payload=original_payload)
        await update_reminder(uuid4(), ReminderUpdate(text="новый"), user, session)
        assert existing.payload is not original_payload
        assert original_payload == {"text": "старый"}  # старый объект не мутирован

    async def test_empty_text_rejected_422(self, user, session):
        self._existing(session)
        with pytest.raises(HTTPException) as exc:
            await update_reminder(uuid4(), ReminderUpdate(text="   "), user, session)
        assert exc.value.status_code == 422

    async def test_too_long_text_rejected_422(self, user, session):
        from app.api.reminders import MAX_REMINDER_TEXT_LEN

        self._existing(session)
        with pytest.raises(HTTPException) as exc:
            await update_reminder(
                uuid4(), ReminderUpdate(text="x" * (MAX_REMINDER_TEXT_LEN + 1)), user, session
            )
        assert exc.value.status_code == 422

    async def test_text_edit_on_non_pending_rejected_409(self, user, session):
        self._existing(session, status_val="done")
        with pytest.raises(HTTPException) as exc:
            await update_reminder(uuid4(), ReminderUpdate(text="новый"), user, session)
        assert exc.value.status_code == 409

    async def test_text_and_fire_at_together(self, user, session):
        existing = self._existing(session)
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        await update_reminder(uuid4(), ReminderUpdate(text="оба", fire_at=future), user, session)
        assert existing.payload["text"] == "оба"
        assert existing.fire_at == future
        assert existing.status == "pending"

    async def test_no_fields_is_noop(self, user, session):
        existing = self._existing(session, payload={"text": "без изменений"})
        out = await update_reminder(uuid4(), ReminderUpdate(), user, session)
        assert out is existing
        assert existing.payload == {"text": "без изменений"}
        session.flush.assert_not_called()


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


class TestReminderDedup:
    """E15: exact-dedup (тот же текст + та же минута) → возвращаем
    существующий, не плодим дубль."""

    async def test_exact_duplicate_returns_existing(self, user, session):
        # existing — с реальными атрибутами, т.к. _to_reminder_response
        # сериализует его в ReminderResponse (deduplicated=True).
        existing = MagicMock()
        existing.id = uuid4()
        existing.bookmark_id = None
        existing.kind = "reminder"
        existing.fire_at = datetime(2030, 1, 1, tzinfo=timezone.utc)
        existing.status = "pending"
        existing.payload = {"text": "купить хлеб"}
        existing.created_at = datetime(2030, 1, 1, tzinfo=timezone.utc)
        existing.sent_at = None
        result = MagicMock()
        result.scalars = MagicMock(
            return_value=MagicMock(first=MagicMock(return_value=existing))
        )
        session.execute = AsyncMock(return_value=result)
        body = ReminderCreate(
            fire_at=datetime.now(timezone.utc) + timedelta(hours=1),
            payload={"text": "купить хлеб"},
        )
        out = await create_reminder(body, user, session)
        assert out.deduplicated is True
        assert out.id == existing.id
        session.add.assert_not_called()  # дубль не создан

    async def test_different_text_creates_new(self, user, session):
        result = MagicMock()
        result.scalars = MagicMock(
            return_value=MagicMock(first=MagicMock(return_value=None))
        )
        session.execute = AsyncMock(return_value=result)
        body = ReminderCreate(
            fire_at=datetime.now(timezone.utc) + timedelta(hours=1),
            payload={"text": "новое дело"},
        )
        await create_reminder(body, user, session)
        session.add.assert_called_once()

    async def test_no_text_skips_dedup(self, user, session):
        body = ReminderCreate(
            fire_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        await create_reminder(body, user, session)
        session.add.assert_called_once()
