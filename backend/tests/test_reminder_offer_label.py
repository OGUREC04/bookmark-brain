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


# ── _choice_text with items (новое поведение) ──────────────

def test_choice_text_lists_item_texts():
    """Пункты items['text'] перечисляются в тексте выбора."""
    from app.worker.reminder_decision import _choice_text
    items = [{"text": "Купить хлеб", "fire_at_utc": "2026-06-20T10:00:00Z"},
             {"text": "Позвонить врачу", "fire_at_utc": None}]
    text = _choice_text("", items)
    assert "Купить хлеб" in text
    assert "Позвонить врачу" in text


def test_choice_text_html_escapes_items():
    """Символы <, >, & в тексте пункта экранируются для HTML parse_mode."""
    from app.worker.reminder_decision import _choice_text
    items = [{"text": "A <b>bold</b> & more", "fire_at_utc": None}]
    text = _choice_text("", items)
    assert "<b>bold</b>" not in text          # raw HTML не проскочило
    assert "&lt;b&gt;bold&lt;/b&gt;" in text  # экранировано
    assert "&amp;" in text                    # & экранирован


def test_choice_text_truncates_long_item():
    """Пункт длиннее 80 символов обрезается с «…»."""
    from app.worker.reminder_decision import _choice_text
    long_text = "А" * 100
    items = [{"text": long_text, "fire_at_utc": None}]
    text = _choice_text("", items)
    assert "А" * 100 not in text   # полный текст не вошёл
    assert "…" in text


def test_choice_text_caps_items_at_8():
    """Если пунктов больше 8 — показывает 8 + «…и ещё N»."""
    from app.worker.reminder_decision import _choice_text
    items = [{"text": f"Пункт {i}", "fire_at_utc": None} for i in range(12)]
    text = _choice_text("", items)
    assert "Пункт 0" in text
    assert "Пункт 7" in text
    assert "Пункт 8" not in text    # 9-й (индекс 8) за пределами
    assert "и ещё 4" in text


def test_choice_text_empty_items_fallback():
    """Пустой items → сообщение без списка, без ошибки (прежнее поведение)."""
    from app.worker.reminder_decision import _choice_text
    text = _choice_text("", [])
    assert "🤔" in text
    # Нет маркеров списка пунктов
    assert "• " not in text.split("Как лучше?")[0] or "📋" in text


def test_choice_text_none_items_fallback():
    """None items (не переданы) → fallback без ошибки."""
    from app.worker.reminder_decision import _choice_text
    text = _choice_text("")
    assert "🤔" in text


def test_choice_text_items_with_empty_text_skipped():
    """Пункты с пустым text не добавляют пустую строку в список."""
    from app.worker.reminder_decision import _choice_text
    items = [{"text": "", "fire_at_utc": None},
             {"text": "  ", "fire_at_utc": None},
             {"text": "Реальный пункт", "fire_at_utc": None}]
    text = _choice_text("", items)
    assert "Реальный пункт" in text
    # Пустых bullet-строк нет (проверяем что нет «• » за которым сразу новая строка)
    assert "• \n" not in text


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
