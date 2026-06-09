"""Tests: #7a pending не сжигается при ошибке парса (ретрай работает),
#7b nl_date понимает словесные часы «час ночи / два часа дня / 5 вечера».
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest

from bot.services.nl_date import ParseStatus, parse

# now = 2026-05-17 09:00 UTC = 12:00 MSK
_NOW = datetime(2026, 5, 17, 9, 0, tzinfo=timezone.utc)


# ───────────────────── #7b clock words ─────────────────────


class TestClockWords:
    @pytest.mark.parametrize("text,expected_utc", [
        # 01:00 MSK прошёл (сейчас 12:00) → завтра 01:00 = 22:00 UTC
        ("в час ночи", datetime(2026, 5, 17, 22, 0, tzinfo=timezone.utc)),
        ("час ночи", datetime(2026, 5, 17, 22, 0, tzinfo=timezone.utc)),
        # 14:00 MSK сегодня (ещё впереди) = 11:00 UTC
        ("два часа дня", datetime(2026, 5, 17, 11, 0, tzinfo=timezone.utc)),
        # 17:00 MSK = 14:00 UTC
        ("5 вечера", datetime(2026, 5, 17, 14, 0, tzinfo=timezone.utc)),
        # 13:00 MSK = 10:00 UTC
        ("час дня", datetime(2026, 5, 17, 10, 0, tzinfo=timezone.utc)),
        # 18:00 MSK = 15:00 UTC
        ("в 6 вечера", datetime(2026, 5, 17, 15, 0, tzinfo=timezone.utc)),
        # 09:00 MSK прошёл → завтра = 06:00 UTC next day
        ("9 утра", datetime(2026, 5, 18, 6, 0, tzinfo=timezone.utc)),
    ])
    def test_clock_word_parsing(self, text, expected_utc):
        r = parse(text, user_tz="Europe/Moscow", now=_NOW)
        assert r.status == ParseStatus.OK
        assert r.dt == expected_utc

    def test_invalid_hour_not_mangled(self):
        # «25 ночи» — час вне диапазона, не подменяем → не падаем
        r = parse("25 ночи", user_tz="Europe/Moscow", now=_NOW)
        assert r.status in (
            ParseStatus.UNPARSEABLE, ParseStatus.NEEDS_HOUR, ParseStatus.OK,
        )


# ───────────────────── #7a pending retry ─────────────────────


class TestPendingRetry:
    async def test_unparseable_resaves_pending_under_error_msg(self, monkeypatch):
        """Время не распозналось → тот же pending кладётся под
        сообщение-ошибку (reply на него снова сработает)."""
        import bot.common.auth
        import bot.handlers.reminders.reply as rep

        async def _fake_ensure(*_a, **_k):
            return "tok"
        monkeypatch.setattr(bot.common.auth, "ensure_user", _fake_ensure)

        async def _fake_tz(*_a, **_k):
            return "Europe/Moscow"
        monkeypatch.setattr(rep, "get_user_tz_name", _fake_tz)

        rt = MagicMock()
        rt.message_id = 555
        rt.text = "🔔 Когда напомнить «купить»?"
        rt.caption = None
        msg = MagicMock()
        msg.reply_to_message = rt
        msg.chat = MagicMock(id=100)
        msg.text = "абракадабра"
        from_user = MagicMock(id=7)
        msg.from_user = from_user
        err_msg = MagicMock(message_id=888)
        msg.answer = AsyncMock(return_value=err_msg)

        store = AsyncMock()
        store.get_reminder_fallback = AsyncMock(return_value=None)
        store.pop_reminder_snooze = AsyncMock(return_value=None)
        store.pop_reminder_pending = AsyncMock(
            return_value={"kind": "explicit", "text": "купить"}
        )
        store.store_reminder_pending_explicit = AsyncMock()

        ok = await rep.handle_reminder_reply(msg, AsyncMock(), store)

        assert ok is True
        store.store_reminder_pending_explicit.assert_awaited_once_with(
            100, 888, "купить", carry_from=555,
        )

    async def test_resave_pending_bookmark_kind(self):
        """Bookmark-kind pending тоже перекладывается (restore_*)."""
        from bot.handlers.reminders.reply import _resave_pending
        store = AsyncMock()
        await _resave_pending(
            store, 100, 888, None, {"kind": "bookmark", "bookmark_id": "b1"},
        )
        store.restore_reminder_pending.assert_awaited_once_with(
            100, 888, {"kind": "bookmark", "bookmark_id": "b1"}, carry_from=None,
        )

    async def test_resave_noop_without_msg(self):
        from bot.handlers.reminders.reply import _resave_pending
        store = AsyncMock()
        await _resave_pending(store, 100, None, None, {"kind": "explicit", "text": "x"})
        store.store_reminder_pending_explicit.assert_not_awaited()


class TestDatePhraseCombine:
    """Phase 2.7: pending с date_phrase («напомни 25 мая» без часа) —
    reply «в 9» комбинируется в «25 мая в 9»."""

    def _make_msg(self, reply_text: str):
        rt = MagicMock()
        rt.message_id = 555
        rt.text = "🔔 Напомню «1 июня экзамен» 25 мая — во сколько?"
        rt.caption = None
        rt.from_user = MagicMock(is_bot=True)
        msg = MagicMock()
        msg.reply_to_message = rt
        msg.chat = MagicMock(id=100)
        msg.text = reply_text
        msg.from_user = MagicMock(id=7)
        msg.answer = AsyncMock(return_value=MagicMock(message_id=888))
        return msg

    def _patch_common(self, monkeypatch):
        import bot.common.auth
        import bot.handlers.reminders.reply as rep

        async def _fake_ensure(*_a, **_k):
            return "tok"
        monkeypatch.setattr(bot.common.auth, "ensure_user", _fake_ensure)

        async def _fake_tz(*_a, **_k):
            return "Europe/Moscow"
        monkeypatch.setattr(rep, "get_user_tz_name", _fake_tz)
        # Нет TG datetime-entity в reply
        monkeypatch.setattr(rep, "extract_first_datetime_entity", lambda *_a, **_k: None)
        return rep

    async def test_hour_reply_combines_with_date_phrase(self, monkeypatch):
        rep = self._patch_common(monkeypatch)
        msg = self._make_msg("в 9")
        store = AsyncMock()
        store.get_reminder_fallback = AsyncMock(return_value=None)
        store.pop_reminder_snooze = AsyncMock(return_value=None)
        store.pop_reminder_pending = AsyncMock(return_value={
            "kind": "explicit", "text": "1 июня экзамен", "date_phrase": "25 мая",
        })
        api = AsyncMock()
        api.create_reminder = AsyncMock()

        ok = await rep.handle_reminder_reply(msg, api, store)
        assert ok is True
        api.create_reminder.assert_awaited_once()
        # fire_at = 25 мая (комбинация даты и часа), текст из pending
        fire_at_iso = api.create_reminder.await_args.args[1]
        assert "-05-25" in fire_at_iso
        payload = api.create_reminder.await_args.kwargs["payload"]
        assert payload["text"] == "1 июня экзамен"

    async def test_day_reply_overrides_date_phrase(self, monkeypatch):
        """Юзер ответил «Завтра» (день, не час) — комбинация «25 мая Завтра»
        не парсится → honorим reply как новую дату, не падаем в ошибку."""
        rep = self._patch_common(monkeypatch)
        msg = self._make_msg("завтра в 10")
        store = AsyncMock()
        store.get_reminder_fallback = AsyncMock(return_value=None)
        store.pop_reminder_snooze = AsyncMock(return_value=None)
        store.pop_reminder_pending = AsyncMock(return_value={
            "kind": "explicit", "text": "1 июня экзамен", "date_phrase": "25 мая",
        })
        api = AsyncMock()
        api.create_reminder = AsyncMock()

        ok = await rep.handle_reminder_reply(msg, api, store)
        assert ok is True
        # Создалось напоминание (standalone «завтра в 10»), не ошибка
        api.create_reminder.assert_awaited_once()


class TestNeedTextReply:
    """E5: pending kind=need_text — reply это ТЕКСТ; реконструируем
    «<текст> <date_phrase>» и прогоняем через explicit-pipeline."""

    async def test_reply_reconstructs_args(self, monkeypatch):
        import bot.common.auth
        import bot.handlers.reminders.reply as rep

        async def _fake_ensure(*_a, **_k):
            return "tok"
        monkeypatch.setattr(bot.common.auth, "ensure_user", _fake_ensure)

        async def _fake_tz(*_a, **_k):
            return "Europe/Moscow"
        monkeypatch.setattr(rep, "get_user_tz_name", _fake_tz)

        rt = MagicMock()
        rt.message_id = 555
        rt.text = "📝 Про что напомнить 25 мая?"
        rt.caption = None
        rt.from_user = MagicMock(is_bot=True)
        msg = MagicMock()
        msg.reply_to_message = rt
        msg.chat = MagicMock(id=100)
        msg.text = "купить торт"
        msg.from_user = MagicMock(id=7)
        msg.answer = AsyncMock(return_value=MagicMock(message_id=888))

        store = AsyncMock()
        store.get_reminder_fallback = AsyncMock(return_value=None)
        store.pop_reminder_snooze = AsyncMock(return_value=None)
        store.pop_reminder_pending = AsyncMock(return_value={
            "kind": "need_text", "date_phrase": "25 мая",
        })

        called = {}
        async def _fake_process(message, args, api, store, cleanup_anchor=None):
            called["args"] = args
            called["cleanup_anchor"] = cleanup_anchor
        monkeypatch.setattr(
            "bot.handlers.reminders.explicit.process_explicit_remind_args",
            _fake_process,
        )

        ok = await rep.handle_reminder_reply(msg, AsyncMock(), store)
        assert ok is True
        # Реконструкция «<текст> <дата>»
        assert called["args"] == "купить торт 25 мая"


class TestDecodePendingNeedText:
    """Regression: _decode_pending должен распознавать kind=need_text
    (баг: декодился как мусорный bookmark → reply «про что» падал в
    «не понял время»)."""

    def test_need_text_envelope_round_trips(self):
        import json

        from bot.state_store import StateStore
        raw = json.dumps({"kind": "need_text", "date_phrase": "25 мая"})
        decoded = StateStore._decode_pending(raw)
        assert decoded == {"kind": "need_text", "date_phrase": "25 мая"}

    def test_explicit_with_date_phrase_round_trips(self):
        import json

        from bot.state_store import StateStore
        raw = json.dumps({"kind": "explicit", "text": "x", "date_phrase": "25 мая"})
        decoded = StateStore._decode_pending(raw)
        assert decoded["kind"] == "explicit"
        assert decoded["date_phrase"] == "25 мая"
