"""E15 UX: подтверждение reminder различает новый vs дубль (формулировка A).

Bug 2026-05-24 follow-up: на повтор бот писал «🔔 Напомню…», хотя нового
напоминания не создавалось (вернулось существующее) — вводило в заблуждение.
Теперь дубль → «👌 Уже напомню…».
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _msg():
    m = MagicMock()
    m.answer = AsyncMock()
    return m


_FIRE = datetime(2026, 5, 25, 7, 0, tzinfo=timezone.utc)  # 10:00 MSK


class TestConfirmationChip:
    async def test_new_reminder_says_napomnyu(self):
        from bot.handlers.reminders.shared import _send_reminder_confirmation_with_chip
        msg = _msg()
        await _send_reminder_confirmation_with_chip(
            msg, _FIRE, "купить хлеб", "Europe/Moscow",
        )
        text = msg.answer.call_args.args[0]
        assert "🔔 Напомню" in text
        assert "👌" not in text

    async def test_duplicate_says_uzhe_napomnyu(self):
        from bot.handlers.reminders.shared import _send_reminder_confirmation_with_chip
        msg = _msg()
        await _send_reminder_confirmation_with_chip(
            msg, _FIRE, "купить хлеб", "Europe/Moscow", deduplicated=True,
        )
        text = msg.answer.call_args.args[0]
        assert "👌 Уже напомню" in text
