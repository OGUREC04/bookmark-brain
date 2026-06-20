"""Тесты гейта временных маркеров — защита от LLM-галлюцинации дедлайнов.

Баг: /todo «купить молоко, позвонить маме, записаться к зубному» → GigaChat
вешал deadline=сегодня на ВСЕ пункты (дат в тексте нет). Гейт has_temporal_marker
не запускает extraction-пасс для пунктов без даты; strip_hallucinated_deadlines
чистит mixed-кейс.
"""
from app.services.task_list_detector import (
    has_temporal_marker,
    strip_hallucinated_deadlines,
)


# ── has_temporal_marker: НЕТ маркера (не должно триггерить extraction) ──


def test_no_marker_plain_items():
    assert has_temporal_marker("купить молоко") is False
    assert has_temporal_marker("позвонить маме") is False
    assert has_temporal_marker("записаться к зубному") is False  # «к» не дата


def test_no_marker_false_friends():
    # Слова, содержащие подстроки месяцев/дней, но не даты — word-boundary спасает
    assert has_temporal_marker("купить майку") is False        # «май» внутри слова
    assert has_temporal_marker("срочно перезвонить") is False  # «ср» внутри слова
    assert has_temporal_marker("купить 5 яблок") is False       # число без даты/времени


def test_empty_safe():
    assert has_temporal_marker("") is False
    assert has_temporal_marker(None) is False  # type: ignore[arg-type]


# ── has_temporal_marker: ЕСТЬ маркер ──


def test_relative_markers():
    assert has_temporal_marker("позвонить сегодня") is True
    assert has_temporal_marker("сделать завтра") is True
    assert has_temporal_marker("отчёт послезавтра") is True


def test_weekday_markers():
    assert has_temporal_marker("купить молоко до вторника") is True
    assert has_temporal_marker("сделать к пятнице") is True
    assert has_temporal_marker("встреча в ср") is True


def test_month_and_numeric_markers():
    assert has_temporal_marker("отчёт 15 мая") is True
    assert has_temporal_marker("оплатить 15.05") is True
    assert has_temporal_marker("созвон в 18:30") is True
    assert has_temporal_marker("позвонить в 9") is True


def test_phrase_markers():
    assert has_temporal_marker("закрыть на этой неделе") is True
    assert has_temporal_marker("напомнить через час") is True
    assert has_temporal_marker("сделать через 3 дня") is True
    assert has_temporal_marker("сделать до конца недели") is True
    assert has_temporal_marker("закрыть к концу этой недели") is True


# ── strip_hallucinated_deadlines ──


def _sd(items):
    return {"type": "task_list", "tasks": items}


def test_strip_all_dateless_items():
    """Все пункты без даты, но LLM повесил today → все обнуляются."""
    structured = _sd([
        {"text": "купить молоко", "done": False, "deadline": "2026-06-21"},
        {"text": "позвонить маме", "done": False, "deadline": "2026-06-21"},
    ])
    result = strip_hallucinated_deadlines(
        ["купить молоко", "позвонить маме"], structured,
    )
    assert all(t["deadline"] is None for t in result["tasks"])


def test_strip_keeps_real_deadline_in_mixed():
    """Пункт с реальной датой сохраняет дедлайн, фантомный — снимается."""
    structured = _sd([
        {"text": "купить молоко", "done": False, "deadline": "2026-06-21"},  # фантом
        {"text": "отчёт", "done": False, "deadline": "2026-05-15"},          # реальный (15 мая)
    ])
    result = strip_hallucinated_deadlines(
        ["купить молоко", "отчёт 15 мая"], structured,
    )
    assert result["tasks"][0]["deadline"] is None
    assert result["tasks"][1]["deadline"] == "2026-05-15"


def test_length_mismatch_untouched():
    structured = _sd([
        {"text": "a", "done": False, "deadline": "2026-06-21"},
    ])
    result = strip_hallucinated_deadlines(["a", "b"], structured)  # 1 vs 2
    assert result["tasks"][0]["deadline"] == "2026-06-21"  # не тронули


def test_immutable_does_not_mutate_input():
    original = _sd([{"text": "купить молоко", "done": False, "deadline": "2026-06-21"}])
    strip_hallucinated_deadlines(["купить молоко"], original)
    # исходный объект не изменён
    assert original["tasks"][0]["deadline"] == "2026-06-21"


def test_none_structured_safe():
    assert strip_hallucinated_deadlines(["a"], None) is None
