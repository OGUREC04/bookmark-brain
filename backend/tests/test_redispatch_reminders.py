"""Unit-тесты ied: re-dispatch reminder_decision после near-dup «сохрани как новую».

Покрывает:
- endpoint `redispatch_reminder_decision` (enqueue / no-op / IDOR)
- arq-джобу `redispatch_reminder_task` (загрузка + делегирование в dispatcher)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
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
    return s


def _bookmark(structured: dict | None):
    bm = MagicMock()
    bm.id = uuid4()
    bm.user_id = uuid4()
    bm.structured_data = structured
    return bm


def _exec_returning(bookmark):
    """session.execute → result.scalar_one_or_none() == bookmark."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=bookmark)
    return AsyncMock(return_value=result)


class TestRedispatchEndpoint:
    async def test_enqueues_when_decision_present(self, user, session):
        from app.api.reminders import redispatch_reminder_decision

        bm = _bookmark({"reminder_decision": {"form": "single_reminder", "items": []}})
        session.execute = _exec_returning(bm)

        pool = AsyncMock()
        with patch("app.api.bookmarks.get_arq_pool", AsyncMock(return_value=pool)):
            out = await redispatch_reminder_decision(
                bm.id, chat_id=100, current_user=user, session=session,
            )

        assert out == {"enqueued": True}
        pool.enqueue_job.assert_awaited_once()
        args = pool.enqueue_job.await_args.args
        assert args[0] == "redispatch_reminder_task"
        assert args[1] == str(bm.id)
        assert args[2] == 100

    async def test_noop_when_no_decision(self, user, session):
        from app.api.reminders import redispatch_reminder_decision

        bm = _bookmark({"type": "task_list"})  # decision отсутствует
        session.execute = _exec_returning(bm)

        with patch("app.api.bookmarks.get_arq_pool") as pool_factory:
            out = await redispatch_reminder_decision(
                bm.id, chat_id=100, current_user=user, session=session,
            )

        assert out == {"enqueued": False}
        pool_factory.assert_not_called()

    async def test_noop_when_already_applied(self, user, session):
        from app.api.reminders import redispatch_reminder_decision

        bm = _bookmark({
            "reminder_decision": {"form": "single_reminder", "items": []},
            "reminder_decision_applied": True,
        })
        session.execute = _exec_returning(bm)

        with patch("app.api.bookmarks.get_arq_pool") as pool_factory:
            out = await redispatch_reminder_decision(
                bm.id, chat_id=100, current_user=user, session=session,
            )

        assert out == {"enqueued": False}
        pool_factory.assert_not_called()

    async def test_404_when_bookmark_missing(self, user, session):
        from app.api.reminders import redispatch_reminder_decision
        from fastapi import HTTPException

        session.execute = _exec_returning(None)  # IDOR / not found

        with pytest.raises(HTTPException) as exc:
            await redispatch_reminder_decision(
                uuid4(), chat_id=100, current_user=user, session=session,
            )
        assert exc.value.status_code == 404


class TestRedispatchWorkerJob:
    async def test_delegates_to_dispatcher(self):
        from app.worker.processing import redispatch_reminder_task

        bm = _bookmark({"reminder_decision": {"form": "single_reminder", "items": []}})

        @asynccontextmanager
        async def _fake_session():
            s = AsyncMock()
            s.execute = _exec_returning(bm)
            yield s

        dispatch = AsyncMock(return_value=True)
        with (
            patch("app.database.async_session", _fake_session),
            patch("app.worker.processing._dispatch_reminder_decision", dispatch),
        ):
            out = await redispatch_reminder_task({}, str(bm.id), 100)

        assert out is True
        dispatch.assert_awaited_once()
        assert dispatch.await_args.kwargs.get("bookmark") is bm
        assert dispatch.await_args.kwargs.get("chat_id") == 100

    async def test_returns_false_when_bookmark_missing(self):
        from app.worker.processing import redispatch_reminder_task

        @asynccontextmanager
        async def _fake_session():
            s = AsyncMock()
            s.execute = _exec_returning(None)
            yield s

        with patch("app.database.async_session", _fake_session):
            out = await redispatch_reminder_task({}, str(uuid4()), 100)

        assert out is False
