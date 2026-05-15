"""Phase 2.6 T7/T8: тесты для extract_explicit_remind_body.

Покрывает строгие/негативные кейсы:
  - «сделай напоминание купить хлеб завтра» → "купить хлеб завтра"
  - «напомни завтра в 9» → "завтра в 9"
  - «напомни» (без body) → ""
  - «надо купить молоко» → None (strong-intent, не explicit)
  - «привет» → None
"""
from __future__ import annotations

import sys
from pathlib import Path

_BOT_DIR = Path(__file__).parent.parent
if str(_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOT_DIR))

import pytest


@pytest.fixture(autouse=True)
def _stub_bot_settings(monkeypatch):
    """bot.handlers.reminders импортирует config — нужны env vars."""
    import os
    for k, v in {
        "TELEGRAM_BOT_TOKEN": "x",
        "BACKEND_URL": "http://x",
        "BOT_SECRET": "x",
        "REDIS_URL": "redis://x",
    }.items():
        monkeypatch.setenv(k, v)


def test_match_sdelai_napomian():
    from bot.handlers.reminders import extract_explicit_remind_body
    assert extract_explicit_remind_body("сделай напоминание купить хлеб завтра") == "купить хлеб завтра"


def test_match_napomni_with_time():
    from bot.handlers.reminders import extract_explicit_remind_body
    assert extract_explicit_remind_body("напомни завтра в 9") == "завтра в 9"


def test_match_napomni_mne():
    from bot.handlers.reminders import extract_explicit_remind_body
    assert extract_explicit_remind_body("напомни мне в пятницу про отчёт") == "в пятницу про отчёт"


def test_match_postav_reminder():
    from bot.handlers.reminders import extract_explicit_remind_body
    assert extract_explicit_remind_body("поставь reminder на завтра") == "на завтра"


def test_match_sozdai_napominaniya():
    from bot.handlers.reminders import extract_explicit_remind_body
    assert extract_explicit_remind_body("создай напоминание про звонок завтра в 14") == "про звонок завтра в 14"


def test_match_napomni_no_body():
    """«напомни» без body → пустая строка (не None)."""
    from bot.handlers.reminders import extract_explicit_remind_body
    assert extract_explicit_remind_body("напомни") == ""


def test_match_case_insensitive():
    from bot.handlers.reminders import extract_explicit_remind_body
    assert extract_explicit_remind_body("СДЕЛАЙ НАПОМИНАНИЕ купить хлеб") == "купить хлеб"


def test_match_with_colon_separator():
    from bot.handlers.reminders import extract_explicit_remind_body
    assert extract_explicit_remind_body("напомни: завтра в 9") == "завтра в 9"


def test_no_match_strong_intent():
    """«надо купить молоко» — strong intent, не explicit-remind."""
    from bot.handlers.reminders import extract_explicit_remind_body
    assert extract_explicit_remind_body("надо купить молоко") is None


def test_no_match_generic_text():
    from bot.handlers.reminders import extract_explicit_remind_body
    assert extract_explicit_remind_body("привет, как дела") is None


def test_no_match_empty():
    from bot.handlers.reminders import extract_explicit_remind_body
    assert extract_explicit_remind_body("") is None
    assert extract_explicit_remind_body("   ") is None


def test_no_match_napomnit_as_substring():
    """«не напоминать» / «попроси напомнить» — НЕ начинаются с триггера → None."""
    from bot.handlers.reminders import extract_explicit_remind_body
    assert extract_explicit_remind_body("попроси напомнить мне") is None


def test_no_match_napomni_ka_particle():
    """«напомни-ка купить хлеб» — частица «-ка» должна НЕ матчиться,
    иначе body будет «ка купить хлеб» (мусор)."""
    from bot.handlers.reminders import extract_explicit_remind_body
    # Возможна интерпретация «напомни-ка» как разговорной формы, но безопаснее
    # вернуть None: пусть юзер уберёт дефис, чем мы съедим «ка» в body.
    assert extract_explicit_remind_body("напомни-ка купить хлеб завтра") is None


def test_no_match_napomnit_other_forms():
    """Другие формы глагола: «напомнить», «напоминаешь», «напоминалось» —
    не должны матчиться как explicit-trigger."""
    from bot.handlers.reminders import extract_explicit_remind_body
    assert extract_explicit_remind_body("напомнить завтра") is None
    assert extract_explicit_remind_body("напоминаешь о чём-то") is None
    assert extract_explicit_remind_body("напоминалось что-то") is None


def test_no_match_napomnite_plural():
    """«напомните всем» — плюральная форма повелительного наклонения, не матч."""
    from bot.handlers.reminders import extract_explicit_remind_body
    assert extract_explicit_remind_body("напомните всем про встречу") is None


def test_match_postav_napominanie_no_time():
    """«поставь напоминание» без времени — body = "" (пустая строка), caller спросит."""
    from bot.handlers.reminders import extract_explicit_remind_body
    assert extract_explicit_remind_body("поставь напоминание") == ""


def test_no_match_napominanie_noun():
    """«напоминание о покупке» — существительное без глагола-триггера → None.

    Существительное «напоминание/напоминанию/напоминаниях» начало строки матчится
    как `напомин\\w+` ТОЛЬКО внутри ветвей «сделай/поставь/создай napomin\\w+».
    Без префикса-глагола — не триггер.
    """
    from bot.handlers.reminders import extract_explicit_remind_body
    assert extract_explicit_remind_body("напоминание о покупке завтра") is None
    assert extract_explicit_remind_body("напоминания не нужны") is None
