"""Unit-тест worker-materializer регулярных напоминаний.

Проверяет control-flow без реальной БД: CAS-win → INSERT+commit, CAS-lose →
skip, пусто → ранний выход. Также форму кнопок/текста регулярного срабатывания.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.worker import recurring as rec
from app.worker.scheduled import _format_recurring_text, _recurring_reminder_buttons


class _Result:
    def __init__(self, *, rows=None, scalar="__unset__"):
        self._rows = rows or []
        self._scalar = scalar

    def mappings(self):
        m = MagicMock()
        m.all.return_value = self._rows
        return m

    def scalar_one_or_none(self):
        return self._scalar


class _FakeSession:
    def __init__(self, results):
        self._results = list(results)
        self.executed = 0
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        self.executed += 1
        return self._results.pop(0)

    async def commit(self):
        self.commits += 1


def _row():
    return {
        "id": uuid4(),
        "user_id": uuid4(),
        "text": "полить цветы",
        "hour": 10,
        "minute": 0,
        "next_fire_at": datetime.now(timezone.utc) - timedelta(minutes=1),
        "timezone": "UTC",
    }


@pytest.fixture
def patch_session(monkeypatch):
    def _install(results):
        sess = _FakeSession(results)
        monkeypatch.setattr(rec, "async_session", lambda: sess)
        return sess
    return _install


# ── кнопки / текст ──


def test_recurring_buttons_shape():
    rid = "abc-123"
    kb = _recurring_reminder_buttons(rid)
    row = kb["inline_keyboard"][0]
    assert row[0]["callback_data"] == f"rrok:{rid}"
    assert row[1]["callback_data"] == f"rrstop:{rid}"
    assert "💤" not in row[0]["text"] and "💤" not in row[1]["text"]  # нет «продлить»


def test_recurring_text_uses_repeat_icon():
    assert _format_recurring_text({"text": "полить цветы"}) == "🔁 полить цветы"
    assert _format_recurring_text({}) == "🔁 Напоминание"


# ── materialize control-flow ──


async def test_empty_due_early_return(patch_session):
    sess = patch_session([_Result(rows=[])])
    await rec.materialize_recurring({})
    assert sess.commits == 0
    assert sess.executed == 1  # только SELECT


async def test_cas_win_inserts_and_commits(patch_session):
    sess = patch_session([
        _Result(rows=[_row()]),       # SELECT due
        _Result(scalar=uuid4()),      # CAS-advance выиграл
        _Result(),                    # INSERT
    ])
    await rec.materialize_recurring({})
    assert sess.executed == 3         # SELECT + CAS + INSERT
    assert sess.commits == 1


async def test_cas_lose_skips_insert(patch_session):
    sess = patch_session([
        _Result(rows=[_row()]),       # SELECT due
        _Result(scalar=None),         # CAS проиграл (другой ран продвинул)
    ])
    await rec.materialize_recurring({})
    assert sess.executed == 2         # SELECT + CAS, без INSERT
    assert sess.commits == 0


async def test_invalid_time_row_skipped(patch_session):
    # defense-in-depth: строка с некорректным часом пропускается, не роняя батч
    bad = _row()
    bad["hour"] = 99
    sess = patch_session([_Result(rows=[bad])])
    await rec.materialize_recurring({})
    assert sess.executed == 1          # только SELECT, ни CAS, ни INSERT
    assert sess.commits == 0
