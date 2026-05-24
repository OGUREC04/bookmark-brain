"""Phase 2.7: reminder-intent сообщения пропускают general dedup.

Bug 2026-05-24: «купить хлеб завтра в 9» матчился как дубль старой заметки
«Записочка о покупке хлеба», реминдер не создавался, алерт без даты/времени.
Фикс: `_has_reminder_intent` исключает reminder-формы из dedup-гейта
(зеркалит исключение для task_list).
"""
from __future__ import annotations

import pytest
from app.worker.processing import _has_reminder_intent


def _sd(form: str | None):
    if form is None:
        return {}
    return {"reminder_decision": {"form": form, "items": []}}


class TestHasReminderIntent:
    @pytest.mark.parametrize("form", [
        "single_reminder",
        "composite_reminder",
        "needs_button_choice",
        "needs_hour",
        "strong_intent_3button",
    ])
    def test_reminder_forms_skip_dedup(self, form):
        assert _has_reminder_intent(_sd(form)) is True

    @pytest.mark.parametrize("form", [
        "none",
        "task_list_no_reminders",
    ])
    def test_non_reminder_forms_still_deduped(self, form):
        # NONE = обычная закладка (дедупим), task_list_* — отдельный путь
        assert _has_reminder_intent(_sd(form)) is False

    def test_no_decision_is_deduped(self):
        assert _has_reminder_intent({"type": "article"}) is False

    def test_no_structured_is_deduped(self):
        assert _has_reminder_intent(None) is False
        assert _has_reminder_intent("not a dict") is False

    def test_malformed_decision_is_safe(self):
        assert _has_reminder_intent({"reminder_decision": "oops"}) is False
        assert _has_reminder_intent({"reminder_decision": {}}) is False


class TestConfirmationWording:
    """E15: worker-подтверждение различает новый reminder vs дубль."""

    def test_new_reminder_wording(self):
        from app.worker.reminder_decision import _confirmation_text_single
        txt = _confirmation_text_single("купить хлеб", "25.05 10:00")
        assert txt.startswith("🔔 Напомню")
        assert "купить хлеб" in txt

    def test_duplicate_wording(self):
        from app.worker.reminder_decision import _confirmation_text_single
        txt = _confirmation_text_single("купить хлеб", "25.05 10:00", deduplicated=True)
        assert txt.startswith("👌 Уже напомню")
        assert "купить хлеб" in txt
