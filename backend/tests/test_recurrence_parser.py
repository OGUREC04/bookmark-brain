"""Тесты парсера регулярных напоминаний (/repeat, MVP — только ежедневно).

Покрывает корнер-кейсы #2,3,4,6,7 из PRD RECURRING-REMINDERS + порядок слов,
последний time-токен и защиту от голого числа в тексте.
"""
from app.services.recurrence_parser import parse_recurrence

# ── базовый успех ──


def test_basic_daily_with_minutes():
    r = parse_recurrence("полить цветы каждый день в 10:00")
    assert r.ok
    assert r.text == "полить цветы"
    assert r.rule == "daily"
    assert (r.hour, r.minute) == (10, 0)


def test_ezhednevno_synonym():
    r = parse_recurrence("полить цветы ежедневно в 9:30")
    assert r.ok
    assert r.text == "полить цветы"
    assert (r.hour, r.minute) == (9, 30)


def test_hour_without_minutes():
    r = parse_recurrence("выпить таблетку каждый день в 8")
    assert r.ok
    assert (r.hour, r.minute) == (8, 0)
    assert r.text == "выпить таблетку"


def test_dot_separator():
    r = parse_recurrence("зарядка каждый день в 7.15")
    assert r.ok
    assert (r.hour, r.minute) == (7, 15)


# ── части суток (#6) ──


def test_meridiem_morning():
    r = parse_recurrence("таблетка каждый день в 8 утра")
    assert r.ok and (r.hour, r.minute) == (8, 0)


def test_meridiem_evening_adds_12():
    r = parse_recurrence("позвонить маме каждый день в 6 вечера")
    assert r.ok and (r.hour, r.minute) == (18, 0)


def test_meridiem_day_noon():
    r = parse_recurrence("обед каждый день в 12 дня")
    assert r.ok and (r.hour, r.minute) == (12, 0)


def test_meridiem_midnight():
    r = parse_recurrence("каждый день в 12 ночи спать")
    assert r.ok and (r.hour, r.minute) == (0, 0)
    assert r.text == "спать"


# ── порядок слов и выбор time-токена ──


def test_schedule_first_then_text():
    r = parse_recurrence("в 10:00 каждый день полить цветы")
    assert r.ok
    assert r.text == "полить цветы"
    assert (r.hour, r.minute) == (10, 0)


def test_last_time_token_wins():
    # «в 7» — часть текста, расписание «в 8» в хвосте.
    r = parse_recurrence("встать в 7 каждый день в 8")
    assert r.ok
    assert (r.hour, r.minute) == (8, 0)
    assert "встать" in r.text


def test_bare_number_in_text_not_taken_as_time():
    r = parse_recurrence("купить 2 билета каждый день в 9")
    assert r.ok
    assert (r.hour, r.minute) == (9, 0)
    assert "2 билета" in r.text


# ── ошибки ──


def test_no_schedule_phrase():
    r = parse_recurrence("полить цветы")
    assert not r.ok and r.error == "NO_SCHEDULE"


def test_no_time():
    r = parse_recurrence("полить цветы каждый день")
    assert not r.ok and r.error == "NO_TIME"


def test_empty():
    r = parse_recurrence("   ")
    assert not r.ok and r.error == "NO_TEXT"


def test_no_text_only_schedule():
    r = parse_recurrence("ежедневно в 9")
    assert not r.ok and r.error == "NO_TEXT"


def test_bad_hour():
    r = parse_recurrence("полить цветы каждый день в 25:00")
    assert not r.ok and r.error == "BAD_TIME"


def test_bad_minute():
    r = parse_recurrence("полить цветы каждый день в 10:70")
    assert not r.ok and r.error == "BAD_TIME"
