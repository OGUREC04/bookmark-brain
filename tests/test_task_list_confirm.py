"""Tests: подтверждение перед созданием списка + #10 фидбэк near-dup.

Покрывает:
- worker `_maybe_offer_task_list` — offer показан/нет, Redis-стейт
- bot `cb_tasklist_confirm` (tlc:) — create+bind+pin+favorite, stale
- bot `cb_tasklist_decline` (tlx:) — structured_data=None, verbose/silent
- #10 `_react_src` — реакция на исходное сообщение, no-op без src
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
        return "fake-token"
    import bot.common.auth
    monkeypatch.setattr(bot.common.auth, "ensure_user", _fake)


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
    async def set(self, k, v, ex=None):
        self.store[k] = v
    async def delete(self, *ks):
        for k in ks:
            self.store.pop(k, None)
    async def aclose(self):
        pass


def _bookmark_obj(bid="bid-1", n=2):
    bm = MagicMock()
    bm.id = bid
    bm.structured_data = {
        "type": "task_list",
        "tasks": [{"text": f"t{i}", "done": False} for i in range(n)],
    }
    return bm


# ───────────────────── worker offer ─────────────────────


class TestWorkerOffer:
    async def test_no_chat_id_returns_false(self):
        from app.worker.task_list_offer import _maybe_offer_task_list
        ok = await _maybe_offer_task_list(
            bookmark=_bookmark_obj(), chat_id=None, message_id=1, silent=True,
        )
        assert ok is False

    async def test_offer_sent_stores_pending_state(self):
        from app.worker import task_list_offer as mod
        fake = _FakeRedis()
        with patch.object(mod, "aioredis_from_url", return_value=fake), \
             patch.object(mod, "_send_message",
                          AsyncMock(return_value={"message_id": 777})):
            ok = await mod._maybe_offer_task_list(
                bookmark=_bookmark_obj("bid-X"), chat_id=42,
                message_id=9, silent=True,
            )
        assert ok is True
        raw = fake.store.get("task_list_pending:42:777")
        assert raw is not None
        payload = json.loads(raw)
        assert payload == {"bookmark_id": "bid-X", "src_msg_id": 9, "silent": True}
        # probe-ключ убран после финального SET
        assert "task_list_pending_probe:42:bid-X" not in fake.store

    async def test_send_failure_returns_false_and_clears_probe(self):
        from app.worker import task_list_offer as mod
        fake = _FakeRedis()
        with patch.object(mod, "aioredis_from_url", return_value=fake), \
             patch.object(mod, "_send_message", AsyncMock(return_value=None)):
            ok = await mod._maybe_offer_task_list(
                bookmark=_bookmark_obj(), chat_id=42,
                message_id=9, silent=False,
            )
        assert ok is False
        assert not fake.store  # probe вычищен


# ───────────────────── bot tlc: confirm ─────────────────────


def _make_cb(data: str, msg_id: int = 555):
    from aiogram.types import Message
    cb = AsyncMock()
    cb.data = data
    cb.message = MagicMock(spec=Message)
    cb.message.chat = MagicMock(id=100)
    cb.message.message_id = msg_id
    cb.message.bot = AsyncMock()
    cb.message.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
    cb.message.bot.pin_chat_message = AsyncMock()
    cb.message.bot.delete_message = AsyncMock()
    cb.message.delete = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.from_user = MagicMock(id=999)
    cb.answer = AsyncMock()
    return cb


class TestConfirm:
    async def test_yes_creates_binds_pins(self):
        from bot.handlers.tasks import cb_tasklist_confirm
        cb = _make_cb("tlc:bid-1")
        store = AsyncMock()
        store.pop_task_list_pending = AsyncMock(return_value={
            "bookmark_id": "bid-1", "src_msg_id": 9, "silent": True,
        })
        store.bind_list_message = AsyncMock()
        api = AsyncMock()
        api.get_bookmark = AsyncMock(return_value={
            "title": "x",
            "structured_data": {"type": "task_list",
                                "tasks": [{"text": "a", "done": False}]},
        })
        api.update_bookmark = AsyncMock()

        await cb_tasklist_confirm(cb, api, store)

        cb.message.bot.send_message.assert_awaited()
        store.bind_list_message.assert_awaited_with(100, 999, "bid-1")
        cb.message.bot.pin_chat_message.assert_awaited()
        api.update_bookmark.assert_awaited_with("fake-token", "bid-1",
                                                {"is_favorite": True})
        cb.message.delete.assert_awaited()  # offer убран
        cb.message.bot.delete_message.assert_awaited_with(100, 9)  # silent дубль

    async def test_yes_stale_pending_alerts(self):
        from bot.handlers.tasks import cb_tasklist_confirm
        cb = _make_cb("tlc:bid-1")
        store = AsyncMock()
        store.pop_task_list_pending = AsyncMock(return_value=None)
        await cb_tasklist_confirm(cb, AsyncMock(), store)
        cb.answer.assert_awaited()
        assert cb.answer.await_args.kwargs.get("show_alert") is True


class TestDecline:
    async def test_no_makes_plain_bookmark_verbose(self):
        from bot.handlers.tasks import cb_tasklist_decline
        cb = _make_cb("tlx:bid-1")
        store = AsyncMock()
        store.pop_task_list_pending = AsyncMock(return_value={
            "bookmark_id": "bid-1", "src_msg_id": 9, "silent": False,
        })
        api = AsyncMock()
        api.update_bookmark = AsyncMock(return_value={"title": "T", "summary": ""})

        await cb_tasklist_decline(cb, api, store)

        api.update_bookmark.assert_awaited_with("fake-token", "bid-1",
                                                {"structured_data": None})
        cb.message.edit_text.assert_awaited()  # verbose карточка

    async def test_no_silent_reacts_on_source(self):
        from bot.handlers.tasks import cb_tasklist_decline
        cb = _make_cb("tlx:bid-1")
        cb.message.bot.set_message_reaction = AsyncMock()
        store = AsyncMock()
        store.pop_task_list_pending = AsyncMock(return_value={
            "bookmark_id": "bid-1", "src_msg_id": 9, "silent": True,
        })
        api = AsyncMock()
        api.update_bookmark = AsyncMock(return_value={"title": "T"})

        await cb_tasklist_decline(cb, api, store)

        cb.message.delete.assert_awaited()
        cb.message.bot.set_message_reaction.assert_awaited()
        assert cb.message.bot.set_message_reaction.await_args.args[:2] == (100, 9)


# ───────────────────── #10 _react_src ─────────────────────


class TestReactSrc:
    async def test_sets_reaction_when_src_present(self):
        from bot.handlers.tasks.dedup import _react_src
        bot = AsyncMock()
        await _react_src(bot, 100, 9, "\U0001f44d")
        bot.set_message_reaction.assert_awaited()
        assert bot.set_message_reaction.await_args.args[:2] == (100, 9)

    async def test_noop_without_src(self):
        from bot.handlers.tasks.dedup import _react_src
        bot = AsyncMock()
        await _react_src(bot, 100, None, "\U0001f44d")
        bot.set_message_reaction.assert_not_awaited()

    async def test_swallows_errors(self):
        from bot.handlers.tasks.dedup import _react_src
        bot = AsyncMock()
        bot.set_message_reaction = AsyncMock(side_effect=RuntimeError("boom"))
        # не должно бросать
        await _react_src(bot, 100, 9, "\U0001f44d")
