"""Тесты бота для /repeat (регулярные напоминания) + колбэков rrok/rrstop."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from bot.handlers.reminders.callbacks import cb_recurring_ok, cb_recurring_stop
from bot.handlers.reminders.repeat import _confirm_text, cmd_repeat


def _msg(args_text):
    m = MagicMock()
    m.answer = AsyncMock()
    m.from_user = MagicMock(id=1)
    cmd = MagicMock()
    cmd.args = args_text
    return m, cmd


def _cb(data):
    c = MagicMock()
    c.data = data
    c.from_user = MagicMock(id=1)
    c.message = MagicMock()
    c.message.edit_text = AsyncMock()
    c.answer = AsyncMock()
    return c


# ── _confirm_text ──


def test_confirm_text_new():
    t = _confirm_text({"text": "полить цветы", "hour": 10, "minute": 0})
    assert "Буду напоминать" in t
    assert "10:00" in t
    assert "полить цветы" in t


def test_confirm_text_dedup():
    t = _confirm_text(
        {"text": "полить цветы", "hour": 9, "minute": 5, "deduplicated": True}
    )
    assert "Уже напоминаю" in t
    assert "09:05" in t


# ── cmd_repeat ──


class TestCmdRepeat:
    async def test_empty_shows_help(self):
        m, cmd = _msg("")
        await cmd_repeat(m, cmd, AsyncMock(), AsyncMock())
        text = m.answer.call_args.args[0]
        assert "/repeat" in text

    async def test_success_creates_and_confirms(self):
        m, cmd = _msg("полить цветы каждый день в 10:00")
        api = AsyncMock()
        api.create_recurring = AsyncMock(
            return_value={"text": "полить цветы", "hour": 10, "minute": 0}
        )
        with patch(
            "bot.handlers.reminders.repeat.ensure_user",
            AsyncMock(return_value="tok"),
        ):
            await cmd_repeat(m, cmd, api, AsyncMock())
        api.create_recurring.assert_awaited_once()
        assert "Буду напоминать" in m.answer.call_args.args[0]

    async def test_422_relays_detail(self):
        m, cmd = _msg("полить цветы каждый день")
        req = httpx.Request("POST", "http://x")
        resp = httpx.Response(422, json={"detail": "Укажи время. Пример: …"}, request=req)
        api = AsyncMock()
        api.create_recurring = AsyncMock(
            side_effect=httpx.HTTPStatusError("422", request=req, response=resp)
        )
        with patch(
            "bot.handlers.reminders.repeat.ensure_user",
            AsyncMock(return_value="tok"),
        ):
            await cmd_repeat(m, cmd, api, AsyncMock())
        assert "Укажи время" in m.answer.call_args.args[0]


# ── колбэки ──


class TestRecurringCallbacks:
    async def test_ok_dismisses_no_api(self):
        c = _cb(f"rrok:{uuid4()}")
        api = AsyncMock()
        await cb_recurring_ok(c, api, AsyncMock())
        c.message.edit_text.assert_awaited_once()
        api.stop_recurring.assert_not_called()

    async def test_stop_invalid_uuid_no_api(self):
        c = _cb("rrstop:not-a-uuid")
        api = AsyncMock()
        await cb_recurring_stop(c, api, AsyncMock())
        api.stop_recurring.assert_not_called()
        c.answer.assert_awaited()

    async def test_stop_valid_calls_api_and_edits(self):
        rid = str(uuid4())
        c = _cb(f"rrstop:{rid}")
        api = AsyncMock()
        api.stop_recurring = AsyncMock()
        with patch(
            "bot.common.auth.ensure_user", AsyncMock(return_value="tok")
        ):
            await cb_recurring_stop(c, api, AsyncMock())
        api.stop_recurring.assert_awaited_once_with("tok", rid)
        assert "Больше не напоминаю" in c.message.edit_text.call_args.args[0]
