"""Phase 2.6 T5+T6: unit-tests для reminder_creator.

Используем mock session — проверяем что reminder_creator корректно
конструирует ScheduledMessage с правильным payload, fire_at и user_id.
Реальный insert в БД — integration test (отдельно).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.nl_date import ParseStatus
from app.services.reminder_creator import (
    create_composite_reminder,
    create_per_item_reminders,
    create_single_reminder,
)
from app.services.reminder_router import ReminderForm, ResolvedItem, RouterDecision

NOW = datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc)


def _make_bookmark() -> MagicMock:
    bm = MagicMock()
    bm.id = uuid.uuid4()
    bm.user_id = uuid.uuid4()
    bm.raw_text = "Завтра контрольная, в пятницу зачёт, ещё подготовить тесты Eltex"
    return bm


def _make_session() -> MagicMock:
    """Mock сессии — captures `.add()` calls."""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


def _resolved(text: str, fire_at: datetime | None, raw: str | None = None) -> ResolvedItem:
    return ResolvedItem(
        text=text,
        raw_date_phrase=raw or "завтра в 9",
        fire_at=fire_at,
        status=ParseStatus.OK if fire_at else None,
    )


# ──────────────────────────────────────────────────
# T5: create_per_item_reminders
# ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_per_item_creates_only_dated() -> None:
    """3 items, 2 c датой → 2 reminder'а. Без даты — пропускаются."""
    bm = _make_bookmark()
    session = _make_session()
    fire1 = NOW + timedelta(days=1, hours=0)  # завтра 9:00 UTC
    fire2 = NOW + timedelta(days=2, hours=9)  # послезавтра 18:00 UTC
    decision = RouterDecision(
        form=ReminderForm.TASK_LIST_WITH_REMINDERS,
        items=[
            _resolved("контрольная", fire1),
            _resolved("зачёт", fire2),
            _resolved("тесты Eltex", None, raw=None),
        ],
    )
    created = await create_per_item_reminders(session, bm, decision, now=NOW)
    assert len(created) == 2
    assert session.add.call_count == 2
    # Payload содержит task_list_id + item_index
    rem1 = session.add.call_args_list[0].args[0]
    assert rem1.payload["task_list_id"] == str(bm.id)
    assert rem1.payload["item_index"] == 0
    assert rem1.payload["source"] == "task_list_per_item"
    assert rem1.payload["text"] == "контрольная"
    assert rem1.fire_at == fire1
    assert rem1.user_id == bm.user_id
    assert rem1.bookmark_id == bm.id
    assert rem1.kind == "reminder"
    assert rem1.status == "pending"
    # Второй item — index=1 (третий пропущен, его индекс не задействуется)
    rem2 = session.add.call_args_list[1].args[0]
    assert rem2.payload["item_index"] == 1


@pytest.mark.asyncio
async def test_per_item_preserves_original_index_when_skipping() -> None:
    """Если item[0] без даты, item[1] с датой — item_index=1 (а не 0).

    Цель: T9 cascade ищет связку по item_index — она должна совпадать с
    позицией пункта в исходном task_list.
    """
    bm = _make_bookmark()
    session = _make_session()
    fire = NOW + timedelta(hours=1)
    decision = RouterDecision(
        form=ReminderForm.TASK_LIST_WITH_REMINDERS,
        items=[
            _resolved("без даты", None, raw=None),
            _resolved("с датой", fire),
        ],
    )
    created = await create_per_item_reminders(session, bm, decision, now=NOW)
    assert len(created) == 1
    rem = session.add.call_args_list[0].args[0]
    assert rem.payload["item_index"] == 1
    assert rem.payload["text"] == "с датой"


@pytest.mark.asyncio
async def test_per_item_skips_past_dates() -> None:
    """fire_at в прошлом — пропускаем, не падаем."""
    bm = _make_bookmark()
    session = _make_session()
    past = NOW - timedelta(hours=1)
    future = NOW + timedelta(hours=1)
    decision = RouterDecision(
        form=ReminderForm.TASK_LIST_WITH_REMINDERS,
        items=[
            _resolved("прошлое", past),
            _resolved("будущее", future),
        ],
    )
    created = await create_per_item_reminders(session, bm, decision, now=NOW)
    assert len(created) == 1
    assert created[0].payload["text"] == "будущее"


@pytest.mark.asyncio
async def test_per_item_skips_naive_fire_at() -> None:
    """tz-naive fire_at — defensive skip (route() всегда возвращает aware,
    но если кто-то склеит вручную — не вносим мусор)."""
    bm = _make_bookmark()
    session = _make_session()
    naive = datetime(2099, 1, 1)  # naive!
    decision = RouterDecision(
        form=ReminderForm.TASK_LIST_WITH_REMINDERS,
        items=[_resolved("test", naive)],
    )
    created = await create_per_item_reminders(session, bm, decision, now=NOW)
    assert created == []
    assert session.add.call_count == 0


@pytest.mark.asyncio
async def test_per_item_empty_no_flush() -> None:
    """Если нечего создавать — flush не вызывается (микро-оптимизация)."""
    bm = _make_bookmark()
    session = _make_session()
    decision = RouterDecision(form=ReminderForm.NONE, items=[])
    created = await create_per_item_reminders(session, bm, decision, now=NOW)
    assert created == []
    session.flush.assert_not_called()


# ──────────────────────────────────────────────────
# T6: create_composite_reminder
# ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_composite_uses_raw_text_by_default() -> None:
    bm = _make_bookmark()
    session = _make_session()
    fire = NOW + timedelta(days=1)
    reminder = await create_composite_reminder(session, bm, fire_at=fire, now=NOW)
    assert reminder is not None
    assert reminder.payload["source"] == "composite_reminder"
    assert reminder.payload["text"] == bm.raw_text
    assert reminder.fire_at == fire
    assert reminder.user_id == bm.user_id
    assert reminder.bookmark_id == bm.id


@pytest.mark.asyncio
async def test_composite_accepts_explicit_text() -> None:
    bm = _make_bookmark()
    session = _make_session()
    fire = NOW + timedelta(hours=2)
    reminder = await create_composite_reminder(
        session, bm, fire_at=fire, now=NOW, text="custom text"
    )
    assert reminder is not None
    assert reminder.payload["text"] == "custom text"


@pytest.mark.asyncio
async def test_composite_truncates_long_text() -> None:
    bm = _make_bookmark()
    bm.raw_text = "x" * 3000
    session = _make_session()
    fire = NOW + timedelta(hours=1)
    reminder = await create_composite_reminder(session, bm, fire_at=fire, now=NOW)
    assert reminder is not None
    assert len(reminder.payload["text"]) == 2000


@pytest.mark.asyncio
async def test_composite_rejects_past() -> None:
    bm = _make_bookmark()
    session = _make_session()
    past = NOW - timedelta(minutes=10)
    reminder = await create_composite_reminder(session, bm, fire_at=past, now=NOW)
    assert reminder is None
    session.add.assert_not_called()


# ──────────────────────────────────────────────────
# create_single_reminder
# ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_creates_with_source() -> None:
    bm = _make_bookmark()
    session = _make_session()
    fire = NOW + timedelta(days=1, hours=0)
    item = _resolved("купить молоко", fire)
    reminder = await create_single_reminder(session, bm, item, now=NOW, source="explicit")
    assert reminder is not None
    assert reminder.payload["text"] == "купить молоко"
    assert reminder.payload["source"] == "explicit"
    assert reminder.fire_at == fire


@pytest.mark.asyncio
async def test_single_rejects_no_date_item() -> None:
    bm = _make_bookmark()
    session = _make_session()
    item = _resolved("text", None, raw=None)
    reminder = await create_single_reminder(session, bm, item, now=NOW)
    assert reminder is None
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_single_default_source() -> None:
    bm = _make_bookmark()
    session = _make_session()
    fire = NOW + timedelta(hours=1)
    item = _resolved("text", fire)
    reminder = await create_single_reminder(session, bm, item, now=NOW)
    assert reminder is not None
    assert reminder.payload["source"] == "single_reminder_auto"
