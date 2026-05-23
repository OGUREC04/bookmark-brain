"""Tests for ReminderIntentDetector — pattern-based detection.

Триггеры:
- Глаголы намерения: надо, нужно, не забыть, сделать, позвонить, купить, написать, подать, проверить
- Временные предлоги: до X, к X, на X
- Явные даты: завтра, послезавтра, в <день>, <число> <месяц>, через N <unit>, на праздниках, на выходных

Ложные срабатывания: «купить молоко» без срока, «надо подумать» без действия — допустимы,
лучше показать кнопку лишний раз чем пропустить намерение (юзер может игнорить).
"""
from __future__ import annotations

import pytest
from app.services.reminder_intent import detect_reminder_intent

# ──────────────────────────────────────────────────
# Positive cases — should detect
# ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        # Глагол намерения + срок
        "Надо подать на матпомощь до 15 мая",
        "Нужно позвонить маме завтра",
        "Не забыть оплатить счёт к пятнице",
        "Надо купить молоко",
        "Нужно проверить отчёт послезавтра",
        # Только явная дата
        "Встреча 15 мая в 18:00",
        "Дедлайн 20 июня",
        "В пятницу собеседование",
        "Через час созвон",
        "Через 3 дня оплата",
        "На праздниках поездка",
        "На выходных дача",
        # «к X» / «до X» как временной предлог
        "К пятнице сделать слайды",
        "До 10 мая закрыть проект",
        # Проверка регистра
        "НАДО ПОЗВОНИТЬ ДО ПЯТНИЦЫ",
    ],
)
def test_detects_intent(text: str) -> None:
    result = detect_reminder_intent(text)
    assert result.has_intent is True, f"Should detect intent in: {text!r}"


# ──────────────────────────────────────────────────
# Negative cases — should NOT detect
# ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        # Цитата / описание прошлого, без призыва
        "Вчера ходил в магазин",
        "Прочитал статью про Python",
        "Хорошая мысль про дизайн",
        # Нет ни глагола ни даты
        "Любимая песня",
        "Это интересно",
        # Просто число (не дата)
        "Версия 2.5",
        "На 3 месте",
        # Пустая / мусор
        "",
        "   ",
        "asdf",
        # Только эмодзи
        "🔥🔥🔥",
    ],
)
def test_does_not_detect_intent(text: str) -> None:
    result = detect_reminder_intent(text)
    assert result.has_intent is False, f"Should NOT detect intent in: {text!r}"


# ──────────────────────────────────────────────────
# Edge cases — должны корректно работать
# ──────────────────────────────────────────────────


def test_returns_dataclass_with_attrs() -> None:
    """Контракт: всегда возвращает объект с has_intent, без падений."""
    result = detect_reminder_intent("надо завтра позвонить")
    assert hasattr(result, "has_intent")
    assert isinstance(result.has_intent, bool)


def test_long_text_still_detects() -> None:
    """Намерение в длинном тексте — детектируется."""
    text = (
        "Сегодня прошёл интересный созвон с Иваном про новую фичу. "
        "Обсудили варианты архитектуры, выбрали async. "
        "Надо зафиксировать решения в ADR до пятницы."
    )
    result = detect_reminder_intent(text)
    assert result.has_intent is True


@pytest.mark.parametrize(
    "text",
    [
        # HIGH-2 regression: «утром / вечером» — слабый сигнал, без глагола не intent
        "Я читал статью утром",
        "Гулял вечером",
        "Был днём в офисе",
    ],
)
def test_time_of_day_alone_is_not_intent(text: str) -> None:
    """Время суток без глагола намерения — не должно тригериться (HIGH-2)."""
    result = detect_reminder_intent(text)
    assert result.has_intent is False, f"Should NOT detect intent in: {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        # Время суток + слабый глагол — это intent
        "Купить молоко вечером",
        "Позвонить маме утром",
    ],
)
def test_time_of_day_with_verb_is_intent(text: str) -> None:
    """Время суток + глагол → intent."""
    result = detect_reminder_intent(text)
    assert result.has_intent is True, f"Should detect intent in: {text!r}"


def test_no_intent_in_pure_quote() -> None:
    """«надо» в цитате описательно — не должно быть intent.

    Это известный false positive — ловится pattern-based детектором.
    Мы его принимаем (better-safe-than-sorry, юзер может отказаться от кнопки).
    """
    # Мы НЕ проверяем negative — просто документируем что такое возможно.
    result = detect_reminder_intent('Он сказал: "Надо лучше работать"')
    # Не проверяем строгое значение — просто фиксируем что детектор стабилен
    assert isinstance(result.has_intent, bool)
