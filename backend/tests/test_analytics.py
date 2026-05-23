"""Unit tests для emit_event (Phase M1, ADR 0010) — без БД.

Фокус: failure-isolation (сбой метрики не бросает), сборка события,
обрезка name/source. Интеграция с реальной партиционированной таблицей
проверена вручную (миграция a8b9c0d1e2f3).
"""
from __future__ import annotations

import app.services.analytics as an
import pytest
from app.services.reminder_router import ReminderForm, is_terminal_form


class _FakeSession:
    def __init__(self, store: list):
        self._store = store

    def add(self, obj):
        self._store.append(obj)

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False


class TestEmitEvent:
    async def test_writes_event_with_dimensions(self, monkeypatch):
        added: list = []
        monkeypatch.setattr(an, "async_session", lambda: _FakeSession(added))
        await an.emit_event(
            name="reminder_router_decision", source="worker",
            agree=True, router_form="single_reminder",
        )
        assert len(added) == 1
        ev = added[0]
        assert ev.event_name == "reminder_router_decision"
        assert ev.source == "worker"
        assert ev.dimensions == {"agree": True, "router_form": "single_reminder"}

    async def test_failure_is_swallowed(self, monkeypatch):
        """Сбой записи метрики НЕ должен бросать — иначе сломает юзер-флоу."""
        def _boom():
            raise RuntimeError("db down")
        monkeypatch.setattr(an, "async_session", _boom)
        # не бросает
        await an.emit_event(name="x", source="worker", a=1)

    async def test_name_and_source_truncated(self, monkeypatch):
        added: list = []
        monkeypatch.setattr(an, "async_session", lambda: _FakeSession(added))
        await an.emit_event(name="n" * 100, source="s" * 50)
        assert len(added[0].event_name) == 64
        assert len(added[0].source) == 16

    async def test_empty_dimensions_ok(self, monkeypatch):
        added: list = []
        monkeypatch.setattr(an, "async_session", lambda: _FakeSession(added))
        await an.emit_event(name="x", source="bot")
        assert added[0].dimensions == {}


class TestIsTerminalForm:
    def test_terminal_forms(self):
        assert is_terminal_form(ReminderForm.SINGLE_REMINDER)
        assert is_terminal_form(ReminderForm.NONE)
        assert is_terminal_form(ReminderForm.TASK_LIST_WITH_REMINDERS)
        assert is_terminal_form(ReminderForm.COMPOSITE_REMINDER)

    def test_ask_states_not_terminal(self):
        assert not is_terminal_form(ReminderForm.NEEDS_HOUR)
        assert not is_terminal_form(ReminderForm.NEEDS_BUTTON_CHOICE)
        assert not is_terminal_form(ReminderForm.STRONG_INTENT_3BUTTON)
