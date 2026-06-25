"""Тесты для stale_list_nudge cron — фокус на анти-спам кэпе на юзера.

Регрессия: крон слал по сообщению на КАЖДЫЙ незакрытый список → у юзера с
накопленными списками 20+ сообщений за один прогон. Теперь не больше
_MAX_NUDGES_PER_USER_PER_RUN на юзера за прогон.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


class _ExecResult:
    def __init__(self, all_rows=None):
        self._all = all_rows or []

    def all(self):
        return self._all


def _bookmark(*, undone: int, done: int = 0, title="Список"):
    bm = MagicMock()
    bm.id = uuid4()
    bm.title = title
    bm.created_at = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    tasks = [{"text": f"d{i}", "done": True} for i in range(done)]
    tasks += [{"text": f"u{i}", "done": False} for i in range(undone)]
    bm.structured_data = {"type": "task_list", "tasks": tasks}
    return bm


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.exists = AsyncMock(return_value=0)   # ещё не nudged
    r.set = AsyncMock(return_value=True)   # SET NX успешен
    r.aclose = AsyncMock()
    return r


@pytest.fixture
def mock_session():
    return AsyncMock()


async def _run(rows, mock_session, mock_redis):
    from app.worker import stale_list_nudge

    mock_session.execute = AsyncMock(return_value=_ExecResult(all_rows=rows))
    send = AsyncMock(return_value={"message_id": 12345})

    with patch("app.database.async_session") as mk_sess, \
         patch("app.worker.scheduled.nudge._send_message", send), \
         patch("redis.asyncio.from_url", return_value=mock_redis):
        mk_sess.return_value.__aenter__.return_value = mock_session
        await stale_list_nudge({})
    return send


class TestStaleNudgeCap:
    async def test_caps_one_per_user(self, mock_session, mock_redis):
        """3 незакрытых списка одного юзера → только 1 nudge (анти-спам)."""
        uid = 999
        rows = [
            (_bookmark(undone=2), uid),
            (_bookmark(undone=1), uid),
            (_bookmark(undone=3), uid),
        ]
        send = await _run(rows, mock_session, mock_redis)
        assert send.await_count == 1

    async def test_cap_is_per_user_not_global(self, mock_session, mock_redis):
        """Лимит на КАЖДОГО юзера: 2 юзера по 3 списка → 2 nudge (по 1)."""
        rows = [
            (_bookmark(undone=1), 111),
            (_bookmark(undone=1), 111),
            (_bookmark(undone=1), 222),
            (_bookmark(undone=1), 222),
        ]
        send = await _run(rows, mock_session, mock_redis)
        assert send.await_count == 2

    async def test_fully_done_lists_skipped(self, mock_session, mock_redis):
        """Полностью выполненный список не считается и не шлётся."""
        rows = [
            (_bookmark(undone=0, done=3), 999),  # всё done → skip
            (_bookmark(undone=1), 999),          # этот уйдёт
        ]
        send = await _run(rows, mock_session, mock_redis)
        assert send.await_count == 1

    async def test_already_nudged_skipped(self, mock_session, mock_redis):
        """Если nudged:{bid} уже стоит — пропускаем (не считается в кэп)."""
        mock_redis.exists = AsyncMock(return_value=1)  # уже nudged
        rows = [(_bookmark(undone=2), 999)]
        send = await _run(rows, mock_session, mock_redis)
        assert send.await_count == 0
