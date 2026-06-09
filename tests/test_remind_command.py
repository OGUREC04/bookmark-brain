"""Тесты для T11: /remind explicit команда."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

# sys.path для импортов
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest


@pytest.fixture(autouse=True)
def patch_ensure_user(monkeypatch):
    async def _fake(*_a, **_k):
        return "fake-token"
    import bot.common.auth
    monkeypatch.setattr(bot.common.auth, "ensure_user", _fake)


@pytest.fixture
def api():
    a = AsyncMock()
    a.get_me = AsyncMock(return_value={
        "id": "u1", "telegram_id": 999, "timezone": "Europe/Moscow",
    })
    a.create_reminder = AsyncMock(return_value={"id": "rem-1"})
    return a


@pytest.fixture
def store():
    s = AsyncMock()
    s._get = AsyncMock()
    redis_mock = AsyncMock()
    redis_mock.set = AsyncMock()
    s._get.return_value = redis_mock
    s.store_reminder_fallback = AsyncMock()
    return s


def _make_msg(text: str = "/remind"):
    msg = AsyncMock()
    msg.text = text
    msg.chat = MagicMock(id=100)
    msg.message_id = 42
    msg.from_user = MagicMock(id=999, username="testuser", first_name="Test")
    prompt = MagicMock(message_id=43)
    msg.answer = AsyncMock(return_value=prompt)
    # bot.send_checklist для эксперимента с date_time chip
    msg.bot = AsyncMock()
    msg.bot.send_checklist = AsyncMock()
    return msg


def _make_command(args: str | None = None):
    cmd = MagicMock()
    cmd.args = args
    return cmd


# ──────────────────────────────────────────────────
# /remind разделение текста и времени
# ──────────────────────────────────────────────────


class TestSplitTextAndTime:
    def test_text_with_relative_time(self):
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("купить хлеб через час")
        assert text == "купить хлеб"
        assert time == "через час"

    def test_text_with_tomorrow_morning(self):
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("позвонить маме завтра утром")
        assert text == "позвонить маме"
        assert "завтра" in time and "утром" in time

    def test_text_with_specific_time(self):
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("купить хлеб завтра в 9")
        assert text == "купить хлеб"
        assert "завтра" in time

    def test_no_time_returns_full_text(self):
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("просто заметка без времени")
        assert text == "просто заметка без времени"
        assert time is None

    # ── Phase 2.7: ведущая дата (front-date idiom) ──

    def test_leading_date_comma_chto(self):
        """Скрин-баг: «25 мая, что 1 июня экзамен» → триггер 25 мая,
        текст про 1 июня, вторая дата НЕ становится триггером."""
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("25 мая, что 1 июня экзамен")
        assert time == "25 мая"
        assert text == "1 июня экзамен"

    def test_leading_date_chto_no_comma(self):
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("завтра что позвонить маме")
        assert time == "завтра"
        assert text == "позвонить маме"

    def test_leading_date_pro(self):
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("в субботу про встречу")
        assert time == "в субботу"
        assert text == "встречу"

    def test_comma_in_text_not_misfire(self):
        """Запятая в перечислении НЕ должна ловиться как граница даты —
        head «купить молоко» не парсится как дата → tail-search."""
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("купить молоко, хлеб завтра")
        assert time == "завтра"
        assert "молоко" in text and "хлеб" in text

    def test_pro_at_start_falls_to_tail(self):
        """«про встречу завтра» — про в начале, head пустой → tail-search."""
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("про встречу завтра")
        assert time == "завтра"
        assert "встречу" in text

    def test_trailing_date_still_works(self):
        """Regression: хвостовая дата без границы — tail-search как раньше."""
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("позвонить маме завтра утром")
        assert text == "позвонить маме"
        assert "завтра" in time

    # ── Phase 2.7 fix: ведущее время БЕЗ разделителя ──
    # Триггер: 2026-05-31 «сегодня вечером доделать ивенторус» — бот спрашивал
    # «когда?», т.к. ни idiom (нет границы), ни tail-search («ивенторус» — не
    # дата) не ловили ведущее «сегодня вечером». Leading-search закрывает дыру.

    def test_leading_today_evening_no_boundary(self):
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("сегодня вечером доделать ивенторус")
        assert time == "сегодня вечером"
        assert text == "доделать ивенторус"

    def test_leading_relative_no_boundary(self):
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("через час купить хлеб")
        assert time == "через час"
        assert text == "купить хлеб"

    def test_leading_tomorrow_with_time_greedy(self):
        """Жадность ведущего окна: «завтра в 9 утра позвонить маме» — берём
        всё время-выражение, а не только «завтра»."""
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("завтра в 9 утра позвонить маме")
        assert "завтра" in time and "9" in time
        assert text == "позвонить маме"

    def test_leading_long_relative_window_7(self):
        """Поднятый cap window=7: «через 2 часа и 30 минут позвонить маме»
        (6 токенов время + 2 действие) должно сматчиться, при window=5 — нет."""
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("через 2 часа и 30 минут позвонить маме")
        assert "через" in time and "30" in time
        assert text == "позвонить маме"

    # ── E5: дата без текста → ("", date) ──

    def test_date_only_returns_empty_text(self):
        """«25 мая» без текста → ('', '25 мая') — пустой текст сигналит
        date-only (caller спросит «про что?»). Не фрагментируем в ('25','мая')."""
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("25 мая")
        assert text == ""
        assert time == "25 мая"

    def test_bare_relative_date_only(self):
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("завтра")
        assert text == ""
        assert time == "завтра"

    def test_text_plus_trailing_date_not_date_only(self):
        """Реконструкция need_text: «купить торт 25 мая» — текст ЕСТЬ."""
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("купить торт 25 мая")
        assert text == "купить торт"
        assert time == "25 мая"

    def test_empty_input(self):
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("")
        assert text == ""
        assert time is None

    # ── Bug 2026-06-09: время в СЕРЕДИНЕ фразы ──
    # Триггер: «Нужно завтра в 9 пойти на футбол» — бот спрашивал «когда?»,
    # т.к. время не в начале (leading) и не в конце (tail), а в середине.
    # Прошлые фиксы добавляли частные случаи; middle-search закрывает класс.

    def test_middle_time_between_text(self):
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("Нужно завтра в 9 пойти на футбол")
        assert time is not None and "завтра" in time and "9" in time
        assert text == "Нужно пойти на футбол"

    def test_middle_date_needs_hour(self):
        """Дата без часа в середине: «надо в субботу позвонить врачу»."""
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("надо в субботу позвонить врачу")
        assert time is not None and "субботу" in time
        assert text == "надо позвонить врачу"

    def test_middle_does_not_override_tail(self):
        """Время в конце — tail-search раньше middle, dangling-токенов нет."""
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("позвонить врачу в субботу")
        assert time is not None and "субботу" in time
        assert text == "позвонить врачу"

    def test_middle_no_false_positive_on_plain_text(self):
        """Без времени — middle не выдумывает (весь ввод = текст)."""
        from bot.common import split_remind_text_and_time
        text, time = split_remind_text_and_time("обсудить новый проект с командой")
        assert time is None
        assert text == "обсудить новый проект с командой"


# ──────────────────────────────────────────────────
# /remind команда
# ──────────────────────────────────────────────────


class TestCmdRemindHelp:
    async def test_no_args_shows_help(self, api, store):
        from bot.handlers.reminders import cmd_remind
        msg = _make_msg("/remind")
        await cmd_remind(msg, _make_command(None), api, store)
        msg.answer.assert_called_once()
        sent = msg.answer.call_args.args[0]
        assert "/remind" in sent.lower() or "напоминания" in sent.lower()
        # API не дёрнут
        api.create_reminder.assert_not_called()


class TestCmdRemindWithTime:
    async def test_creates_reminder_with_parsed_time(self, api, store):
        from bot.handlers.reminders import cmd_remind
        msg = _make_msg("/remind купить хлеб через час")
        await cmd_remind(msg, _make_command("купить хлеб через час"), api, store)

        api.create_reminder.assert_called_once()
        kwargs = api.create_reminder.call_args.kwargs
        assert kwargs.get("bookmark_id") is None  # explicit /remind не имеет закладки
        assert kwargs.get("payload", {}).get("text") == "купить хлеб"
        assert kwargs.get("payload", {}).get("source") == "explicit_remind"

        # Подтверждение юзеру: через sendChecklist (эксперимент с date_time chip)
        # либо fallback в message.answer.
        sent_via_checklist = msg.bot.send_checklist.called if hasattr(msg.bot, "send_checklist") else False
        sent_via_answer = msg.answer.call_args is not None
        assert sent_via_checklist or sent_via_answer
        if sent_via_checklist:
            kwargs = msg.bot.send_checklist.call_args.kwargs
            checklist = kwargs.get("checklist")
            assert checklist is not None
            # Один task с купить хлеб + дата
            assert len(checklist.tasks) == 1
            assert "купить хлеб" in checklist.tasks[0].text
            # date_time entity прицеплен
            assert checklist.tasks[0].text_entities is not None
            assert any(
                getattr(e, "type", None) == "date_time"
                or getattr(getattr(e, "type", None), "value", None) == "date_time"
                for e in checklist.tasks[0].text_entities
            )
        else:
            sent_text = msg.answer.call_args.args[0]
            assert "напомн" in sent_text.lower()
            assert "купить хлеб" in sent_text

    async def test_past_time_rejected(self, api, store):
        from bot.handlers.reminders import cmd_remind
        msg = _make_msg("/remind купить хлеб вчера в 9")
        await cmd_remind(msg, _make_command("купить хлеб вчера в 9"), api, store)
        api.create_reminder.assert_not_called()
        sent = msg.answer.call_args.args[0]
        assert "прошлом" in sent.lower() or "будущем" in sent.lower()


class TestCmdRemindWithoutTime:
    async def test_no_time_asks_for_reply(self, api, store):
        from bot.handlers.reminders import cmd_remind
        msg = _make_msg("/remind купить хлеб")
        await cmd_remind(msg, _make_command("купить хлеб"), api, store)

        # API не вызван — ждём reply
        api.create_reminder.assert_not_called()
        # Юзеру предложено reply'нуть
        sent = msg.answer.call_args.args[0]
        assert "когда" in sent.lower()
        assert "reply" in sent.lower() or "ответь" in sent.lower()
        # 12y: explicit /remind без времени → store_reminder_pending_explicit
        store.store_reminder_pending_explicit.assert_called_once()
        args = store.store_reminder_pending_explicit.call_args.args
        # (chat_id, msg_id, text)
        assert "купить хлеб" in args[2]
