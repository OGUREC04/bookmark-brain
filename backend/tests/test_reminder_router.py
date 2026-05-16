"""Phase 2.6 T3: Save-flow router unit-tests.

Тестируем чистую функцию `route()` на разных комбинациях:
  - 0 / 1 / 2+ дат
  - single_statement true / false
  - strong-intent в тексте
  - explicit «сделай напоминание»
  - дата без часа → NEEDS_HOUR

`nl_date.parse()` используется реально (не мок) — это интеграционный тест
двух модулей: router + nl_date. Так покрываем баги пересечения.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time

from app.schemas import AIClassification, ReminderItem
from app.services.reminder_router import (
    ReminderForm,
    RouterDecision,
    route,
)


# Фиксированное «сейчас»: 13 мая 2026, 12:00 MSK = 09:00 UTC
NOW_MSK = datetime(2026, 5, 13, 12, 0, tzinfo=ZoneInfo("Europe/Moscow"))
NOW_UTC = NOW_MSK.astimezone(timezone.utc)


def _cls(
    *,
    items: list[dict] | None = None,
    single: bool = True,
    hint: str | None = None,
) -> AIClassification:
    return AIClassification(
        summary="s",
        tags=["t"],
        category="article",
        language="ru",
        reminder_items=[ReminderItem(**i) for i in (items or [])],
        single_statement=single,
        reminder_form_hint=hint,
    )


# ──────────────────────────────────────────────────
# Rule 9: NONE (ничего не подходит)
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
def test_empty_classification_returns_none() -> None:
    d = route(text="Просто статья", classification=_cls(), now=NOW_UTC)
    assert d.form == ReminderForm.NONE
    assert d.items == []


# ──────────────────────────────────────────────────
# Rule 6: 1 date + single-item → SINGLE_REMINDER
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
def test_single_item_with_date_returns_single_reminder() -> None:
    d = route(
        text="Купить молоко завтра в 9",
        classification=_cls(
            items=[{"text": "купить молоко", "raw_date_phrase": "завтра в 9"}],
            single=True,
            hint="single_reminder",
        ),
        now=NOW_UTC,
    )
    assert d.form == ReminderForm.SINGLE_REMINDER
    assert len(d.dated_items) == 1
    assert d.dated_items[0].fire_at is not None
    assert d.dated_items[0].fire_at.tzinfo is not None


# ──────────────────────────────────────────────────
# Rule 4: 2+ dates → TASK_LIST_WITH_REMINDERS
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
def test_two_dated_items_returns_task_list_with_reminders() -> None:
    d = route(
        text="Завтра контрольная, в пятницу зачёт, ещё подготовить тесты Eltex",
        classification=_cls(
            items=[
                {"text": "контрольная", "raw_date_phrase": "завтра в 9"},
                {"text": "зачёт", "raw_date_phrase": "в пятницу в 18"},
                {"text": "подготовить тесты Eltex", "raw_date_phrase": None},
            ],
            single=False,
            hint="task_list_with_reminders",
        ),
        now=NOW_UTC,
    )
    assert d.form == ReminderForm.TASK_LIST_WITH_REMINDERS
    assert len(d.dated_items) == 2
    assert len(d.items) == 3


# ──────────────────────────────────────────────────
# Rule 5: 1 date + multi-item → NEEDS_BUTTON_CHOICE
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
def test_one_date_multi_item_returns_button_choice() -> None:
    d = route(
        text="Завтра контрольная, ещё тесты Eltex и подготовка к сессии",
        classification=_cls(
            items=[
                {"text": "контрольная", "raw_date_phrase": "завтра в 9"},
                {"text": "тесты Eltex", "raw_date_phrase": None},
                {"text": "подготовка к сессии", "raw_date_phrase": None},
            ],
            single=False,
            hint="task_list_with_reminders",
        ),
        now=NOW_UTC,
    )
    assert d.form == ReminderForm.NEEDS_BUTTON_CHOICE
    assert len(d.dated_items) == 1


# ──────────────────────────────────────────────────
# Rule 8: 0 dates + multi-item → TASK_LIST_NO_REMINDERS
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
def test_multi_item_no_dates_returns_task_list_no_reminders() -> None:
    d = route(
        text="Молоко, хлеб, сыр",
        classification=_cls(
            items=[
                {"text": "молоко", "raw_date_phrase": None},
                {"text": "хлеб", "raw_date_phrase": None},
                {"text": "сыр", "raw_date_phrase": None},
            ],
            single=False,
            hint="task_list_no_reminders",
        ),
        now=NOW_UTC,
    )
    assert d.form == ReminderForm.TASK_LIST_NO_REMINDERS
    assert d.dated_items == []


# ──────────────────────────────────────────────────
# Rule 7: 0 dates + needs_hour → NEEDS_HOUR
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
def test_single_item_date_without_hour_returns_needs_hour() -> None:
    d = route(
        text="Контрольная в пятницу",
        classification=_cls(
            items=[{"text": "контрольная", "raw_date_phrase": "в пятницу"}],
            single=True,
            hint="single_reminder",
        ),
        now=NOW_UTC,
    )
    # «в пятницу» возвращает NEEDS_HOUR (нет даты с часом, fire_at=None)
    assert d.form == ReminderForm.NEEDS_HOUR
    assert len(d.needs_hour_items) == 1
    assert d.dated_items == []


# ──────────────────────────────────────────────────
# Rules 1-3: Strong-intent + single-statement
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
def test_strong_intent_with_hour_returns_single_reminder() -> None:
    """«надо купить молоко завтра в 9» — есть час → молча создаём single_reminder."""
    d = route(
        text="надо купить молоко завтра в 9",
        classification=_cls(
            items=[{"text": "купить молоко", "raw_date_phrase": "завтра в 9"}],
            single=True,
        ),
        now=NOW_UTC,
    )
    assert d.strong_intent is True
    assert d.form == ReminderForm.SINGLE_REMINDER


@freeze_time(NOW_UTC)
def test_strong_intent_no_date_returns_3button() -> None:
    """«надо купить молоко» — без даты → 3-button Phase 2.5 flow."""
    d = route(
        text="надо купить молоко",
        classification=_cls(
            items=[{"text": "купить молоко", "raw_date_phrase": None}],
            single=True,
        ),
        now=NOW_UTC,
    )
    assert d.strong_intent is True
    assert d.form == ReminderForm.STRONG_INTENT_3BUTTON


@freeze_time(NOW_UTC)
def test_strong_intent_date_without_hour_returns_needs_hour() -> None:
    """«нужно сдать отчёт в пятницу» — дата без часа → spросим Reply."""
    d = route(
        text="нужно сдать отчёт в пятницу",
        classification=_cls(
            items=[{"text": "сдать отчёт", "raw_date_phrase": "в пятницу"}],
            single=True,
        ),
        now=NOW_UTC,
    )
    assert d.strong_intent is True
    assert d.form == ReminderForm.NEEDS_HOUR


@freeze_time(NOW_UTC)
def test_strong_intent_multi_statement_falls_through() -> None:
    """Strong-intent multi-statement не идёт в Phase 2.5 flow — попадает в общие правила.

    Текст: «надо: контрольная завтра, тесты Eltex, подготовка к сессии»
    → multi-item, 1 дата → NEEDS_BUTTON_CHOICE.
    """
    d = route(
        text="надо: контрольная завтра в 9, тесты Eltex, подготовка к сессии",
        classification=_cls(
            items=[
                {"text": "контрольная", "raw_date_phrase": "завтра в 9"},
                {"text": "тесты Eltex", "raw_date_phrase": None},
                {"text": "подготовка к сессии", "raw_date_phrase": None},
            ],
            single=False,
        ),
        now=NOW_UTC,
    )
    assert d.strong_intent is True
    assert d.form == ReminderForm.NEEDS_BUTTON_CHOICE


# ──────────────────────────────────────────────────
# Explicit trigger «сделай напоминание»
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
def test_explicit_trigger_flag_is_set() -> None:
    d = route(
        text="сделай напоминание купить хлеб завтра в 18",
        classification=_cls(
            items=[{"text": "купить хлеб", "raw_date_phrase": "завтра в 18"}],
            single=True,
        ),
        now=NOW_UTC,
    )
    assert d.explicit_trigger is True
    assert d.form == ReminderForm.SINGLE_REMINDER


# ──────────────────────────────────────────────────
# Serialization для bookmark.structured_data
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
def test_decision_to_dict_is_json_serializable() -> None:
    import json

    d = route(
        text="Завтра контрольная, в пятницу зачёт",
        classification=_cls(
            items=[
                {"text": "контрольная", "raw_date_phrase": "завтра в 9"},
                {"text": "зачёт", "raw_date_phrase": "в пятницу в 18"},
            ],
            single=False,
        ),
        now=NOW_UTC,
    )
    payload = d.to_dict()
    # Должен сериализоваться без ошибок
    raw = json.dumps(payload)
    restored = json.loads(raw)
    assert restored["form"] == "task_list_with_reminders"
    assert len(restored["items"]) == 2
    assert restored["items"][0]["fire_at_utc"] is not None
    assert restored["items"][0]["status"] == "ok"


@freeze_time(NOW_UTC)
def test_decision_to_dict_handles_none_dates() -> None:
    """Items без даты сериализуются с fire_at_utc=null и status=null."""
    d = route(
        text="Молоко, хлеб",
        classification=_cls(
            items=[
                {"text": "молоко", "raw_date_phrase": None},
                {"text": "хлеб", "raw_date_phrase": None},
            ],
            single=False,
        ),
        now=NOW_UTC,
    )
    payload = d.to_dict()
    for item in payload["items"]:
        assert item["fire_at_utc"] is None
        assert item["status"] is None


# ──────────────────────────────────────────────────
# Edge cases — in_past, unparseable
# ──────────────────────────────────────────────────


@freeze_time(NOW_UTC)
def test_in_past_date_does_not_count_as_dated() -> None:
    """«вчера» → IN_PAST → fire_at=None → не считается dated item.
    Single statement без других дат → NONE.
    """
    d = route(
        text="Сделать ревью вчера",
        classification=_cls(
            items=[{"text": "сделать ревью", "raw_date_phrase": "вчера"}],
            single=True,
        ),
        now=NOW_UTC,
    )
    assert d.dated_items == []
    # IN_PAST не считается NEEDS_HOUR — должен попасть в NONE
    assert d.form == ReminderForm.NONE


@freeze_time(NOW_UTC)
def test_unparseable_date_does_not_count() -> None:
    """raw_date_phrase невнятный мусор → UNPARSEABLE → fire_at=None.
    Single statement → NONE.
    """
    d = route(
        text="Купить wjksdf",
        classification=_cls(
            items=[{"text": "купить", "raw_date_phrase": "asdfgh"}],
            single=True,
        ),
        now=NOW_UTC,
    )
    assert d.dated_items == []
    assert d.form == ReminderForm.NONE
