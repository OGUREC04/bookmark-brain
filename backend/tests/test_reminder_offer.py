"""Тесты для _maybe_offer_reminder — кнопка «Создать напоминание?» после save.

T8 — Phase 2.5 Reminders MVP.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.set = AsyncMock(return_value=True)
    r.get = AsyncMock(return_value=None)  # T13 anti-double-offer flag check
    r.delete = AsyncMock()
    r.aclose = AsyncMock()
    return r


def _bookmark(*, has_intent: bool, structured_data: dict | None = None):
    bm = MagicMock()
    bm.id = uuid4()
    if structured_data is not None:
        bm.structured_data = structured_data
    elif has_intent:
        bm.structured_data = {"reminder_intent": True}
    else:
        bm.structured_data = {"reminder_intent": False}
    return bm


class TestMaybeOfferReminder:
    async def test_offers_when_intent_and_not_silent(self, mock_redis):
        """reminder_intent=True + silent=False → отправляем offer."""
        from app.worker import _maybe_offer_reminder

        bm = _bookmark(has_intent=True)
        send_mock = AsyncMock(return_value={"message_id": 555})

        with patch("app.worker._send_message", send_mock), \
             patch("app.worker.aioredis_from_url", return_value=mock_redis):
            await _maybe_offer_reminder(
                bookmark=bm, chat_id=999, silent=False,
            )

        send_mock.assert_called_once()
        # chat_id первый аргумент
        assert send_mock.call_args.args[0] == 999
        text = send_mock.call_args.args[1]
        # В теле — подсказка про reply с примерами
        assert "reply" in text.lower() or "ответь" in text.lower()
        assert "завтра" in text.lower()  # один из примеров
        # Кнопки: только одна — «🔔 Создать напоминание?»
        markup = send_mock.call_args.args[2]
        kb = markup["inline_keyboard"]
        flat = [b for row in kb for b in row]
        # Минимум одна кнопка с rsk: callback
        assert any(b["callback_data"].startswith("rsk:") for b in flat)
        # Redis state сохранён
        keys = [c.args[0] for c in mock_redis.set.call_args_list]
        assert any("reminder_pending:999:555" == k for k in keys)

    async def test_offered_in_silent_mode_too(self, mock_redis):
        """silent=True НЕ блокирует offer: silent_mode по дефолту True
        у всех юзеров, иначе reminders фича невидима."""
        from app.worker import _maybe_offer_reminder

        bm = _bookmark(has_intent=True)
        send_mock = AsyncMock(return_value={"message_id": 42})

        with patch("app.worker._send_message", send_mock), \
             patch("app.worker.aioredis_from_url", return_value=mock_redis):
            await _maybe_offer_reminder(
                bookmark=bm, chat_id=999, silent=True,
            )
        send_mock.assert_called_once()

    async def test_skipped_when_no_intent(self, mock_redis):
        """reminder_intent=False → не отправляем."""
        from app.worker import _maybe_offer_reminder

        bm = _bookmark(has_intent=False)
        send_mock = AsyncMock()

        with patch("app.worker._send_message", send_mock):
            await _maybe_offer_reminder(
                bookmark=bm, chat_id=999, silent=False,
            )
        send_mock.assert_not_called()

    async def test_skipped_when_structured_data_missing(self):
        """structured_data=None — не падаем, не отправляем."""
        from app.worker import _maybe_offer_reminder

        bm = MagicMock()
        bm.id = uuid4()
        bm.structured_data = None
        send_mock = AsyncMock()

        with patch("app.worker._send_message", send_mock):
            await _maybe_offer_reminder(
                bookmark=bm, chat_id=999, silent=False,
            )
        send_mock.assert_not_called()

    async def test_no_chat_id_skipped(self):
        """chat_id=None — нечего слать."""
        from app.worker import _maybe_offer_reminder

        bm = _bookmark(has_intent=True)
        send_mock = AsyncMock()

        with patch("app.worker._send_message", send_mock):
            await _maybe_offer_reminder(
                bookmark=bm, chat_id=None, silent=False,
            )
        send_mock.assert_not_called()

    async def test_send_failure_does_not_raise(self, mock_redis):
        """Telegram упал — exception проглочен, не ломает основной flow.
        F3: Redis probe ставится ДО send. После провала send — final-key
        НЕ ставится, probe чистится."""
        from app.worker import _maybe_offer_reminder

        bm = _bookmark(has_intent=True)
        send_mock = AsyncMock(return_value=None)  # send failed

        with patch("app.worker._send_message", send_mock), \
             patch("app.worker.aioredis_from_url", return_value=mock_redis):
            await _maybe_offer_reminder(
                bookmark=bm, chat_id=999, silent=False,
            )

        # Probe был поставлен (1 set), потом удалён (1 delete).
        # Финального reminder_pending:{chat_id}:{msg_id} нет.
        keys_set = [c.args[0] for c in mock_redis.set.call_args_list]
        assert all(k.startswith("reminder_pending_probe:") for k in keys_set), \
            f"После send=None должен быть только probe-set, был: {keys_set}"
        # Probe удалён
        if mock_redis.delete.call_args_list:
            del_keys = [c.args[0] for c in mock_redis.delete.call_args_list]
            assert any("reminder_pending_probe:" in k for k in del_keys)

    async def test_redis_probe_failure_skips_send(self, mock_redis):
        """F3: если Redis probe упал — НЕ отправляем сообщение в Telegram.
        Лучше не показать офер чем показать broken button."""
        from app.worker import _maybe_offer_reminder

        bm = _bookmark(has_intent=True)
        # Probe set падает
        mock_redis.set = AsyncMock(side_effect=Exception("Redis down"))
        send_mock = AsyncMock()

        with patch("app.worker._send_message", send_mock), \
             patch("app.worker.aioredis_from_url", return_value=mock_redis):
            await _maybe_offer_reminder(
                bookmark=bm, chat_id=999, silent=False,
            )
        send_mock.assert_not_called()
