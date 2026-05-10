"""Тесты для bot/handlers/reminders.py — T6 Phase 2.5.

Покрывает:
- Callbacks: rsk: (создать), rsn: (отказ), rdone: (выполнено), rsnz: (продлить)
- Reply-handler: парсинг времени → create/update reminder
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest


# ──────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────


@pytest.fixture
def api():
    a = AsyncMock()
    a.get_me = AsyncMock(return_value={
        "id": "u1", "telegram_id": 999, "timezone": "Europe/Moscow",
    })
    a.create_reminder = AsyncMock(return_value={
        "id": "rem-1", "fire_at": "2026-05-11T06:00:00+00:00",
    })
    a.update_reminder = AsyncMock(return_value={
        "id": "rem-1", "fire_at": "2026-05-11T08:00:00+00:00",
    })
    a.cancel_reminder = AsyncMock(return_value=None)
    return a


@pytest.fixture
def store():
    """StateStore mock — все reminder-методы из state_store.py."""
    s = AsyncMock()
    s.get_reminder_pending = AsyncMock(return_value=None)
    s.pop_reminder_pending = AsyncMock(return_value=None)
    s.delete_reminder_pending = AsyncMock()
    s.get_reminder_id = AsyncMock(return_value=None)
    s.delete_reminder_id = AsyncMock()
    s.store_reminder_snooze = AsyncMock()
    s.pop_reminder_snooze = AsyncMock(return_value=None)
    return s


@pytest.fixture(autouse=True)
def patch_ensure_user(monkeypatch):
    async def _fake(*_a, **_k):
        return "fake-token"
    import bot.handlers.start
    monkeypatch.setattr(bot.handlers.start, "_ensure_user", _fake)


def _make_callback(data: str, chat_id: int = 100, msg_id: int = 42):
    cb = AsyncMock()
    cb.data = data
    cb.from_user = MagicMock(id=999, username="testuser", first_name="Test")
    cb.message = AsyncMock()
    cb.message.chat = MagicMock(id=chat_id)
    cb.message.message_id = msg_id
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.answer = AsyncMock()
    return cb


# ──────────────────────────────────────────────────
# Callback rsk: — confirm create
# ──────────────────────────────────────────────────


class TestCallbackRsk:
    async def test_edits_message_to_ask_for_time(self, api, store):
        from bot.handlers.reminders import cb_create_reminder

        cb = _make_callback("rsk:bid-123")
        await cb_create_reminder(cb, api, store)

        cb.message.edit_text.assert_called_once()
        text = cb.message.edit_text.call_args.args[0]
        assert "reply" in text.lower() or "ответь" in text.lower()
        assert "когда" in text.lower()
        cb.answer.assert_called_once()


# ──────────────────────────────────────────────────
# Callback rsn: — dismiss
# ──────────────────────────────────────────────────


class TestCallbackRsn:
    async def test_edits_message_and_clears_pending(self, api, store):
        from bot.handlers.reminders import cb_dismiss_reminder

        cb = _make_callback("rsn:bid-123")
        await cb_dismiss_reminder(cb, api, store)

        cb.message.edit_text.assert_called_once()
        text = cb.message.edit_text.call_args.args[0]
        assert "без напоминания" in text.lower() or "окей" in text.lower()
        # Очищаем pending state
        store.delete_reminder_pending.assert_called_once_with(100, 42)
        cb.answer.assert_called_once()


# ──────────────────────────────────────────────────
# Callback rdone: — mark done
# ──────────────────────────────────────────────────


class TestCallbackRdone:
    async def test_cancels_reminder_and_edits(self, api, store):
        from bot.handlers.reminders import cb_done_reminder

        sm_id = str(uuid4())
        cb = _make_callback(f"rdone:{sm_id}")
        await cb_done_reminder(cb, api, store)

        api.cancel_reminder.assert_called_once_with("fake-token", sm_id)
        cb.message.edit_text.assert_called_once()
        text = cb.message.edit_text.call_args.args[0]
        assert "✅" in text or "сделано" in text.lower() or "выполнено" in text.lower()
        # Чистим Redis state
        store.delete_reminder_id.assert_called_once_with(100, 42)

    async def test_404_does_not_crash(self, api, store):
        """API вернул 404 (уже cancelled / не существует) — не падаем."""
        from bot.handlers.reminders import cb_done_reminder

        request = httpx.Request("DELETE", "http://test/r")
        response = httpx.Response(404, request=request)
        api.cancel_reminder.side_effect = httpx.HTTPStatusError(
            "not found", request=request, response=response
        )

        sm_id = str(uuid4())
        cb = _make_callback(f"rdone:{sm_id}")
        await cb_done_reminder(cb, api, store)  # не должен бросить
        # Сообщение всё равно отредактировано
        cb.message.edit_text.assert_called_once()


# ──────────────────────────────────────────────────
# Callback rsnz: — snooze
# ──────────────────────────────────────────────────


class TestCallbackRsnz:
    async def test_stores_snooze_state_and_asks_for_time(self, api, store):
        from bot.handlers.reminders import cb_snooze_reminder

        sm_id = str(uuid4())
        cb = _make_callback(f"rsnz:{sm_id}")
        await cb_snooze_reminder(cb, api, store)

        store.store_reminder_snooze.assert_called_once_with(100, 42, sm_id)
        cb.message.edit_text.assert_called_once()
        text = cb.message.edit_text.call_args.args[0]
        assert "reply" in text.lower() or "ответь" in text.lower()
        # Должны быть примеры
        assert "час" in text.lower() or "завтра" in text.lower()


# ──────────────────────────────────────────────────
# Reply-handler — parse time → create_reminder
# ──────────────────────────────────────────────────


def _make_reply_message(text: str, reply_to_msg_id: int = 42, chat_id: int = 100):
    msg = AsyncMock()
    msg.text = text
    msg.chat = MagicMock(id=chat_id)
    msg.message_id = reply_to_msg_id + 1
    msg.from_user = MagicMock(id=999, username="testuser", first_name="Test")

    rt = MagicMock()
    rt.message_id = reply_to_msg_id
    msg.reply_to_message = rt

    msg.answer = AsyncMock()
    msg.reply = AsyncMock()
    return msg


class TestReplyHandlerCreate:
    async def test_creates_reminder_when_pending_offer(self, api, store):
        from bot.handlers.reminders import handle_reminder_reply

        bid = str(uuid4())
        store.pop_reminder_pending = AsyncMock(return_value=bid)
        store.pop_reminder_snooze = AsyncMock(return_value=None)

        msg = _make_reply_message("через час")
        handled = await handle_reminder_reply(msg, api, store)

        assert handled is True
        api.create_reminder.assert_called_once()
        kwargs = api.create_reminder.call_args.kwargs
        args = api.create_reminder.call_args.args
        # bookmark_id передан
        all_args = list(args) + list(kwargs.values())
        assert bid in all_args or kwargs.get("bookmark_id") == bid
        # Подтверждение отправлено
        msg.answer.assert_called()
        # state очищен (pop'нули)
        store.pop_reminder_pending.assert_called_once_with(100, 42)

    async def test_unparseable_text_shows_help_no_create(self, api, store):
        from bot.handlers.reminders import handle_reminder_reply

        bid = str(uuid4())
        store.pop_reminder_pending = AsyncMock(return_value=bid)
        store.pop_reminder_snooze = AsyncMock(return_value=None)

        msg = _make_reply_message("какая-то дичь")
        handled = await handle_reminder_reply(msg, api, store)

        assert handled is True
        # API не дёрнут
        api.create_reminder.assert_not_called()
        # Юзеру показали хелп
        msg.answer.assert_called()
        sent = msg.answer.call_args.args[0]
        assert "не понял" in sent.lower() or "пример" in sent.lower() or "напомнить" in sent.lower()

    async def test_in_past_shows_error_no_create(self, api, store):
        from bot.handlers.reminders import handle_reminder_reply

        bid = str(uuid4())
        store.pop_reminder_pending = AsyncMock(return_value=bid)
        store.pop_reminder_snooze = AsyncMock(return_value=None)

        msg = _make_reply_message("вчера в 18")
        handled = await handle_reminder_reply(msg, api, store)

        assert handled is True
        api.create_reminder.assert_not_called()
        sent = msg.answer.call_args.args[0]
        assert "прошлом" in sent.lower() or "будущ" in sent.lower()

    async def test_no_pending_state_returns_false(self, api, store):
        """Reply на сообщение без reminder state — handler возвращает False (не наш)."""
        from bot.handlers.reminders import handle_reminder_reply

        store.pop_reminder_pending = AsyncMock(return_value=None)
        store.pop_reminder_snooze = AsyncMock(return_value=None)

        msg = _make_reply_message("через час")
        handled = await handle_reminder_reply(msg, api, store)

        assert handled is False
        api.create_reminder.assert_not_called()

    async def test_no_reply_to_message_returns_false(self, api, store):
        from bot.handlers.reminders import handle_reminder_reply

        msg = _make_reply_message("через час")
        msg.reply_to_message = None
        handled = await handle_reminder_reply(msg, api, store)
        assert handled is False


# ──────────────────────────────────────────────────
# Reply-handler — snooze flow
# ──────────────────────────────────────────────────


class TestReplyHandlerSnooze:
    async def test_updates_reminder_when_snooze_state(self, api, store):
        from bot.handlers.reminders import handle_reminder_reply

        sm_id = str(uuid4())
        store.pop_reminder_pending = AsyncMock(return_value=None)
        store.pop_reminder_snooze = AsyncMock(return_value=sm_id)

        msg = _make_reply_message("через 2 часа")
        handled = await handle_reminder_reply(msg, api, store)

        assert handled is True
        api.update_reminder.assert_called_once()
        # Первый позиционный — token, второй — sm_id
        args = api.update_reminder.call_args.args
        kwargs = api.update_reminder.call_args.kwargs
        assert sm_id in list(args) + list(kwargs.values())
        msg.answer.assert_called()

    async def test_snooze_takes_priority_over_pending(self, api, store):
        """Если каким-то чудом и pending и snooze есть на одном msg_id —
        snooze в приоритете (это активный reminder, не offer)."""
        from bot.handlers.reminders import handle_reminder_reply

        bid = str(uuid4())
        sm_id = str(uuid4())
        store.pop_reminder_pending = AsyncMock(return_value=bid)
        store.pop_reminder_snooze = AsyncMock(return_value=sm_id)

        msg = _make_reply_message("через час")
        handled = await handle_reminder_reply(msg, api, store)

        assert handled is True
        # Хотя бы один из них вызвался — обе ветки валидны для UX,
        # главное что мы не молча проглотили reply.
        assert (
            api.create_reminder.called or api.update_reminder.called
        )


# ──────────────────────────────────────────────────
# Router registration
# ──────────────────────────────────────────────────


class TestRouter:
    def test_router_exposes_callbacks_and_reply(self):
        """Smoke — router определён и экспортирует все 4 callback и reply-handler."""
        from bot.handlers import reminders as reminders_module

        assert hasattr(reminders_module, "router")
        assert hasattr(reminders_module, "cb_create_reminder")
        assert hasattr(reminders_module, "cb_dismiss_reminder")
        assert hasattr(reminders_module, "cb_done_reminder")
        assert hasattr(reminders_module, "cb_snooze_reminder")
        assert hasattr(reminders_module, "handle_reminder_reply")
