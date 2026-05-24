"""Wiring-тест: PATCH /bookmarks/{id} триггерит reminder-cascade при
изменении structured_data (Mini App редактирует дедлайны), с дешёвым
guard'ом для холостых апдейтов (тоггл done, правка title)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.api.bookmarks import update_bookmark
from app.schemas import BookmarkUpdate


@pytest.fixture
def user():
    u = MagicMock()
    u.id = uuid4()
    u.timezone = "Europe/Moscow"
    return u


def _session_returning(bookmark) -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=bookmark)
    s = AsyncMock()
    s.execute = AsyncMock(return_value=result)
    return s


def _bookmark(structured):
    bm = MagicMock()
    bm.id = uuid4()
    bm.structured_data = structured
    return bm


async def test_cascade_invoked_when_deadline_added(user, monkeypatch):
    """structured_data меняется (добавлен дедлайн) → apply_cascade зовётся."""
    bm = _bookmark({"type": "task_list", "tasks": [{"text": "врач"}]})
    session = _session_returning(bm)

    cascade = AsyncMock()
    monkeypatch.setattr("app.services.reminder_cascade.apply_cascade", cascade)

    body = BookmarkUpdate(structured_data={
        "type": "task_list",
        "tasks": [{"text": "врач", "deadline": "2099-05-15"}],
    })
    await update_bookmark(bm.id, body, user, session)

    cascade.assert_awaited_once()
    # old/new прокинуты корректно
    kwargs = cascade.await_args.kwargs
    assert kwargs["old_structured"]["tasks"][0] == {"text": "врач"}
    assert kwargs["new_structured"]["tasks"][0]["deadline"] == "2099-05-15"
    assert kwargs["user_tz"] == "Europe/Moscow"


async def test_cascade_skipped_on_done_toggle(user, monkeypatch):
    """Изменилась только галочка done → guard пропускает cascade."""
    bm = _bookmark({"type": "task_list", "tasks": [{"text": "врач", "done": False}]})
    session = _session_returning(bm)

    cascade = AsyncMock()
    monkeypatch.setattr("app.services.reminder_cascade.apply_cascade", cascade)

    body = BookmarkUpdate(structured_data={
        "type": "task_list",
        "tasks": [{"text": "врач", "done": True}],
    })
    await update_bookmark(bm.id, body, user, session)

    cascade.assert_not_awaited()


async def test_cascade_skipped_when_structured_not_touched(user, monkeypatch):
    """PATCH меняет только title → cascade не зовётся."""
    bm = _bookmark({"type": "task_list", "tasks": [{"text": "врач"}]})
    session = _session_returning(bm)

    cascade = AsyncMock()
    monkeypatch.setattr("app.services.reminder_cascade.apply_cascade", cascade)

    body = BookmarkUpdate(title="новый заголовок")
    await update_bookmark(bm.id, body, user, session)

    cascade.assert_not_awaited()


async def test_cascade_failure_does_not_break_patch(user, monkeypatch):
    """Падение каскада best-effort — PATCH всё равно возвращает bookmark."""
    bm = _bookmark({"type": "task_list", "tasks": [{"text": "врач"}]})
    session = _session_returning(bm)

    async def _boom(*_a, **_k):
        raise RuntimeError("db down")
    monkeypatch.setattr("app.services.reminder_cascade.apply_cascade", _boom)

    body = BookmarkUpdate(structured_data={
        "type": "task_list",
        "tasks": [{"text": "врач", "deadline": "2099-05-15"}],
    })
    out = await update_bookmark(bm.id, body, user, session)
    assert out is bm
