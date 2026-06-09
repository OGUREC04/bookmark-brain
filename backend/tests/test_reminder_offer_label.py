"""Bug 2026-06-09: текст «про что напоминание» в offer + html.escape (CRITICAL).

_send_message всегда parse_mode=HTML. Title генерит LLM из произвольного контента;
без escape символы <>& уронили бы ВСЁ offer-сообщение (Telegram 400 → intent потерян).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ── pure text-функции ──────────────────────────────────────

def test_offer_text_with_label_personalized():
    from app.worker.reminder_offer import _reminder_offer_text
    assert "про «<b>купить хлеб</b>»" in _reminder_offer_text("купить хлеб").lower()


def test_offer_text_without_label_generic():
    from app.worker.reminder_offer import _reminder_offer_text
    assert "про «" not in _reminder_offer_text("").lower()


def test_choice_text_with_label_prefix():
    from app.worker.reminder_decision import _choice_text
    # label приходит УЖЕ экранированным
    assert "Про «<b>A &amp; B</b>»" in _choice_text("A &amp; B")


def test_choice_text_no_label_generic():
    from app.worker.reminder_decision import _choice_text
    assert "Про «" not in _choice_text("")


def test_ask_hour_text_with_label_prefix():
    from app.worker.reminder_decision import _ask_hour_text
    assert "Про «<b>задача</b>»" in _ask_hour_text("задача")


# ── escape в _maybe_offer_reminder (CRITICAL) ──────────────

@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.set = AsyncMock(return_value=True)
    r.get = AsyncMock(return_value=None)
    r.delete = AsyncMock()
    r.aclose = AsyncMock()
    return r


async def test_maybe_offer_escapes_special_chars(mock_redis):
    """title с <>& → в offer escaped, сырых угловых скобок title нет."""
    from app.worker import _maybe_offer_reminder

    bm = MagicMock()
    bm.id = uuid4()
    bm.structured_data = {"reminder_intent": True}
    bm.title = "Купить A & B <x>"
    bm.raw_text = "fallback"
    bm.source_message_id = None

    send_mock = AsyncMock(return_value={"message_id": 555})
    with patch("app.worker.reminder_offer._send_message", send_mock), \
         patch("app.worker.reminder_offer.aioredis_from_url", return_value=mock_redis):
        await _maybe_offer_reminder(bookmark=bm, chat_id=999, silent=False)

    text = send_mock.call_args.args[1]
    assert "&amp;" in text          # & экранирован
    assert "&lt;x&gt;" in text      # <x> экранирован
    assert "<x>" not in text        # сырых угловых скобок title нет
    assert "Купить A" in text       # текст закладки показан


async def test_maybe_offer_generic_when_no_text(mock_redis):
    """Медиа без текста (title/raw_text пустые) → общий offer без «»."""
    from app.worker import _maybe_offer_reminder

    bm = MagicMock()
    bm.id = uuid4()
    bm.structured_data = {"reminder_intent": True}
    bm.title = None
    bm.raw_text = None
    bm.source_message_id = None

    send_mock = AsyncMock(return_value={"message_id": 555})
    with patch("app.worker.reminder_offer._send_message", send_mock), \
         patch("app.worker.reminder_offer.aioredis_from_url", return_value=mock_redis):
        await _maybe_offer_reminder(bookmark=bm, chat_id=999, silent=False)

    text = send_mock.call_args.args[1]
    assert "про «" not in text.lower()  # нет персонализации
