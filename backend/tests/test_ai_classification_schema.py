"""Phase 2.6 T1: AIClassification расширена reminder-полями.

Контракт:
- reminder_items / single_statement / reminder_form_hint опциональны
- Старые ответы AI без этих полей продолжают валидироваться (backward-compat)
- При наличии полей — pydantic корректно распаршивает ReminderItem
"""
from __future__ import annotations

import pytest
from app.schemas import AIClassification, ReminderItem
from pydantic import ValidationError


def _minimal_payload(**overrides) -> dict:
    base = {
        "summary": "summary",
        "tags": ["t"],
        "category": "article",
        "language": "ru",
    }
    base.update(overrides)
    return base


def test_classification_backward_compat_without_reminder_fields() -> None:
    """Старые ответы (Phase ≤ 2.5) без reminder_items/single_statement парсятся OK."""
    obj = AIClassification(**_minimal_payload())
    assert obj.reminder_items == []
    assert obj.single_statement is True
    assert obj.reminder_form_hint is None


def test_classification_accepts_reminder_items() -> None:
    obj = AIClassification(
        **_minimal_payload(
            reminder_items=[
                {"text": "контрольная", "raw_date_phrase": "завтра"},
                {"text": "тесты Eltex", "raw_date_phrase": None},
            ],
            single_statement=False,
            reminder_form_hint="task_list_with_reminders",
        )
    )
    assert len(obj.reminder_items) == 2
    assert obj.reminder_items[0].text == "контрольная"
    assert obj.reminder_items[0].raw_date_phrase == "завтра"
    assert obj.reminder_items[1].raw_date_phrase is None
    assert obj.single_statement is False
    assert obj.reminder_form_hint == "task_list_with_reminders"


def test_reminder_item_requires_text() -> None:
    """text обязателен; raw_date_phrase опционален (default None)."""
    item = ReminderItem(text="купить молоко")
    assert item.text == "купить молоко"
    assert item.raw_date_phrase is None

    with pytest.raises(ValidationError):
        ReminderItem()  # type: ignore[call-arg]


def test_classification_single_reminder_form() -> None:
    obj = AIClassification(
        **_minimal_payload(
            reminder_items=[{"text": "купить молоко", "raw_date_phrase": "завтра в 9"}],
            single_statement=True,
            reminder_form_hint="single_reminder",
        )
    )
    assert obj.reminder_form_hint == "single_reminder"
    assert obj.reminder_items[0].raw_date_phrase == "завтра в 9"


def test_classification_none_form_for_article() -> None:
    """Статья — пустой reminder_items, hint='none'."""
    obj = AIClassification(
        **_minimal_payload(
            reminder_items=[],
            single_statement=True,
            reminder_form_hint="none",
        )
    )
    assert obj.reminder_items == []
    assert obj.reminder_form_hint == "none"
