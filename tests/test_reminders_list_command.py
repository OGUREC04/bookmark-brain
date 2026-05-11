"""Тесты для T12: /reminders команда + история + NL-reply mgmt."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import httpx
import pytest


@pytest.fixture(autouse=True)
def patch_ensure_user(monkeypatch):
    async def _fake(*_a, **_k):
        return "fake-token"
    import bot.handlers.start
    monkeypatch.setattr(bot.handlers.start, "_ensure_user", _fake)


@pytest.fixture
def api():
    a = AsyncMock()
    a.get_me = AsyncMock(return_value={
        "id": "u1", "telegram_id": 999, "timezone": "Europe/Moscow",
    })
    a.list_upcoming_reminders = AsyncMock(return_value={
        "items": [
            {"id": "rid-1", "fire_at": "2026-05-12T06:00:00+00:00",
             "payload": {"text": "купить хлеб"}, "status": "pending"},
            {"id": "rid-2", "fire_at": "2026-05-13T15:00:00+00:00",
             "payload": {"text": "позвонить маме"}, "status": "pending"},
            {"id": "rid-3", "fire_at": "2026-05-15T09:00:00+00:00",
             "payload": {"text": "оплатить счёт"}, "status": "pending"},
        ],
        "total": 3,
    })
    a.list_reminder_history = AsyncMock(return_value={
        "items": [
            {"id": "old-1", "fire_at": "2026-05-08T09:00:00+00:00",
             "payload": {"text": "вчерашняя задача"}, "status": "done"},
            {"id": "old-2", "fire_at": "2026-05-05T15:00:00+00:00",
             "payload": {"text": "отменённая"}, "status": "cancelled"},
        ],
        "total": 2,
    })
    a.cancel_reminder = AsyncMock()
    a.update_reminder = AsyncMock()
    return a


@pytest.fixture
def store():
    s = AsyncMock()
    s.store_reminders_list_snapshot = AsyncMock()
    s.get_reminders_list_snapshot = AsyncMock(return_value=None)
    return s


def _make_msg(text: str = "/reminders"):
    msg = AsyncMock()
    msg.text = text
    msg.chat = MagicMock(id=100)
    msg.message_id = 42
    msg.from_user = MagicMock(id=999, username="testuser", first_name="Test")
    sent = MagicMock()
    sent.message_id = 43
    msg.answer = AsyncMock(return_value=sent)
    return msg


def _make_reply(text: str, reply_to_msg_id: int = 43):
    msg = AsyncMock()
    msg.text = text
    msg.chat = MagicMock(id=100)
    msg.message_id = 50
    msg.from_user = MagicMock(id=999, username="testuser", first_name="Test")
    rt = MagicMock(message_id=reply_to_msg_id)
    msg.reply_to_message = rt
    msg.answer = AsyncMock()
    return msg


def _cmd(args: str | None = None):
    from aiogram.filters import CommandObject
    return CommandObject(prefix="/", command="reminders", args=args)


# ──────────────────────────────────────────────────
# /reminders list
# ──────────────────────────────────────────────────


class TestCmdReminders:
    async def test_shows_active_list_with_numbers(self, api, store):
        from bot.handlers.reminders import cmd_reminders
        msg = _make_msg()
        await cmd_reminders(msg, _cmd(None), api, store)

        api.list_upcoming_reminders.assert_called_once()
        sent = msg.answer.call_args.args[0]
        assert "Активные" in sent
        assert "1." in sent and "2." in sent and "3." in sent
        assert "купить хлеб" in sent
        assert "позвонить маме" in sent

    async def test_saves_snapshot_ids(self, api, store):
        from bot.handlers.reminders import cmd_reminders
        msg = _make_msg()
        await cmd_reminders(msg, _cmd(None), api, store)

        store.store_reminders_list_snapshot.assert_called_once()
        args = store.store_reminders_list_snapshot.call_args.args
        assert args[0] == 100  # chat_id
        assert args[1] == 43   # sent.message_id
        assert args[2] == ["rid-1", "rid-2", "rid-3"]

    async def test_empty_list_shows_hint(self, api, store):
        from bot.handlers.reminders import cmd_reminders
        api.list_upcoming_reminders = AsyncMock(return_value={"items": [], "total": 0})
        msg = _make_msg()
        await cmd_reminders(msg, _cmd(None), api, store)

        sent = msg.answer.call_args.args[0]
        assert "/remind" in sent.lower() or "нет" in sent.lower()
        # Snapshot не сохраняется когда пусто
        store.store_reminders_list_snapshot.assert_not_called()

    async def test_history_branch(self, api, store):
        from bot.handlers.reminders import cmd_reminders
        msg = _make_msg()
        await cmd_reminders(msg, _cmd("история"), api, store)

        api.list_reminder_history.assert_called_once()
        api.list_upcoming_reminders.assert_not_called()
        sent = msg.answer.call_args.args[0]
        assert "История" in sent or "истори" in sent.lower()
        assert "вчерашняя задача" in sent


# ──────────────────────────────────────────────────
# NL-reply: отмени N / перенеси N на ... / история
# ──────────────────────────────────────────────────


class TestRemindersListReply:
    async def test_otmeni_cancels_correct_id(self, api, store):
        from bot.handlers.reminders import handle_reminders_list_reply
        store.get_reminders_list_snapshot = AsyncMock(
            return_value=["rid-1", "rid-2", "rid-3"]
        )

        msg = _make_reply("отмени 2")
        handled = await handle_reminders_list_reply(msg, api, store)

        assert handled is True
        api.cancel_reminder.assert_called_once_with("fake-token", "rid-2")
        sent = msg.answer.call_args.args[0]
        assert "Отменен" in sent or "отмен" in sent.lower()

    async def test_otmeni_out_of_range(self, api, store):
        from bot.handlers.reminders import handle_reminders_list_reply
        store.get_reminders_list_snapshot = AsyncMock(return_value=["rid-1"])

        msg = _make_reply("отмени 5")
        handled = await handle_reminders_list_reply(msg, api, store)

        assert handled is True
        api.cancel_reminder.assert_not_called()
        sent = msg.answer.call_args.args[0]
        assert "5" in sent or "нет" in sent.lower()

    async def test_perenesi_updates_correct_id(self, api, store):
        from bot.handlers.reminders import handle_reminders_list_reply
        store.get_reminders_list_snapshot = AsyncMock(
            return_value=["rid-1", "rid-2", "rid-3"]
        )

        msg = _make_reply("перенеси 1 на завтра в 9")
        handled = await handle_reminders_list_reply(msg, api, store)

        assert handled is True
        api.update_reminder.assert_called_once()
        args = api.update_reminder.call_args.args
        assert "rid-1" in args  # id переноса = первый

    async def test_no_snapshot_returns_false(self, api, store):
        """Reply без зарегистрированного snapshot — не наш."""
        from bot.handlers.reminders import handle_reminders_list_reply
        store.get_reminders_list_snapshot = AsyncMock(return_value=None)

        msg = _make_reply("отмени 1")
        handled = await handle_reminders_list_reply(msg, api, store)

        assert handled is False  # пропускаем дальше

    async def test_snapshot_persists_across_reminders_changes(self, api, store):
        """T12 главный тест: snapshot фиксирует UUID при показе списка.
        Через 5 минут «отмени 1» отменяет тот же UUID, даже если первый
        пункт уже сработал и ушёл из активных."""
        from bot.handlers.reminders import handle_reminders_list_reply
        # Snapshot снят 5 минут назад, когда было 3 reminder'а
        store.get_reminders_list_snapshot = AsyncMock(
            return_value=["rid-A", "rid-B", "rid-C"]
        )
        # Сейчас api.list_upcoming вернёт уже только 2 (rid-A сработал)
        # Но мы НЕ запрашиваем list — берём из snapshot.

        msg = _make_reply("отмени 1")
        handled = await handle_reminders_list_reply(msg, api, store)

        assert handled is True
        # Отменили rid-A, не rid-B (хотя rid-B сейчас «первый» в текущем списке)
        api.cancel_reminder.assert_called_once_with("fake-token", "rid-A")

    async def test_unknown_reply_text_shows_hint(self, api, store):
        from bot.handlers.reminders import handle_reminders_list_reply
        store.get_reminders_list_snapshot = AsyncMock(
            return_value=["rid-1"]
        )

        msg = _make_reply("какая-то дичь")
        handled = await handle_reminders_list_reply(msg, api, store)

        assert handled is True
        api.cancel_reminder.assert_not_called()
        api.update_reminder.assert_not_called()
        sent = msg.answer.call_args.args[0]
        assert "отмени" in sent.lower() or "перенеси" in sent.lower() or "не понял" in sent.lower()
