"""Баг 2026-06-09: напоминание-из-закладки брало текст из reply (= время),
а не из закладки. Reply на «Когда напомнить?» — это ВРЕМЯ, не содержание.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_ROOT = Path(__file__).parent.parent
for _p in (_ROOT, _ROOT / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest


@pytest.fixture(autouse=True)
def patch_ensure_user(monkeypatch):
    async def _fake(*_a, **_k):
        return "tok"
    import bot.common.auth
    monkeypatch.setattr(bot.common.auth, "ensure_user", _fake)


def _msg(text: str):
    m = AsyncMock()
    m.text = text
    m.chat = MagicMock(id=1)
    m.answer = AsyncMock()
    return m


async def test_bookmark_reminder_text_prefers_title():
    from bot.handlers.reminders.reply import _bookmark_reminder_text
    api = AsyncMock()
    api.get_bookmark = AsyncMock(return_value={"title": "купить хлеб", "raw_text": "x"})
    assert await _bookmark_reminder_text(api, "tok", "bid-1") == "купить хлеб"


async def test_bookmark_reminder_text_falls_back_to_raw_text():
    from bot.handlers.reminders.reply import _bookmark_reminder_text
    api = AsyncMock()
    api.get_bookmark = AsyncMock(return_value={"title": None, "raw_text": "позвонить врачу"})
    assert await _bookmark_reminder_text(api, "tok", "bid-1") == "позвонить врачу"


async def test_bookmark_reminder_text_empty_on_failure():
    from bot.handlers.reminders.reply import _bookmark_reminder_text
    api = AsyncMock()
    api.get_bookmark = AsyncMock(side_effect=RuntimeError("backend down"))
    # Не падаем; пустой текст → дисплей покажет общий «🔔 Напоминание».
    assert await _bookmark_reminder_text(api, "tok", "bid-1") == ""


async def test_apply_create_uses_bookmark_text_not_time_reply():
    """kind=create (bookmark-напоминание): payload.text = текст ЗАКЛАДКИ,
    а НЕ reply «через час» (это время)."""
    from bot.handlers.reminders.reply import _apply_reminder_action
    api = AsyncMock()
    api.get_bookmark = AsyncMock(return_value={"title": "купить хлеб"})
    api.create_reminder = AsyncMock()
    store = AsyncMock()
    fire = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    await _apply_reminder_action(
        _msg("через час"), api, store,
        kind="create", target_id="bid-1", fire_at_iso=fire,
        user_tz_name="Europe/Moscow", confirm_msg_id=10,
    )

    api.create_reminder.assert_awaited_once()
    _, kwargs = api.create_reminder.call_args
    assert kwargs["payload"]["text"] == "купить хлеб"  # НЕ "через час"
    assert kwargs["bookmark_id"] == "bid-1"


async def test_apply_explicit_create_keeps_explicit_text():
    """kind=explicit_create: текст = заданный (target_id), не трогаем."""
    from bot.handlers.reminders.reply import _apply_reminder_action
    api = AsyncMock()
    api.create_reminder = AsyncMock()
    store = AsyncMock()
    fire = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    await _apply_reminder_action(
        _msg("да"), api, store,
        kind="explicit_create", target_id="помыть машину", fire_at_iso=fire,
        user_tz_name="Europe/Moscow", confirm_msg_id=10,
    )

    _, kwargs = api.create_reminder.call_args
    assert kwargs["payload"]["text"] == "помыть машину"
