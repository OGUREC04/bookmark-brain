"""Phase 2.6 T11 — integration smoke: full pipeline classification → router → creator.

Не использует БД (mock session). Покрывает 3 финальные формы reminder'ов +
вариации по времени (час / часть суток / только дата) согласно PRD.

Цель — поймать регрессию интерфейса между AIClassification → reminder_router
→ reminder_creator (один контракт ResolvedItem проходит через всю цепочку).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from app.schemas import AIClassification, ReminderItem
from app.services.reminder_creator import (
    create_composite_reminder,
    create_per_item_reminders,
    create_single_reminder,
)
from app.services.reminder_router import ReminderForm, route
from freezegun import freeze_time

NOW_MSK = datetime(2026, 5, 13, 12, 0, tzinfo=ZoneInfo("Europe/Moscow"))
NOW_UTC = NOW_MSK.astimezone(timezone.utc)


def _classification(items: list[dict], *, single: bool, hint: str | None = None) -> AIClassification:
    return AIClassification(
        summary="s", tags=["t"], category="article", language="ru",
        reminder_items=[ReminderItem(**i) for i in items],
        single_statement=single,
        reminder_form_hint=hint,
    )


def _make_bookmark() -> MagicMock:
    bm = MagicMock()
    bm.id = uuid.uuid4()
    bm.user_id = uuid.uuid4()
    bm.raw_text = "raw"
    return bm


def _make_session() -> MagicMock:
    s = MagicMock()
    s.add = MagicMock()
    s.flush = AsyncMock()
    return s


# ──────────────────────────────────────────────────
# Scenario 1: SINGLE_REMINDER — «купить молоко завтра в 9»
# ──────────────────────────────────────────────────


@pytest.mark.asyncio
@freeze_time(NOW_UTC)
async def test_e2e_single_reminder_with_hour() -> None:
    """AI → router=SINGLE_REMINDER → creator делает 1 reminder."""
    cls = _classification(
        [{"text": "купить молоко", "raw_date_phrase": "завтра в 9"}],
        single=True, hint="single_reminder",
    )
    decision = route(
        text="купить молоко завтра в 9",
        classification=cls,
        user_tz="Europe/Moscow",
        now=NOW_UTC,
    )
    assert decision.form == ReminderForm.SINGLE_REMINDER
    assert len(decision.dated_items) == 1

    bm = _make_bookmark()
    session = _make_session()
    reminder = await create_single_reminder(
        session, bm, decision.dated_items[0], now=NOW_UTC, source="e2e",
    )
    assert reminder is not None
    assert reminder.payload["text"] == "купить молоко"
    # 9:00 MSK 14 мая = 06:00 UTC
    assert reminder.fire_at.hour == 6


# ──────────────────────────────────────────────────
# Scenario 2: TASK_LIST_WITH_REMINDERS — 2+ дат
# ──────────────────────────────────────────────────


@pytest.mark.asyncio
@freeze_time(NOW_UTC)
async def test_e2e_task_list_with_reminders() -> None:
    cls = _classification(
        [
            {"text": "контрольная", "raw_date_phrase": "завтра в 9"},
            {"text": "зачёт", "raw_date_phrase": "в пятницу в 18"},
            {"text": "тесты Eltex", "raw_date_phrase": None},
        ],
        single=False, hint="task_list_with_reminders",
    )
    decision = route(
        text="завтра контрольная в 9, в пятницу зачёт в 18, ещё тесты Eltex",
        classification=cls, now=NOW_UTC,
    )
    assert decision.form == ReminderForm.TASK_LIST_WITH_REMINDERS

    bm = _make_bookmark()
    session = _make_session()
    created = await create_per_item_reminders(session, bm, decision, now=NOW_UTC)
    assert len(created) == 2
    # item_index сохраняется
    assert created[0].payload["item_index"] == 0
    assert created[1].payload["item_index"] == 1


# ──────────────────────────────────────────────────
# Scenario 3: NEEDS_BUTTON_CHOICE — 1 дата + multi-item
# ──────────────────────────────────────────────────


@pytest.mark.asyncio
@freeze_time(NOW_UTC)
async def test_e2e_needs_button_choice_then_composite() -> None:
    """1 дата + multi-item → router NEEDS_BUTTON_CHOICE. Юзер выбрал 🔔 →
    composite reminder через creator с fire_at = первая dated_item."""
    cls = _classification(
        [
            {"text": "контрольная", "raw_date_phrase": "завтра в 9"},
            {"text": "тесты Eltex", "raw_date_phrase": None},
            {"text": "сессия", "raw_date_phrase": None},
        ],
        single=False,
    )
    decision = route(
        text="завтра контрольная в 9, ещё тесты Eltex и сессия",
        classification=cls, now=NOW_UTC,
    )
    assert decision.form == ReminderForm.NEEDS_BUTTON_CHOICE

    # Юзер кликнул 🔔 Напоминание → composite на fire_at первого dated
    fire_at = decision.dated_items[0].fire_at
    assert fire_at is not None

    bm = _make_bookmark()
    bm.raw_text = "завтра контрольная в 9, ещё тесты Eltex и сессия"
    session = _make_session()
    reminder = await create_composite_reminder(
        session, bm, fire_at=fire_at, now=NOW_UTC,
    )
    assert reminder is not None
    assert reminder.payload["source"] == "composite_reminder"
    assert "контрольная" in reminder.payload["text"]


# ──────────────────────────────────────────────────
# Scenario 4: NEEDS_HOUR — только дата
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
def test_e2e_needs_hour_no_creator_call() -> None:
    """Только дата без часа → router NEEDS_HOUR. Creator не вызывается —
    ждём reply со временем (UX-flow, не unit-test'абельный без БД)."""
    cls = _classification(
        [{"text": "контрольная", "raw_date_phrase": "в пятницу"}],
        single=True,
    )
    decision = route(
        text="контрольная в пятницу", classification=cls, now=NOW_UTC,
    )
    assert decision.form == ReminderForm.NEEDS_HOUR
    assert decision.dated_items == []
    assert len(decision.needs_hour_items) == 1


# ──────────────────────────────────────────────────
# Scenario 5: Strong-intent — день суток vs час
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
def test_e2e_strong_intent_with_part_of_day_creates_reminder() -> None:
    """«надо купить молоко завтра утром» — strong+single+утром.
    nl_date.preprocess маппит «утром» → 9:00 → router SINGLE_REMINDER."""
    cls = _classification(
        [{"text": "купить молоко", "raw_date_phrase": "завтра утром"}],
        single=True,
    )
    decision = route(
        text="надо купить молоко завтра утром",
        classification=cls, now=NOW_UTC,
    )
    assert decision.strong_intent is True
    assert decision.form == ReminderForm.SINGLE_REMINDER
    fire_at = decision.dated_items[0].fire_at
    # 9:00 MSK = 6:00 UTC
    assert fire_at.hour == 6


@freeze_time(NOW_UTC)
def test_e2e_strong_intent_no_date_3button() -> None:
    """«надо купить молоко» без даты → STRONG_INTENT_3BUTTON (Phase 2.5 UX)."""
    cls = _classification(
        [{"text": "купить молоко", "raw_date_phrase": None}],
        single=True,
    )
    decision = route(text="надо купить молоко", classification=cls, now=NOW_UTC)
    assert decision.form == ReminderForm.STRONG_INTENT_3BUTTON


# ──────────────────────────────────────────────────
# Scenario 6: Idempotent serialization for persistence
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
def test_e2e_decision_roundtrips_through_json() -> None:
    """to_dict → JSON → dict → восстановленный has same form/items count.

    Это критично т.к. worker персистит decision в JSONB structured_data,
    бот читает обратно через apply-decision endpoint."""
    import json

    cls = _classification(
        [
            {"text": "контрольная", "raw_date_phrase": "завтра в 9"},
            {"text": "зачёт", "raw_date_phrase": "в пятницу в 18"},
        ],
        single=False,
    )
    decision = route(
        text="завтра контрольная в 9, в пятницу зачёт в 18",
        classification=cls, now=NOW_UTC,
    )
    d = decision.to_dict()
    raw = json.dumps(d)
    restored = json.loads(raw)
    assert restored["form"] == decision.form.value
    assert len(restored["items"]) == len(decision.items)
    # fire_at_utc восстанавливается обратно в datetime через fromisoformat
    for r_item, d_item in zip(restored["items"], decision.items, strict=True):
        if d_item.fire_at:
            parsed = datetime.fromisoformat(r_item["fire_at_utc"])
            assert parsed == d_item.fire_at
