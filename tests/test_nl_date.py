"""Tests for nl_date.parse() — NL date parser for reminder time inputs.

TDD: тесты сначала (RED), потом реализация (GREEN).

Покрытые кейсы:
- Относительные («завтра в 9», «через час»)
- Абсолютные («15 мая в 18:00»)
- Дни недели («в субботу в 18»)
- Прошлое («вчера», «вчера в 18») → IN_PAST
- День без времени («завтра», «в субботу») → NEEDS_HOUR
- Размытое («не знаю», «потом») → FALLBACK_DEFAULT
- Невнятный мусор → UNPARSEABLE
- Timezones — Europe/Moscow vs Europe/Kaliningrad
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time

from backend.app.services.nl_date import ParseStatus, parse

# Фиксированное «сейчас»: среда, 13 мая 2026, 12:00 MSK = 09:00 UTC
NOW_MSK = datetime(2026, 5, 13, 12, 0, tzinfo=ZoneInfo("Europe/Moscow"))
NOW_UTC = NOW_MSK.astimezone(timezone.utc)


def _expect_msk(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Helper: build expected datetime in MSK timezone (UTC-aware)."""
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("Europe/Moscow"))


# ──────────────────────────────────────────────────
# Группа 1: Относительные даты с временем — должны парситься
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
class TestRelativeWithTime:
    def test_zavtra_v_9(self) -> None:
        result = parse("завтра в 9", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.OK
        assert result.dt == _expect_msk(2026, 5, 14, 9, 0).astimezone(timezone.utc)

    def test_zavtra_v_18_00(self) -> None:
        result = parse("завтра в 18:00", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.OK
        assert result.dt == _expect_msk(2026, 5, 14, 18, 0).astimezone(timezone.utc)

    def test_poslezavtra_v_9(self) -> None:
        result = parse("послезавтра в 9", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.OK
        assert result.dt == _expect_msk(2026, 5, 15, 9, 0).astimezone(timezone.utc)

    def test_segodnya_v_22(self) -> None:
        result = parse("сегодня в 22", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.OK
        assert result.dt == _expect_msk(2026, 5, 13, 22, 0).astimezone(timezone.utc)


# ──────────────────────────────────────────────────
# Группа 2: «через X» — относительные интервалы
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
class TestRelativeInterval:
    def test_cherez_chas(self) -> None:
        result = parse("через час", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.OK
        # 13 мая 12:00 MSK + 1h = 13:00 MSK = 10:00 UTC
        assert result.dt == _expect_msk(2026, 5, 13, 13, 0).astimezone(timezone.utc)

    def test_cherez_2_chasa(self) -> None:
        result = parse("через 2 часа", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.OK
        assert result.dt == _expect_msk(2026, 5, 13, 14, 0).astimezone(timezone.utc)

    def test_cherez_30_minut(self) -> None:
        result = parse("через 30 минут", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.OK
        assert result.dt == _expect_msk(2026, 5, 13, 12, 30).astimezone(timezone.utc)

    def test_cherez_3_dnya(self) -> None:
        result = parse("через 3 дня", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.OK
        # «через 3 дня» без часа — но это интервал, не календарный, время сохраняется (12:00)
        assert result.dt == _expect_msk(2026, 5, 16, 12, 0).astimezone(timezone.utc)

    def test_cherez_nedelyu(self) -> None:
        result = parse("через неделю", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.OK


# HIGH-2 regression — интервал «через N дней» при now.hour=0 не должен возвращать NEEDS_HOUR.
def test_cherez_3_dnya_at_midnight() -> None:
    """Если сейчас полночь, «через 3 дня» без часа — это всё равно интервал, OK."""
    midnight_msk = datetime(2026, 5, 13, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    midnight_utc = midnight_msk.astimezone(timezone.utc)
    with freeze_time(midnight_utc):
        result = parse("через 3 дня", user_tz="Europe/Moscow", now=midnight_utc)
    assert result.status == ParseStatus.OK


# ──────────────────────────────────────────────────
# Группа 3: Дни недели
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
class TestWeekday:
    def test_v_subbotu_v_18(self) -> None:
        # 13 мая 2026 — среда. Ближайшая суббота = 16 мая
        result = parse("в субботу в 18", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.OK
        assert result.dt == _expect_msk(2026, 5, 16, 18, 0).astimezone(timezone.utc)

    def test_v_pyatnitsu_v_9(self) -> None:
        # Ближайшая пятница = 15 мая
        result = parse("в пятницу в 9", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.OK
        assert result.dt == _expect_msk(2026, 5, 15, 9, 0).astimezone(timezone.utc)

    def test_v_subbotu_no_time(self) -> None:
        result = parse("в субботу", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.NEEDS_HOUR
        assert result.dt is None

    def test_zavtra_no_time_needs_hour(self) -> None:
        """«завтра» без часа → NEEDS_HOUR, а НЕ «завтра в текущее время».
        dateparser наследовал час от RELATIVE_BASE для относительных слов —
        обнуляем время базы для голой даты."""
        result = parse("завтра", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.NEEDS_HOUR
        assert result.dt is None

    def test_poslezavtra_no_time_needs_hour(self) -> None:
        result = parse("послезавтра", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.NEEDS_HOUR
        assert result.dt is None


# ──────────────────────────────────────────────────
# Группа 4: Абсолютные даты
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
class TestAbsoluteDate:
    def test_15_maya_v_18_00(self) -> None:
        result = parse("15 мая в 18:00", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.OK
        # 15 мая 2026 — текущий год
        assert result.dt == _expect_msk(2026, 5, 15, 18, 0).astimezone(timezone.utc)

    def test_15_maya_no_time(self) -> None:
        result = parse("15 мая", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.NEEDS_HOUR
        assert result.dt is None


# ──────────────────────────────────────────────────
# Группа 5: Прошлое — не создавать reminder
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
class TestPast:
    def test_vchera(self) -> None:
        result = parse("вчера", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.IN_PAST
        assert result.dt is None

    def test_vchera_v_18(self) -> None:
        result = parse("вчера в 18", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.IN_PAST

    def test_segodnya_v_8_when_now_is_12(self) -> None:
        # Сейчас 12:00 MSK, юзер пишет «сегодня в 8» → прошлое
        result = parse("сегодня в 8", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.IN_PAST


# ──────────────────────────────────────────────────
# Группа 6: Размытое — fallback default через 24ч
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
class TestFallbackDefault:
    @pytest.mark.parametrize("text", ["не знаю", "потом", "как-нибудь", "ок", "позже"])
    def test_fallback_phrases(self, text: str) -> None:
        result = parse(text, user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.FALLBACK_DEFAULT
        assert result.dt == NOW_UTC + timedelta(hours=24)

    @pytest.mark.parametrize("text", ["потом!", "  ок ", "не знаю.", "позже?"])
    def test_fallback_with_punctuation(self, text: str) -> None:
        """С пунктуацией / пробелами — всё равно fallback."""
        result = parse(text, user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.FALLBACK_DEFAULT

    @pytest.mark.parametrize(
        "text",
        [
            "в 9 ок",                    # «ок» внутри валидного времени — НЕ fallback
            "приди не знаю когда",       # «не знаю» внутри длинной фразы — НЕ fallback
            "потом увидимся",            # «потом» как часть фразы — НЕ fallback
            "позже не приходи",          # «позже» внутри — НЕ fallback
        ],
    )
    def test_fallback_marker_inside_phrase_is_not_fallback(self, text: str) -> None:
        """HIGH-1 regression — «ок» / «потом» / «не знаю» как часть других фраз
        не должны попадать в FALLBACK_DEFAULT.
        """
        result = parse(text, user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status != ParseStatus.FALLBACK_DEFAULT


# ──────────────────────────────────────────────────
# Группа 7: Полный мусор → UNPARSEABLE
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
class TestUnparseable:
    @pytest.mark.parametrize("text", ["", "   ", "asdfgh", "🔥🔥🔥", "?!?!"])
    def test_garbage(self, text: str) -> None:
        result = parse(text, user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.UNPARSEABLE
        assert result.dt is None


# ──────────────────────────────────────────────────
# Группа 8: Часовой пояс не MSK
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
class TestTimezone:
    def test_kaliningrad_zavtra_v_9(self) -> None:
        # Калининград = UTC+2
        result = parse("завтра в 9", user_tz="Europe/Kaliningrad", now=NOW_UTC)
        assert result.status == ParseStatus.OK
        # 14 мая 2026 09:00 Калининград = 07:00 UTC
        expected_kld = datetime(2026, 5, 14, 9, 0, tzinfo=ZoneInfo("Europe/Kaliningrad"))
        assert result.dt == expected_kld.astimezone(timezone.utc)

    def test_returned_dt_is_utc_aware(self) -> None:
        result = parse("завтра в 9", user_tz="Europe/Moscow", now=NOW_UTC)
        assert result.status == ParseStatus.OK
        assert result.dt is not None
        assert result.dt.tzinfo is not None
        # Should be UTC
        assert result.dt.utcoffset().total_seconds() == 0  # type: ignore


# ──────────────────────────────────────────────────
# Группа 9: Невалидный timezone → ValueError
# ──────────────────────────────────────────────────


def test_invalid_timezone_raises() -> None:
    with pytest.raises((ValueError, KeyError)):
        parse("завтра в 9", user_tz="NotARealZone/Foo", now=NOW_UTC)


# ──────────────────────────────────────────────────
# Группа 10: Phase 2.6 — NEEDS_HOUR rename + backward-compat alias
# ──────────────────────────────────────────────────


def test_needs_hour_is_alias_for_needs_time() -> None:
    """NEEDS_TIME (старое имя) и NEEDS_HOUR (новое в Phase 2.6) — один и тот же член Enum."""
    assert ParseStatus.NEEDS_TIME is ParseStatus.NEEDS_HOUR
    assert ParseStatus.NEEDS_HOUR.value == "needs_hour"


@freeze_time(NOW_UTC)
def test_v_pyatnitsu_returns_needs_hour() -> None:
    """«в пятницу» без часа — возвращаем NEEDS_HOUR (хендлер просит Reply со временем).

    Примечание: «завтра» без часа dateparser возвращает с текущим часом (12:00) — это OK.
    А вот именованный день недели / абсолютная дата возвращаются с 00:00 → NEEDS_HOUR.
    """
    result = parse("в пятницу", user_tz="Europe/Moscow", now=NOW_UTC)
    assert result.status == ParseStatus.NEEDS_HOUR
    assert result.dt is None


@freeze_time(NOW_UTC)
def test_zavtra_utrom_returns_ok_default_9() -> None:
    """«завтра утром» → OK с дефолтным временем 9:00 (universal time rule)."""
    result = parse("завтра утром", user_tz="Europe/Moscow", now=NOW_UTC)
    assert result.status == ParseStatus.OK
    assert result.dt == _expect_msk(2026, 5, 14, 9, 0).astimezone(timezone.utc)
