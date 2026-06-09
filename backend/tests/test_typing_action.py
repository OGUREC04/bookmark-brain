"""Индикатор «печатает…» сверху чата на время AI-обработки (5lt продолжение).

typing_action — пульс chat-action на весь период обработки текста/ссылок
(AI идёт в воркере после выхода из бот-хендлера, там был только 👀 без статуса).
"""
from __future__ import annotations

import asyncio


async def test_typing_action_pulses_then_stops(monkeypatch):
    from app.worker import telegram as tg
    calls = []

    async def _track(chat_id, action="typing"):
        calls.append((chat_id, action))
    monkeypatch.setattr(tg, "_send_chat_action", _track)

    async with tg.typing_action(123, interval=0.01):
        await asyncio.sleep(0.035)  # дать пульсу сработать несколько раз
    n = len(calls)
    assert n >= 1
    assert calls[0] == (123, "typing")  # первый — сразу

    await asyncio.sleep(0.03)
    assert len(calls) == n  # после выхода новых нет (пульс отменён)


async def test_typing_action_none_chat_is_noop(monkeypatch):
    from app.worker import telegram as tg
    calls = []

    async def _track(*a, **k):
        calls.append(a)
    monkeypatch.setattr(tg, "_send_chat_action", _track)

    async with tg.typing_action(None):
        await asyncio.sleep(0.02)
    assert calls == []


async def test_typing_action_best_effort_on_error(monkeypatch):
    from app.worker import telegram as tg

    async def _boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(tg, "_send_chat_action", _boom)

    # Ошибка пульса не должна ронять блок.
    async with tg.typing_action(123, interval=0.01):
        await asyncio.sleep(0.02)


async def test_wrapper_runs_impl_inside_typing(monkeypatch):
    """process_bookmark_task оборачивает _impl в typing_action и пробрасывает args."""
    from app.worker import processing as proc
    called = {}

    async def _fake_impl(ctx, bid, chat_id=None, message_id=None, silent=False):
        called.update(bid=bid, chat_id=chat_id, message_id=message_id, silent=silent)
    monkeypatch.setattr(proc, "_process_bookmark_task_impl", _fake_impl)

    await proc.process_bookmark_task({}, "bm-1", chat_id=5, message_id=6, silent=True)
    assert called == {"bid": "bm-1", "chat_id": 5, "message_id": 6, "silent": True}
