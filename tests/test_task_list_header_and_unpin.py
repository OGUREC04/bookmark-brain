"""Tests: #3 нейтральная шапка списка + #7 автооткреп при выполнении.

#3 — оба рендерера (bot + backend) дают LIST_HEADER без AI-заголовка,
синхронны; общий срок по-прежнему дописывается.
#7 — _all_tasks_done / _maybe_autounpin / _rerender_with_autounpin:
открепляем когда все пункты done, slow-path не перепинивает.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest

from aiogram.exceptions import TelegramBadRequest

from app.services.task_list_renderer import LIST_HEADER as BACKEND_HEADER
from app.services.task_list_renderer import render_task_list_text
from bot.handlers.tasks.shared import (
    LIST_HEADER,
    _all_tasks_done,
    _maybe_autounpin,
    _render_text,
    _rerender_with_autounpin,
)

_SD = {
    "type": "task_list",
    "tasks": [
        {"text": "молоко", "done": False},
        {"text": "хлеб", "done": False},
    ],
}


# ───────────────────── #3 header ─────────────────────


class TestNeutralHeader:
    def test_renderers_share_constant(self):
        assert LIST_HEADER == BACKEND_HEADER == "📋 <b>Список</b>"

    def test_bot_render_drops_ai_title(self):
        out = _render_text("Галлюцинация Утром Вечером", _SD)
        assert "📋 <b>Список</b>" in out
        assert "Галлюцинация" not in out

    def test_backend_render_drops_ai_title(self):
        out = render_task_list_text("Галлюцинация Утром Вечером", _SD)
        assert "📋 <b>Список</b>" in out
        assert "Галлюцинация" not in out

    def test_both_renderers_identical(self):
        a = _render_text("X", _SD, silent=True)
        b = render_task_list_text("X", _SD, silent=True)
        assert a == b

    def test_common_deadline_still_shown(self):
        sd = {**_SD, "common_deadline": "2026-05-20T00:00:00"}
        out = _render_text(None, sd)
        assert "⏰" in out and "20.05" in out


# ───────────────────── #7 auto-unpin ─────────────────────


class TestAllTasksDone:
    def test_empty_is_false(self):
        assert _all_tasks_done({"tasks": []}) is False
        assert _all_tasks_done({}) is False

    def test_all_done_true(self):
        assert _all_tasks_done(
            {"tasks": [{"text": "a", "done": True}, {"text": "b", "done": True}]}
        ) is True

    def test_partial_false(self):
        assert _all_tasks_done(
            {"tasks": [{"text": "a", "done": True}, {"text": "b", "done": False}]}
        ) is False


class TestMaybeAutounpin:
    async def test_unpins_when_all_done(self):
        bot = AsyncMock()
        await _maybe_autounpin(bot, 100, 999, {"tasks": [{"text": "a", "done": True}]})
        bot.unpin_chat_message.assert_awaited_once_with(100, 999)

    async def test_noop_when_not_all_done(self):
        bot = AsyncMock()
        await _maybe_autounpin(bot, 100, 999, _SD)
        bot.unpin_chat_message.assert_not_awaited()

    async def test_swallows_telegram_error(self):
        bot = AsyncMock()
        bot.unpin_chat_message = AsyncMock(
            side_effect=TelegramBadRequest(method=None, message="nothing to unpin")
        )
        # не должно бросать
        await _maybe_autounpin(bot, 100, 999, {"tasks": [{"text": "a", "done": True}]})


class TestRerenderWithAutounpin:
    async def test_all_done_no_repin_and_unpins(self):
        bot = AsyncMock()
        updated = {"structured_data": {"tasks": [{"text": "a", "done": True}]}}
        with patch(
            "bot.handlers.tasks.shared._rerender_at_bottom",
            new=AsyncMock(return_value=777),
        ) as rer:
            await _rerender_with_autounpin(bot, 100, 555, updated, store=None)
        assert rer.await_args.kwargs["keep_pinned"] is False
        bot.unpin_chat_message.assert_awaited_once_with(100, 777)

    async def test_partial_keeps_pin_no_unpin(self):
        bot = AsyncMock()
        updated = {"structured_data": _SD}
        with patch(
            "bot.handlers.tasks.shared._rerender_at_bottom",
            new=AsyncMock(return_value=777),
        ) as rer:
            await _rerender_with_autounpin(bot, 100, 555, updated, store=None)
        assert rer.await_args.kwargs["keep_pinned"] is True
        bot.unpin_chat_message.assert_not_awaited()
