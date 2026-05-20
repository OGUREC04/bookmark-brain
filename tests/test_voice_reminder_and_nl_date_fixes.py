"""Tests: kjo/skf (voice→reminder), rby (nl_date roll-forward).

53j покрыт изменением фильтра catch-all (аiogram-фильтр, проверяется
на dev-боте) — здесь юнитом тестируем детерминированный voice-reminder
роут и nl_date.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest

from bot.services.nl_date import ParseStatus, parse
from bot.services.voice_intent import VoiceIntent, detect_intent

# ───────────────────── skf/kjo: voice intent ─────────────────────


class TestVoiceReminderIntent:
    def test_napomni_is_reminder(self):
        r = detect_intent("напомни купить молоко", duration=3.0)
        assert r.intent == VoiceIntent.REMINDER
        assert r.cleaned_text == "купить молоко"

    def test_napomni_mne_strips_mne(self):
        r = detect_intent("напомни мне позвонить маме завтра", duration=3.0)
        assert r.intent == VoiceIntent.REMINDER
        assert r.cleaned_text == "позвонить маме завтра"

    def test_napomni_chto_is_search_not_reminder(self):
        # «напомни что я покупал» — поисковый вопрос, не reminder
        r = detect_intent("напомни что я покупал вчера", duration=3.0)
        assert r.intent != VoiceIntent.REMINDER

    def test_napomni_kakie_is_not_reminder(self):
        r = detect_intent("напомни какие закладки про python", duration=3.0)
        assert r.intent != VoiceIntent.REMINDER

    def test_explicit_list_still_todo(self):
        r = detect_intent("сделай список молоко хлеб сыр", duration=4.0)
        assert r.intent == VoiceIntent.TODO


class TestVoiceListDictation:
    """kjo-followup: голосовой список без буллетов (STT-поток).
    Compensация: ≥3 цифр-маркеров ИЛИ ≥2 «нужно/надо <глагол>» → TODO.
    Порог цифр поднят с 2 до 3 после code review H2 — иначе обычные
    реплики с парой числительных уезжали в TODO."""

    def test_numbered_dictation_is_list(self):
        r = detect_intent(
            "1 нужно сделать отчёт 2 нужно сделать презентацию "
            "3 нужно сделать звонок", duration=12.0,
        )
        assert r.intent == VoiceIntent.TODO

    def test_numbered_without_imperative_is_list(self):
        r = detect_intent(
            "1 купить молоко 2 купить хлеб 3 купить сыр", duration=8.0,
        )
        assert r.intent == VoiceIntent.TODO

    def test_repeat_imperative_no_numbers_is_list(self):
        r = detect_intent(
            "нужно сделать отчёт нужно позвонить маме надо забрать посылку",
            duration=8.0,
        )
        assert r.intent == VoiceIntent.TODO

    def test_single_imperative_not_list(self):
        r = detect_intent("нужно подумать об этом", duration=3.0)
        assert r.intent != VoiceIntent.TODO

    def test_napomni_wins_over_numbered(self):
        # REMINDER-проверка идёт ДО TODO — «напомни» приоритетнее.
        r = detect_intent(
            "напомни купить молоко 1 хлеб 2 сыр 3 масло", duration=5.0,
        )
        assert r.intent == VoiceIntent.REMINDER

    def test_two_numbers_in_speech_is_not_list(self):
        """H2 (code review): «у меня 2 идеи 3 варианта» НЕ должно
        уезжать в TODO — это обычная речь, не диктовка списка."""
        r = detect_intent("у меня 2 идеи 3 варианта по этому проекту",
                          duration=5.0)
        assert r.intent != VoiceIntent.TODO

    def test_two_numbered_items_not_enough(self):
        """Граничное: 2 нумерованных маркера без императива — порог
        ≥3 не достигнут. Пользователь использует /todo явно для
        коротких списков, либо «сделай список …»."""
        r = detect_intent("1 хлеб 2 молоко", duration=3.0)
        assert r.intent != VoiceIntent.TODO


class TestVoiceReminderHandler:
    async def test_calls_explicit_remind_pipeline(self):
        """kjo: voice «напомни …» идёт в тот же путь, что /remind —
        НЕ в task_list."""
        from bot.handlers.media import _handle_voice_reminder
        msg = MagicMock()
        msg.reply = AsyncMock()
        api = AsyncMock()
        store = AsyncMock()
        with patch(
            "bot.handlers.reminders.explicit.process_explicit_remind_args",
            new=AsyncMock(),
        ) as pera:
            await _handle_voice_reminder(
                msg, api, "tok", "напомни купить молоко завтра в 9",
                "купить молоко завтра в 9", store,
            )
        pera.assert_awaited_once()
        assert pera.await_args.args[1] == "купить молоко завтра в 9"


# ───────────────────── rby: nl_date roll-forward ─────────────────────

# MSK = UTC+3. now=17:00 UTC → 20:00 MSK (вечер уже прошёл 18:00).
_NOW_2000_MSK = datetime(2026, 5, 16, 17, 0, tzinfo=timezone.utc)
# now=12:00 UTC → 15:00 MSK (вечер 18:00 ещё впереди).
_NOW_1500_MSK = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)


class TestNlDateRollForward:
    def test_vecherom_past_rolls_to_tomorrow(self):
        r = parse("вечером", user_tz="Europe/Moscow", now=_NOW_2000_MSK)
        assert r.status == ParseStatus.OK
        # 18:00 MSK завтра = 15:00 UTC следующего дня
        assert r.dt == datetime(2026, 5, 17, 15, 0, tzinfo=timezone.utc)

    def test_vecherom_future_stays_today(self):
        r = parse("вечером", user_tz="Europe/Moscow", now=_NOW_1500_MSK)
        assert r.status == ParseStatus.OK
        assert r.dt == datetime(2026, 5, 16, 15, 0, tzinfo=timezone.utc)

    def test_bare_clock_past_rolls(self):
        # Голое «18:00» когда сейчас 20:00 MSK → завтра 18:00 (15:00 UTC)
        r = parse("18:00", user_tz="Europe/Moscow", now=_NOW_2000_MSK)
        assert r.status == ParseStatus.OK
        assert r.dt == datetime(2026, 5, 17, 15, 0, tzinfo=timezone.utc)

    def test_explicit_today_past_stays_in_past(self):
        # «сегодня в 8» когда сейчас 20:00 — юзер явно сказал сегодня,
        # НЕ перекатываем (так и задумано).
        r = parse("сегодня в 8", user_tz="Europe/Moscow", now=_NOW_2000_MSK)
        assert r.status == ParseStatus.IN_PAST

    def test_day_marker_guard(self):
        # helper: часть суток с явным днём НЕ считается «голой» —
        # перекат запрещён (день задан юзером).
        from bot.services.nl_date import _is_bare_time_of_day
        assert _is_bare_time_of_day("вечером") is True
        assert _is_bare_time_of_day("18:00") is True
        assert _is_bare_time_of_day("завтра вечером") is False
        assert _is_bare_time_of_day("15 мая вечером") is False
        assert _is_bare_time_of_day("в субботу вечером") is False
