"""Phase 2.6 T9 — unit-тесты для cascade (без БД, через mock-сессию)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.reminder_cascade import (
    CascadeResult,
    _norm,
    _parse_deadline_to_utc,
    _plural,
    apply_cascade,
)


def test_norm_strips_and_lowers():
    assert _norm("  Купить Хлеб  ") == "купить хлеб"
    assert _norm(None) == ""
    assert _norm("") == ""


def test_plural_russian_grammar():
    """1 → ание, 2-4 → ания, 5+ → аний, 11-14 → аний."""
    assert _plural(1) == "ание"
    assert _plural(2) == "ания"
    assert _plural(4) == "ания"
    assert _plural(5) == "аний"
    assert _plural(11) == "аний"
    assert _plural(14) == "аний"
    assert _plural(21) == "ание"
    assert _plural(25) == "аний"


def test_parse_deadline_returns_utc_at_9_user_tz():
    """Deadline 2099-05-15 + Europe/Moscow → 06:00 UTC (MSK 09:00)."""
    # Используем дату далеко в будущем чтобы тест не сломался со временем
    dt = _parse_deadline_to_utc("2099-05-15", user_tz="Europe/Moscow")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0
    # MSK = UTC+3 → 9:00 MSK = 6:00 UTC
    assert dt.hour == 6
    assert dt.minute == 0


def test_parse_deadline_in_past_returns_none():
    """Прошедший день → None (не создаём reminder в прошлом)."""
    assert _parse_deadline_to_utc("2020-01-01", user_tz="Europe/Moscow") is None


def test_parse_deadline_invalid_format_returns_none():
    assert _parse_deadline_to_utc("not-a-date", user_tz="Europe/Moscow") is None
    assert _parse_deadline_to_utc("", user_tz="Europe/Moscow") is None
    assert _parse_deadline_to_utc(None, user_tz="Europe/Moscow") is None  # type: ignore[arg-type]


def test_parse_deadline_fallbacks_invalid_tz_to_msk():
    """Невалидный TZ → fallback на Europe/Moscow, не падаем."""
    dt = _parse_deadline_to_utc("2099-05-15", user_tz="NotARealZone/Foo")
    assert dt is not None


def test_cascade_result_summary_empty():
    r = CascadeResult()
    assert r.has_changes is False
    assert r.summary() == ""


def test_cascade_result_summary_mixed():
    r = CascadeResult(
        created=[uuid.uuid4()],
        rescheduled=[uuid.uuid4(), uuid.uuid4()],
        cancelled=[uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()],
    )
    assert r.has_changes is True
    s = r.summary()
    assert "+1 напоминание" in s
    assert "перенёс 2 напоминания" in s
    assert "отменил 5 напоминаний" in s


# ──────────────────────────────────────────────────
# apply_cascade — mock session
# ──────────────────────────────────────────────────


def _make_session(
    pending_rems: list[dict] | None = None,
    pending_after_pass1: list[tuple] | None = None,
) -> MagicMock:
    """Mock-сессия эмулирует 2 SELECT'а: pending reminders, затем reminders-after-pass1.

    SQLAlchemy session.execute().mappings().all() → list[dict].
    """
    session = MagicMock()

    select_results = [
        # Pass 1 SELECT
        _mock_mappings_result(pending_rems or []),
        # Pass 2 SELECT (text-only)
        _mock_rows_result(pending_after_pass1 or []),
    ]
    update_results = [_mock_update_result() for _ in range(20)]  # с запасом на UPDATE
    queue = list(select_results) + list(update_results)

    async def execute(*args, **kwargs):
        # Возвращаем по порядку. Тесту важен порядок SELECT, UPDATE'ы возвращают
        # «пустой» mock.
        return queue.pop(0) if queue else _mock_update_result()
    session.execute = AsyncMock(side_effect=execute)
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


def _mock_mappings_result(items: list[dict]) -> MagicMock:
    r = MagicMock()
    mappings = MagicMock()
    mappings.all = MagicMock(return_value=items)
    r.mappings = MagicMock(return_value=mappings)
    return r


def _mock_rows_result(rows: list[tuple]) -> MagicMock:
    r = MagicMock()
    r.all = MagicMock(return_value=rows)
    return r


def _mock_update_result() -> MagicMock:
    r = MagicMock()
    r.rowcount = 1
    return r


@pytest.mark.asyncio
async def test_cascade_no_changes_when_structured_unchanged():
    """Старая = новая → 0 изменений."""
    session = _make_session()
    sd = {"type": "task_list", "tasks": [{"text": "молоко"}]}
    result = await apply_cascade(
        session, bookmark_id=uuid.uuid4(), user_id=uuid.uuid4(),
        old_structured=sd, new_structured=sd,
    )
    assert not result.has_changes


@pytest.mark.asyncio
async def test_cascade_cancels_removed_item():
    """Item «молоко» удалён → reminder cancelled."""
    rid = uuid.uuid4()
    session = _make_session(
        pending_rems=[{
            "id": rid,
            "fire_at": datetime(2099, 1, 1, tzinfo=timezone.utc),
            "payload": {"text": "молоко", "task_list_id": "x"},
            "status": "pending",
        }],
        pending_after_pass1=[],  # после cancel pass1 ничего pending не осталось
    )
    old = {"tasks": [{"text": "молоко"}, {"text": "хлеб"}]}
    new = {"tasks": [{"text": "хлеб"}]}
    result = await apply_cascade(
        session, bookmark_id=uuid.uuid4(), user_id=uuid.uuid4(),
        old_structured=old, new_structured=new,
    )
    assert rid in result.cancelled
    assert not result.rescheduled
    assert not result.created


@pytest.mark.asyncio
async def test_cascade_creates_for_new_item_with_deadline():
    """Новый item с deadline → создан reminder."""
    session = _make_session(
        pending_rems=[],
        pending_after_pass1=[],  # ни одного существующего
    )
    old = {"tasks": [{"text": "молоко"}]}
    new = {"tasks": [
        {"text": "молоко"},
        {"text": "врач", "deadline": "2099-05-15"},
    ]}
    result = await apply_cascade(
        session, bookmark_id=uuid.uuid4(), user_id=uuid.uuid4(),
        old_structured=old, new_structured=new, user_tz="Europe/Moscow",
    )
    assert len(result.created) == 1
    assert session.add.call_count == 1
    rem = session.add.call_args_list[0].args[0]
    assert rem.payload["text"] == "врач"
    assert rem.payload["source"] == "cascade_added"
    assert rem.payload["item_index"] == 1


@pytest.mark.asyncio
async def test_cascade_skips_new_item_without_deadline():
    """Новый item без deadline → не создаём reminder."""
    session = _make_session(pending_rems=[], pending_after_pass1=[])
    old = {"tasks": [{"text": "молоко"}]}
    new = {"tasks": [{"text": "молоко"}, {"text": "сыр"}]}
    result = await apply_cascade(
        session, bookmark_id=uuid.uuid4(), user_id=uuid.uuid4(),
        old_structured=old, new_structured=new,
    )
    assert result.created == []
    assert session.add.call_count == 0


@pytest.mark.asyncio
async def test_cascade_skips_existing_text_in_pass2():
    """Если у existing reminder уже есть тот же text — pass2 не создаёт дубль."""
    session = _make_session(
        pending_rems=[],
        pending_after_pass1=[("молоко",)],  # уже есть reminder с text=молоко
    )
    old = {"tasks": []}
    new = {"tasks": [{"text": "молоко", "deadline": "2099-05-15"}]}
    result = await apply_cascade(
        session, bookmark_id=uuid.uuid4(), user_id=uuid.uuid4(),
        old_structured=old, new_structured=new,
    )
    assert result.created == []


@pytest.mark.asyncio
async def test_cascade_handles_none_structured():
    """Защита от None — не падаем."""
    session = _make_session(pending_rems=[], pending_after_pass1=[])
    result = await apply_cascade(
        session, bookmark_id=uuid.uuid4(), user_id=uuid.uuid4(),
        old_structured=None, new_structured=None,
    )
    assert not result.has_changes


@pytest.mark.asyncio
async def test_cascade_ignores_invalid_deadline_for_new_item():
    """Невалидный deadline (прошедший / битый) → не создаём reminder."""
    session = _make_session(pending_rems=[], pending_after_pass1=[])
    old = {"tasks": []}
    new = {"tasks": [
        {"text": "past", "deadline": "2020-01-01"},
        {"text": "bad", "deadline": "not-a-date"},
    ]}
    result = await apply_cascade(
        session, bookmark_id=uuid.uuid4(), user_id=uuid.uuid4(),
        old_structured=old, new_structured=new,
    )
    assert result.created == []
