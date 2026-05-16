"""Functional coverage for the Phase 2.6 T7 cross-package seam.

`bot/handlers/tasks/nl_edit.py:_handle_remind_on_task_list` lazily imports
five symbols from the (separately-split) `bot.handlers.reminders` package
and then calls `bot.services.nl_date.parse`. The q21 split shipped a
facade gap here that no test caught (479 green) because nothing exercised
this path. These tests run the path end-to-end with mocked I/O so any
future regression — missing re-export OR behaviour drift — fails fast.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


def _api(tz="Europe/Moscow"):
    api = AsyncMock()
    api.get_me = AsyncMock(return_value={"timezone": tz})
    api.get_bookmark = AsyncMock(
        return_value={"title": "Покупки", "summary": None}
    )
    api.create_reminder = AsyncMock(return_value={"id": "r1"})
    return api


@pytest.mark.asyncio
async def test_empty_body_asks_when():
    """Empty body → prompt, no reminder created. Exercises the lazy import."""
    from bot.handlers.tasks.nl_edit import _handle_remind_on_task_list

    msg = AsyncMock()
    api = _api()
    await _handle_remind_on_task_list(msg, api, "tok", "bid-1", "   ")

    msg.answer.assert_awaited_once()
    assert "Когда напомнить" in msg.answer.await_args.args[0]
    api.create_reminder.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_time_creates_reminder():
    """`завтра в 9` → reminder created against the task_list, confirmed."""
    from bot.handlers.tasks.nl_edit import _handle_remind_on_task_list

    msg = AsyncMock()
    api = _api()
    await _handle_remind_on_task_list(msg, api, "tok", "bid-1", "завтра в 9")

    api.create_reminder.assert_awaited_once()
    _args, kwargs = api.create_reminder.await_args
    assert kwargs["bookmark_id"] == "bid-1"
    assert kwargs["payload"]["source"] == "reply_remind_task_list"
    assert kwargs["payload"]["task_list_id"] == "bid-1"
    # Confirmation references the list title (HTML-escaped via _safe).
    confirm = msg.answer.await_args.args[0]
    assert "Покупки" in confirm and "Напомню" in confirm


@pytest.mark.asyncio
async def test_unparseable_time_shows_examples():
    """Garbage time → error with TIME_EXAMPLES, no reminder."""
    from bot.handlers.tasks.nl_edit import _handle_remind_on_task_list

    msg = AsyncMock()
    api = _api()
    await _handle_remind_on_task_list(
        msg, api, "tok", "bid-1", "когда-нибудь потом возможно"
    )

    api.create_reminder.assert_not_awaited()
    text = msg.answer.await_args.args[0]
    assert "Не понял время" in text


@pytest.mark.asyncio
async def test_bookmark_lookup_failure_is_handled():
    """get_bookmark raising → graceful 'Не нашёл этот список', no crash."""
    from bot.handlers.tasks.nl_edit import _handle_remind_on_task_list

    msg = AsyncMock()
    api = _api()
    api.get_bookmark = AsyncMock(side_effect=RuntimeError("404"))
    await _handle_remind_on_task_list(msg, api, "tok", "bid-1", "завтра в 9")

    api.create_reminder.assert_not_awaited()
    assert "Не нашёл этот список" in msg.answer.await_args.args[0]
