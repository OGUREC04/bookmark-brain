"""Tests: #6 /lists (отдельная история списков) + #5 /unpin (открепить все).

Хэндлеры юнит-уровнем (api/store/message замоканы). Бэкенд-фильтр
structured_type проверяется тем, что api.get_bookmarks вызывается
именно с structured_type='task_list'.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest


@pytest.fixture(autouse=True)
def patch_ensure_user(monkeypatch):
    async def _fake(*_a, **_k):
        return "tok"
    import bot.common.auth
    monkeypatch.setattr(bot.common.auth, "ensure_user", _fake)
    # ensure_user в start.py импортится как модульный символ
    import bot.handlers.start as st
    monkeypatch.setattr(st, "ensure_user", _fake)


# ───────────────────── #6 /lists ─────────────────────


class TestCmdLists:
    async def test_filters_by_task_list_and_renders(self):
        from bot.handlers.tasks.lists import cmd_lists
        msg = MagicMock()
        msg.text = "/lists"
        msg.answer = AsyncMock()
        api = AsyncMock()
        api.get_bookmarks = AsyncMock(return_value={
            "items": [{
                "id": "b1", "title": "Покупки",
                "structured_data": {
                    "type": "task_list",
                    "tasks": [
                        {"text": "молоко", "done": True},
                        {"text": "хлеб", "done": False},
                    ],
                },
            }],
            "total": 1,
        })
        await cmd_lists(msg, api)

        api.get_bookmarks.assert_awaited_once()
        assert api.get_bookmarks.await_args.kwargs["structured_type"] == "task_list"
        msg.answer.assert_awaited()
        sent = msg.answer.await_args.args[0]
        assert "Списки задач" in sent
        assert "Покупки" in sent
        assert "1/2" in sent  # прогресс done/total

    async def test_empty_lists_hint(self):
        from bot.handlers.tasks.lists import cmd_lists
        msg = MagicMock()
        msg.text = "/lists"
        msg.answer = AsyncMock()
        api = AsyncMock()
        api.get_bookmarks = AsyncMock(return_value={"items": [], "total": 0})
        await cmd_lists(msg, api)
        assert "нет списков" in msg.answer.await_args.args[0].lower()


# ───────────────────── #5 /unpin ─────────────────────


class TestCmdUnpinAll:
    async def test_calls_unpin_all_chat_messages(self):
        """unpin_all_chat_messages — единый вызов Telegram, не зависит
        от Redis-реестра (старые пины тоже снимаются)."""
        from bot.handlers.tasks.commands import cmd_unpin_all
        msg = MagicMock()
        msg.chat = MagicMock(id=100)
        msg.bot = AsyncMock()
        msg.answer = AsyncMock()
        await cmd_unpin_all(msg, AsyncMock(), AsyncMock())

        msg.bot.unpin_all_chat_messages.assert_awaited_once_with(100)
        assert "Открепил" in msg.answer.await_args.args[0]

    async def test_swallows_unpin_errors(self):
        from aiogram.exceptions import TelegramBadRequest

        from bot.handlers.tasks.commands import cmd_unpin_all
        msg = MagicMock()
        msg.chat = MagicMock(id=100)
        msg.bot = AsyncMock()
        msg.bot.unpin_all_chat_messages = AsyncMock(
            side_effect=TelegramBadRequest(method=None, message="no rights")
        )
        msg.answer = AsyncMock()
        # не должно бросать; юзер всё равно увидит подтверждение
        await cmd_unpin_all(msg, AsyncMock(), AsyncMock())
        msg.answer.assert_awaited()


# ───────────────────── api_client param ─────────────────────


class TestApiClientParam:
    async def test_get_bookmarks_passes_structured_type(self):
        from bot.api_client import BackendClient
        c = BackendClient.__new__(BackendClient)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"items": [], "total": 0})
        c.client = MagicMock()
        c.client.get = AsyncMock(return_value=resp)
        await c.get_bookmarks("tok", page=2, structured_type="task_list")
        params = c.client.get.await_args.kwargs["params"]
        assert params["structured_type"] == "task_list"
        assert params["page"] == 2

    async def test_get_bookmarks_omits_param_when_none(self):
        from bot.api_client import BackendClient
        c = BackendClient.__new__(BackendClient)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"items": [], "total": 0})
        c.client = MagicMock()
        c.client.get = AsyncMock(return_value=resp)
        await c.get_bookmarks("tok")
        assert "structured_type" not in c.client.get.await_args.kwargs["params"]
