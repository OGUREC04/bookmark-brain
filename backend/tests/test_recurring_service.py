"""Тесты вычисления времени следующего срабатывания регулярного напоминания.

Покрывает корнер-кейсы #1 (прошло сегодня → завтра), #8/#12 (tz), #9
(строго будущее, без добивания) из PRD RECURRING-REMINDERS.
"""
from datetime import datetime, timezone

from app.services.recurring_service import next_fire_utc, normalize_series_text


def _utc(y, m, d, h, mi):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


# ── UTC-зона (без сдвига) ──


def test_later_today_same_day():
    after = _utc(2026, 6, 21, 8, 0)
    assert next_fire_utc(10, 0, "UTC", after) == _utc(2026, 6, 21, 10, 0)


def test_already_passed_today_goes_tomorrow():
    after = _utc(2026, 6, 21, 12, 0)
    assert next_fire_utc(10, 0, "UTC", after) == _utc(2026, 6, 22, 10, 0)


def test_exactly_now_goes_tomorrow():
    # candidate <= now → строго будущее → завтра
    after = _utc(2026, 6, 21, 10, 0)
    assert next_fire_utc(10, 0, "UTC", after) == _utc(2026, 6, 22, 10, 0)


def test_with_minutes():
    after = _utc(2026, 6, 21, 8, 0)
    assert next_fire_utc(9, 30, "UTC", after) == _utc(2026, 6, 21, 9, 30)


# ── зона юзера (Москва = UTC+3) ──


def test_moscow_today():
    # 05:00Z = 08:00 MSK; 10:00 MSK ещё впереди → сегодня 07:00Z
    after = _utc(2026, 6, 21, 5, 0)
    assert next_fire_utc(10, 0, "Europe/Moscow", after) == _utc(2026, 6, 21, 7, 0)


def test_moscow_passed_goes_tomorrow():
    # 09:00Z = 12:00 MSK; 10:00 MSK уже прошло → завтра 07:00Z
    after = _utc(2026, 6, 21, 9, 0)
    assert next_fire_utc(10, 0, "Europe/Moscow", after) == _utc(2026, 6, 22, 7, 0)


def test_invalid_tz_falls_back_to_moscow():
    after = _utc(2026, 6, 21, 5, 0)
    assert next_fire_utc(10, 0, "Nonsense/Zone", after) == _utc(2026, 6, 21, 7, 0)


def test_naive_after_treated_as_utc():
    after = datetime(2026, 6, 21, 8, 0)  # naive
    assert next_fire_utc(10, 0, "UTC", after) == _utc(2026, 6, 21, 10, 0)


# ── нормализация текста для дедупа ──


def test_normalize_series_text():
    assert normalize_series_text("  Полить   Цветы ") == "полить цветы"
    assert normalize_series_text("полить цветы") == normalize_series_text("Полить Цветы")
