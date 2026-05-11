"""T18: тесты для security hardening из code-review + security-review.

Покрывает:
- C-sec: HTML-escape пользовательского текста (`_safe`)
- H1: UUID-валидация callback_data (`_is_valid_uuid`)
- H2: длина пользовательского текста перед записью в Redis (`_cap_text`)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest


class TestSafeHtmlEscape:
    def test_escapes_lt_gt(self):
        from bot.handlers.reminders import _safe
        assert _safe("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"

    def test_escapes_anchor_injection(self):
        from bot.handlers.reminders import _safe
        # tg-deeplink phishing
        out = _safe('<a href="tg://resolve?domain=evil">click</a>')
        assert "<a " not in out
        assert "&lt;a" in out

    def test_passes_plain_text(self):
        from bot.handlers.reminders import _safe
        assert _safe("купить хлеб") == "купить хлеб"

    def test_handles_none(self):
        from bot.handlers.reminders import _safe
        assert _safe(None) == ""
        assert _safe("") == ""

    def test_escapes_ampersand(self):
        from bot.handlers.reminders import _safe
        assert _safe("AT&T") == "AT&amp;T"


class TestCapText:
    def test_short_text_unchanged(self):
        from bot.handlers.reminders import _cap_text
        assert _cap_text("hello") == "hello"

    def test_long_text_truncated(self):
        from bot.handlers.reminders import _cap_text, MAX_REMINDER_TEXT_LEN
        long = "x" * (MAX_REMINDER_TEXT_LEN + 100)
        out = _cap_text(long)
        assert len(out) == MAX_REMINDER_TEXT_LEN
        assert out.endswith("...")

    def test_empty_and_none(self):
        from bot.handlers.reminders import _cap_text
        assert _cap_text("") == ""
        assert _cap_text(None) == ""

    def test_custom_limit(self):
        from bot.handlers.reminders import _cap_text
        out = _cap_text("abcdefghij", limit=5)
        assert len(out) == 5
        assert out.endswith("...")


class TestUuidValidation:
    def test_accepts_valid_uuid(self):
        from bot.handlers.reminders import _is_valid_uuid
        assert _is_valid_uuid(str(uuid4())) is True

    def test_rejects_garbage(self):
        from bot.handlers.reminders import _is_valid_uuid
        assert _is_valid_uuid("rid-123") is False
        assert _is_valid_uuid("../../../etc/passwd") is False
        assert _is_valid_uuid("' OR 1=1 --") is False

    def test_rejects_empty_and_none(self):
        from bot.handlers.reminders import _is_valid_uuid
        assert _is_valid_uuid(None) is False
        assert _is_valid_uuid("") is False


@pytest.fixture(autouse=True)
def patch_ensure_user(monkeypatch):
    async def _fake(*_a, **_k):
        return "fake-token"
    import bot.handlers.start
    monkeypatch.setattr(bot.handlers.start, "_ensure_user", _fake)


class TestCbDoneRejectsInvalidUuid:
    async def test_done_with_garbage_callback_data_skipped(self):
        """H1: cb_done_reminder с не-UUID callback_data не зовёт API."""
        from bot.handlers.reminders import cb_done_reminder

        cb = AsyncMock()
        cb.data = "rdone:../../../etc/passwd"
        cb.message = AsyncMock()
        cb.message.chat = MagicMock(id=100)
        cb.message.message_id = 42
        cb.answer = AsyncMock()

        api = AsyncMock()
        api.cancel_reminder = AsyncMock()
        store = AsyncMock()

        await cb_done_reminder(cb, api, store)

        # API НЕ вызван — UUID не валиден
        api.cancel_reminder.assert_not_called()
        cb.answer.assert_called_once()

    async def test_snooze_with_garbage_callback_data_skipped(self):
        """H1: cb_snooze_reminder с не-UUID callback_data не делает edit/store."""
        from bot.handlers.reminders import cb_snooze_reminder

        cb = AsyncMock()
        cb.data = "rsnz:not-a-uuid"
        cb.message = AsyncMock()
        cb.message.chat = MagicMock(id=100)
        cb.message.message_id = 42
        cb.message.edit_text = AsyncMock()
        cb.answer = AsyncMock()

        api = AsyncMock()
        store = AsyncMock()
        store.store_reminder_snooze = AsyncMock()

        await cb_snooze_reminder(cb, api, store)

        cb.message.edit_text.assert_not_called()
        store.store_reminder_snooze.assert_not_called()
