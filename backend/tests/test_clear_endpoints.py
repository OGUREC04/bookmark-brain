"""Unit-тесты bulk-эндпоинтов /clearlists и /clearreminders (без БД)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


@pytest.fixture
def user():
    u = MagicMock()
    u.id = uuid4()
    return u


@pytest.fixture
def session():
    s = AsyncMock()
    s.flush = AsyncMock()
    return s


class TestArchiveAllTaskLists:
    async def test_returns_archived_count(self, user, session):
        from app.api.bookmarks import archive_all_task_lists
        session.execute = AsyncMock(return_value=MagicMock(rowcount=6))

        out = await archive_all_task_lists(user, session)

        assert out == {"archived": 6}
        session.execute.assert_awaited_once()
        session.flush.assert_awaited_once()

    async def test_zero_when_nothing(self, user, session):
        from app.api.bookmarks import archive_all_task_lists
        session.execute = AsyncMock(return_value=MagicMock(rowcount=0))
        out = await archive_all_task_lists(user, session)
        assert out == {"archived": 0}


class TestCancelAllPending:
    async def test_returns_cancelled_count(self, user, session):
        from app.api.reminders import cancel_all_pending
        session.execute = AsyncMock(return_value=MagicMock(rowcount=3))

        out = await cancel_all_pending(user, session)

        assert out == {"cancelled": 3}
        session.execute.assert_awaited_once()
        session.flush.assert_awaited_once()

    async def test_zero_when_nothing(self, user, session):
        from app.api.reminders import cancel_all_pending
        session.execute = AsyncMock(return_value=MagicMock(rowcount=0))
        out = await cancel_all_pending(user, session)
        assert out == {"cancelled": 0}
