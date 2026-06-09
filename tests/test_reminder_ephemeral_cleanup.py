"""Единый механизм очистки эфемерных сообщений reminder-диалога.

Покрывает примитивы state_store (track/carry/pop) и helper _purge_reminder_dialog.
Чертёж: docs/research/_reminder-cleanup-blueprint.md.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

_ROOT = Path(__file__).parent.parent
for _p in (_ROOT, _ROOT / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest


class _FakeRedis:
    """Минимальный fake с list-операциями (rpush/lrange/expire/delete)."""

    def __init__(self):
        self.lists: dict[str, list[str]] = {}
        self.expires: dict[str, int] = {}

    async def rpush(self, key, *vals):
        self.lists.setdefault(key, []).extend(str(v) for v in vals)

    async def lrange(self, key, start, end):
        lst = self.lists.get(key, [])
        if end == -1:
            return list(lst[start:])
        return list(lst[start:end + 1])

    async def delete(self, *keys):
        for k in keys:
            self.lists.pop(k, None)
            self.expires.pop(k, None)

    async def expire(self, key, ttl):
        self.expires[key] = ttl


def _store_with(fake: _FakeRedis):
    from bot.state_store import StateStore
    s = StateStore("redis://localhost:6379/0")
    async def _get():
        return fake
    s._get = _get
    return s


# ── примитивы ──────────────────────────────────────────────

async def test_track_pushes_and_sets_ttl():
    fake = _FakeRedis()
    s = _store_with(fake)
    await s.track_reminder_ephemeral(1, 100, 101)
    await s.track_reminder_ephemeral(1, 100, 102)
    assert fake.lists["reminder_ephemeral:1:100"] == ["101", "102"]
    assert fake.expires["reminder_ephemeral:1:100"] == 3600  # pending TTL, не 5мин


async def test_pop_returns_ints_and_is_idempotent():
    fake = _FakeRedis()
    s = _store_with(fake)
    await s.track_reminder_ephemeral(1, 100, 101)
    await s.track_reminder_ephemeral(1, 100, 102)
    assert await s.pop_reminder_ephemeral(1, 100) == [101, 102]
    assert await s.pop_reminder_ephemeral(1, 100) == []  # 2й pop — пусто


async def test_carry_moves_tail_and_appends_old_anchor():
    fake = _FakeRedis()
    s = _store_with(fake)
    # под старым якорем 100 — reply юзера 101
    await s.track_reminder_ephemeral(1, 100, 101)
    # бот переспросил новым prompt 200 → переносим
    await s.carry_reminder_ephemeral(1, 100, 200)
    # под новым: старый хвост [101] + сам старый prompt [100]
    assert await s.pop_reminder_ephemeral(1, 200) == [101, 100]
    # старый ключ удалён
    assert "reminder_ephemeral:1:100" not in fake.lists


async def test_carry_same_anchor_just_seeds_prompt():
    """edit_text морфит prompt in-place (id не меняется) → carry=track старого id."""
    fake = _FakeRedis()
    s = _store_with(fake)
    await s.carry_reminder_ephemeral(1, 300, 300)
    assert await s.pop_reminder_ephemeral(1, 300) == [300]


async def test_carry_chain_accumulates_full_tail():
    """Многошаговый переспрос: весь хвост доезжает до финального якоря."""
    fake = _FakeRedis()
    s = _store_with(fake)
    await s.track_reminder_ephemeral(1, 100, 101)   # reply на prompt 100
    await s.carry_reminder_ephemeral(1, 100, 200)   # prompt 200
    await s.track_reminder_ephemeral(1, 200, 201)   # reply на prompt 200
    await s.carry_reminder_ephemeral(1, 200, 300)   # prompt 300
    # финальный pop = вся цепочка
    assert await s.pop_reminder_ephemeral(1, 300) == [101, 100, 201, 200]


async def test_store_method_carry_from_side_effect():
    """carry_from в store-методе переносит хвост (побочный эффект записи)."""
    fake = _FakeRedis()
    s = _store_with(fake)
    # добавим set/get для reminder_pending записи
    fake.kv = {}
    async def _set(k, v, ex=None): fake.kv[k] = v
    fake.set = _set
    await s.track_reminder_ephemeral(1, 100, 101)
    await s.store_reminder_pending_explicit(1, 200, "купить хлеб", carry_from=100)
    assert await s.pop_reminder_ephemeral(1, 200) == [101, 100]


# ── helper _purge_reminder_dialog ──────────────────────────

def _bot():
    b = AsyncMock()
    b.delete_message = AsyncMock()
    return b


async def test_purge_deletes_anchor_list_and_extra():
    """Удаляются prompt (anchor=100) + список [101,102] + reply (extra=103)."""
    from bot.handlers.reminders.shared import _purge_reminder_dialog
    store = AsyncMock()
    store.pop_reminder_ephemeral = AsyncMock(return_value=[101, 102])
    bot = _bot()
    await _purge_reminder_dialog(bot, 1, 100, store, extra_msg_ids=[103])
    deleted = [c.args[1] for c in bot.delete_message.call_args_list]
    assert deleted == [100, 101, 102, 103]  # anchor включён


async def test_purge_deletes_anchor_even_with_empty_list():
    """Happy-path: список пуст, но prompt (anchor) + reply всё равно удаляются."""
    from bot.handlers.reminders.shared import _purge_reminder_dialog
    store = AsyncMock()
    store.pop_reminder_ephemeral = AsyncMock(return_value=[])
    bot = _bot()
    await _purge_reminder_dialog(bot, 1, 200, store, extra_msg_ids=[201])
    deleted = [c.args[1] for c in bot.delete_message.call_args_list]
    assert deleted == [200, 201]  # prompt + reply


async def test_purge_keep_anchor_survives():
    """keep_msg_id=anchor (snapshot списка / strong-морф) → anchor НЕ удаляется."""
    from bot.handlers.reminders.shared import _purge_reminder_dialog
    store = AsyncMock()
    store.pop_reminder_ephemeral = AsyncMock(return_value=[301])
    bot = _bot()
    await _purge_reminder_dialog(
        bot, 1, 300, store, extra_msg_ids=[302], keep_msg_id=300,
    )
    deleted = [c.args[1] for c in bot.delete_message.call_args_list]
    assert deleted == [301, 302]  # anchor 300 сохранён


async def test_purge_excludes_keep_msg_id():
    from bot.handlers.reminders.shared import _purge_reminder_dialog
    store = AsyncMock()
    store.pop_reminder_ephemeral = AsyncMock(return_value=[500])
    bot = _bot()
    # 500 = сообщение, которое edit_text-ом стало подтверждением → не удалять
    await _purge_reminder_dialog(bot, 1, 500, store, keep_msg_id=500)
    bot.delete_message.assert_not_awaited()


async def test_purge_dedupes():
    from bot.handlers.reminders.shared import _purge_reminder_dialog
    store = AsyncMock()
    store.pop_reminder_ephemeral = AsyncMock(return_value=[101, 101])
    bot = _bot()
    await _purge_reminder_dialog(bot, 1, 100, store, extra_msg_ids=[101])
    deleted = [c.args[1] for c in bot.delete_message.call_args_list]
    assert deleted == [100, 101]  # anchor + дедуп reply (один раз)


async def test_purge_swallows_delete_errors():
    from bot.handlers.reminders.shared import _purge_reminder_dialog
    store = AsyncMock()
    store.pop_reminder_ephemeral = AsyncMock(return_value=[101, 102])
    bot = _bot()
    bot.delete_message = AsyncMock(side_effect=RuntimeError("message cannot be deleted"))
    # не должно бросить
    await _purge_reminder_dialog(bot, 1, 100, store)


async def test_purge_keep_equals_anchor_no_list_is_full_noop():
    """strong cancel: список пуст + keep_msg_id=anchor → ничего не удаляем."""
    from bot.handlers.reminders.shared import _purge_reminder_dialog
    store = AsyncMock()
    store.pop_reminder_ephemeral = AsyncMock(return_value=[])
    bot = _bot()
    await _purge_reminder_dialog(bot, 1, 100, store, keep_msg_id=100)
    bot.delete_message.assert_not_awaited()
