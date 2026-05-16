"""Tests for /tz bot command handler."""
from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from bot.handlers.timezone import cmd_tz


@pytest.fixture
def api():
    """Mock BackendClient with default user response."""
    mock = AsyncMock()
    mock.get_me = AsyncMock(
        return_value={"id": "u1", "telegram_id": 999, "timezone": "Europe/Moscow"}
    )
    mock.update_timezone = AsyncMock(return_value={"timezone": "Europe/Kaliningrad"})
    return mock


@pytest.fixture
def msg(mock_message):
    """Message factory with /tz pre-set."""
    m = mock_message()
    m.text = "/tz"
    m.answer = AsyncMock()
    return m


@pytest.fixture(autouse=True)
def patch_ensure_user(monkeypatch):
    """`_ensure_user` returns fake token, не зависит от реального API."""
    async def _fake(*_args, **_kwargs):
        return "fake-token"

    import bot.common.auth
    monkeypatch.setattr(bot.common.auth, "ensure_user", _fake)


class TestCmdTz:
    async def test_no_args_shows_current(self, msg, api):
        """`/tz` без аргументов → показать текущий пояс + хелп."""
        await cmd_tz(msg, api)
        api.get_me.assert_called_once()
        api.update_timezone.assert_not_called()
        assert msg.answer.called
        sent = msg.answer.call_args[0][0]
        assert "Europe/Moscow" in sent

    async def test_set_valid_zone(self, msg, api):
        """`/tz Europe/Kaliningrad` → вызывает update_timezone."""
        msg.text = "/tz Europe/Kaliningrad"
        await cmd_tz(msg, api)
        api.update_timezone.assert_called_once_with("fake-token", "Europe/Kaliningrad")
        sent = msg.answer.call_args[0][0]
        assert "Europe/Kaliningrad" in sent

    async def test_reset_to_default(self, msg, api):
        """`/tz reset` → set Europe/Moscow."""
        msg.text = "/tz reset"
        await cmd_tz(msg, api)
        api.update_timezone.assert_called_once_with("fake-token", "Europe/Moscow")

    async def test_invalid_zone_shows_help(self, msg, api):
        """Бэкенд вернул 400 → бот показывает help, не падает."""
        request = httpx.Request("PATCH", "http://test/tz")
        response = httpx.Response(400, request=request)
        api.update_timezone.side_effect = httpx.HTTPStatusError(
            "bad", request=request, response=response
        )
        msg.text = "/tz NotARealZone/Foo"
        await cmd_tz(msg, api)
        sent = msg.answer.call_args[0][0]
        assert "NotARealZone" in sent or "не похож" in sent

    async def test_server_error_shows_message(self, msg, api):
        """Бэкенд вернул 500 → бот пишет 'Ошибка сервера', не падает."""
        request = httpx.Request("PATCH", "http://test/tz")
        response = httpx.Response(500, request=request)
        api.update_timezone.side_effect = httpx.HTTPStatusError(
            "server", request=request, response=response
        )
        msg.text = "/tz Europe/Kaliningrad"
        await cmd_tz(msg, api)
        sent = msg.answer.call_args[0][0]
        assert "Ошибка" in sent
