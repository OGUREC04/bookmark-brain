"""Тесты /clearlists и /clearreminders — confirm-флоу + bulk-вызовы API."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Message

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture(autouse=True)
def patch_ensure_user(monkeypatch):
    async def _fake(*_a, **_k):
        return "tok"
    import bot.handlers.clear as clr
    monkeypatch.setattr(clr, "ensure_user", _fake)


def _msg():
    m = MagicMock()
    m.answer = AsyncMock(return_value=MagicMock(message_id=888))
    return m


def _callback():
    cb = MagicMock()
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()
    return cb


# ─── /clearlists ───


class TestClearLists:
    async def test_shows_confirm_when_lists_exist(self):
        from bot.handlers.clear import cmd_clear_lists
        msg = _msg()
        api = AsyncMock()
        api.get_bookmarks = AsyncMock(return_value={"total": 5})

        await cmd_clear_lists(msg, api)

        api.get_bookmarks.assert_awaited_once()
        # фильтр именно неархивных task_list
        kwargs = api.get_bookmarks.await_args.kwargs
        assert kwargs["structured_type"] == "task_list"
        assert kwargs["is_archived"] is False
        # показан confirm с кнопкой
        _, call_kwargs = msg.answer.call_args
        assert call_kwargs.get("reply_markup") is not None
        assert "5" in msg.answer.call_args.args[0]

    async def test_noop_when_no_lists(self):
        from bot.handlers.clear import cmd_clear_lists
        msg = _msg()
        api = AsyncMock()
        api.get_bookmarks = AsyncMock(return_value={"total": 0})

        await cmd_clear_lists(msg, api)
        assert msg.answer.call_args.kwargs.get("reply_markup") is None

    async def test_confirm_archives_and_reports_count(self):
        from bot.handlers.clear import cb_clear_lists_confirm
        cb = _callback()
        api = AsyncMock()
        api.archive_all_task_lists = AsyncMock(return_value={"archived": 7})

        await cb_clear_lists_confirm(cb, api)

        api.archive_all_task_lists.assert_awaited_once_with("tok")
        assert "7" in cb.message.edit_text.call_args.args[0]


# ─── /clearreminders ───


class TestClearReminders:
    async def test_shows_confirm_when_pending_exist(self):
        from bot.handlers.clear import cmd_clear_reminders
        msg = _msg()
        api = AsyncMock()
        api.list_upcoming_reminders = AsyncMock(return_value={"total": 3})

        await cmd_clear_reminders(msg, api)

        api.list_upcoming_reminders.assert_awaited_once()
        assert msg.answer.call_args.kwargs.get("reply_markup") is not None
        assert "3" in msg.answer.call_args.args[0]

    async def test_noop_when_no_pending(self):
        from bot.handlers.clear import cmd_clear_reminders
        msg = _msg()
        api = AsyncMock()
        api.list_upcoming_reminders = AsyncMock(return_value={"total": 0})

        await cmd_clear_reminders(msg, api)
        assert msg.answer.call_args.kwargs.get("reply_markup") is None

    async def test_confirm_cancels_and_reports_count(self):
        from bot.handlers.clear import cb_clear_reminders_confirm
        cb = _callback()
        api = AsyncMock()
        api.cancel_all_reminders = AsyncMock(return_value={"cancelled": 4})

        await cb_clear_reminders_confirm(cb, api)

        api.cancel_all_reminders.assert_awaited_once_with("tok")
        assert "4" in cb.message.edit_text.call_args.args[0]


class TestClearCancel:
    async def test_cancel_touches_nothing(self):
        from bot.handlers.clear import cb_clear_cancel
        cb = _callback()
        await cb_clear_cancel(cb)
        cb.message.edit_text.assert_awaited_once()
        cb.answer.assert_awaited_once()
