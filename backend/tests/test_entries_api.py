"""Unit-тесты note-entries API — без БД, фокус на IDOR/валидацию/CRUD.

Полный путь с реальной Postgres — интеграционно (после поднятия Docker).
Паттерн моков — как test_recurring_api.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.api.entries import create_entry, delete_entry, get_thread, update_entry
from app.models import NoteEntry
from app.schemas import EntryCreate, EntryResponse, EntryUpdate
from fastapi import HTTPException


@pytest.fixture
def user():
    u = MagicMock()
    u.id = uuid4()
    return u


@pytest.fixture(autouse=True)
def _mock_arq_pool():
    """Дописки ставят debounce-reindex джоб — мокаем arq-пул, чтобы не лезть в redis."""
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock()
    with patch("app.api.entries.get_arq_pool", new=AsyncMock(return_value=pool)):
        yield pool


def _owner(found: bool):
    res = MagicMock()
    res.scalar_one_or_none.return_value = uuid4() if found else None
    return res


def _scalars(rows):
    res = MagicMock()
    res.scalars.return_value.all.return_value = rows
    return res


def _one(entry):
    res = MagicMock()
    res.scalar_one_or_none.return_value = entry
    return res


def _session(*results):
    s = AsyncMock()
    s.add = MagicMock()
    s.flush = AsyncMock()
    s.refresh = AsyncMock()
    s.execute = AsyncMock(side_effect=list(results))
    return s


def _entry(**over):
    base = dict(
        id=uuid4(), bookmark_id=uuid4(), kind="user", body="мысль",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), edited_at=None,
        is_deleted=False, media_file_id=None, transcription=None,
        duration=None, entry_ai_status=None,
    )
    base.update(over)
    return NoteEntry(**base)


class TestEntrySchema:
    def test_response_is_flat_no_voice_object(self):
        # DEC-4: плоская форма — голосовые поля на верхнем уровне, без вложенного voice{}.
        fields = EntryResponse.model_fields
        assert "voice" not in fields
        for f in ("transcription", "duration", "entry_ai_status", "edited_at"):
            assert f in fields


class TestGetThread:
    async def test_idor_404_for_foreign_note(self, user):
        session = _session(_owner(found=False))  # до выборки записей не дойдём
        with pytest.raises(HTTPException) as exc:
            await get_thread(uuid4(), user, session)
        assert exc.value.status_code == 404

    async def test_returns_non_deleted_entries(self, user):
        bid = uuid4()
        entries = [_entry(bookmark_id=bid), _entry(bookmark_id=bid)]
        session = _session(_owner(True), _scalars(entries))
        res = await get_thread(bid, user, session)
        assert res.total == 2
        assert len(res.entries) == 2


class TestCreateEntry:
    async def test_creates_user_entry_trimmed(self, user):
        bid = uuid4()
        session = _session(_owner(True))
        await create_entry(bid, EntryCreate(body="  купить молоко  "), user, session)
        session.add.assert_called_once()
        added = session.add.call_args[0][0]
        assert isinstance(added, NoteEntry)
        assert added.kind == "user"
        assert added.body == "купить молоко"  # триммится
        assert added.bookmark_id == bid

    async def test_schedules_debounced_reindex(self, user, _mock_arq_pool):
        bid = uuid4()
        session = _session(_owner(True))
        await create_entry(bid, EntryCreate(body="x"), user, session)
        _mock_arq_pool.enqueue_job.assert_awaited_once()
        args, kwargs = _mock_arq_pool.enqueue_job.call_args
        assert args[0] == "reembed_bookmark_task"
        assert kwargs["_job_id"] == f"reembed:{bid}"  # debounce-дедуп по заметке

    async def test_empty_body_422(self, user):
        session = _session(_owner(True))
        with pytest.raises(HTTPException) as exc:
            await create_entry(uuid4(), EntryCreate(body="   "), user, session)
        assert exc.value.status_code == 422
        session.add.assert_not_called()

    async def test_idor_404(self, user):
        session = _session(_owner(False))
        with pytest.raises(HTTPException) as exc:
            await create_entry(uuid4(), EntryCreate(body="x"), user, session)
        assert exc.value.status_code == 404
        session.add.assert_not_called()


class TestUpdateEntry:
    async def test_sets_edited_at(self, user):
        bid = uuid4()
        entry = _entry(bookmark_id=bid, body="old")
        session = _session(_owner(True), _one(entry))
        await update_entry(bid, entry.id, EntryUpdate(body="new"), user, session)
        assert entry.body == "new"
        assert entry.edited_at is not None

    async def test_404_when_missing(self, user):
        session = _session(_owner(True), _one(None))
        with pytest.raises(HTTPException) as exc:
            await update_entry(uuid4(), uuid4(), EntryUpdate(body="x"), user, session)
        assert exc.value.status_code == 404

    async def test_empty_body_422(self, user):
        entry = _entry()
        session = _session(_owner(True), _one(entry))
        with pytest.raises(HTTPException) as exc:
            await update_entry(uuid4(), entry.id, EntryUpdate(body="  "), user, session)
        assert exc.value.status_code == 422

    async def test_idor_404_foreign_note(self, user):
        session = _session(_owner(False))  # чужая заметка → до выборки записи не дойдём
        with pytest.raises(HTTPException) as exc:
            await update_entry(uuid4(), uuid4(), EntryUpdate(body="x"), user, session)
        assert exc.value.status_code == 404


class TestDeleteEntry:
    async def test_soft_delete(self, user):
        bid = uuid4()
        entry = _entry(bookmark_id=bid)
        session = _session(_owner(True), _one(entry))
        await delete_entry(bid, entry.id, user, session)
        assert entry.is_deleted is True

    async def test_404_when_missing(self, user):
        session = _session(_owner(True), _one(None))
        with pytest.raises(HTTPException) as exc:
            await delete_entry(uuid4(), uuid4(), user, session)
        assert exc.value.status_code == 404

    async def test_idor_404_foreign_note(self, user):
        session = _session(_owner(False))
        with pytest.raises(HTTPException) as exc:
            await delete_entry(uuid4(), uuid4(), user, session)
        assert exc.value.status_code == 404
