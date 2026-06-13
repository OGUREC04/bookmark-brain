"""Тесты related — задача 5 (без БД).

Сервис connections.get_related / count_related (маппинг, скоуп, лимит/all) +
эндпоинт api.connections.get_related_bookmarks (IDOR 404, happy-path) прямым
вызовом функции (HTTP-харнесса в проекте нет).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.api import connections as capi
from app.services import connections

A = UUID("00000000-0000-0000-0000-000000000005")
B = UUID("00000000-0000-0000-0000-000000000001")
USER = UUID("11111111-1111-1111-1111-111111111111")


class _Result:
    def __init__(self, rows=None, one=None):
        self._rows = rows or []
        self._one = one

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one

    def scalar_one_or_none(self):
        return self._one


# ── service ───────────────────────────────────────────────────────────────

async def test_get_related_maps_rows_and_limits():
    row = SimpleNamespace(
        id=B, title="t", summary="s", item_type="content",
        created_at="2026-06-13", weight=0.9,
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_Result(rows=[row]))

    out = await connections.get_related(session, A, USER, limit=5)

    assert out == [{
        "id": str(B), "title": "t", "summary": "s",
        "item_type": "content", "weight": 0.9, "created_at": "2026-06-13",
    }]
    sql = str(session.execute.call_args.args[0])
    assert "LIMIT" in sql
    params = session.execute.call_args.args[1]
    assert params["bid"] == str(A)
    assert params["user_id"] == str(USER)
    assert params["limit"] == 5


async def test_get_related_all_drops_limit():
    session = MagicMock()
    session.execute = AsyncMock(return_value=_Result(rows=[]))
    await connections.get_related(session, A, USER, include_all=True)
    sql = str(session.execute.call_args.args[0])
    assert "LIMIT" not in sql
    assert "limit" not in session.execute.call_args.args[1]


async def test_count_related_returns_int():
    session = MagicMock()
    session.execute = AsyncMock(return_value=_Result(one=SimpleNamespace(n=7)))
    assert await connections.count_related(session, A, USER) == 7


async def test_count_related_zero_when_no_row():
    session = MagicMock()
    session.execute = AsyncMock(return_value=_Result(one=None))
    assert await connections.count_related(session, A, USER) == 0


# ── endpoint ──────────────────────────────────────────────────────────────

async def test_related_endpoint_404_for_foreign_bookmark():
    session = MagicMock()
    session.execute = AsyncMock(return_value=_Result(one=None))  # не найдена у юзера
    user = SimpleNamespace(id=USER)

    with pytest.raises(HTTPException) as ei:
        await capi.get_related_bookmarks(
            A, show_all=False, limit=5, current_user=user, session=session,
        )
    assert ei.value.status_code == 404


async def test_related_endpoint_happy_path(monkeypatch):
    session = MagicMock()
    # owner-проверка → находит id заметки.
    session.execute = AsyncMock(return_value=_Result(one=A))
    user = SimpleNamespace(id=USER)
    monkeypatch.setattr(
        connections, "get_related",
        AsyncMock(return_value=[{
            "id": str(B), "title": "t", "summary": None,
            "item_type": None, "weight": 0.8, "created_at": None,
        }]),
    )
    # total — истинный счётчик (не len топ-5): связей может быть больше показанных.
    monkeypatch.setattr(connections, "count_related", AsyncMock(return_value=12))

    resp = await capi.get_related_bookmarks(
        A, show_all=False, limit=5, current_user=user, session=session,
    )
    assert resp.total == 12
    assert len(resp.items) == 1
    assert str(resp.items[0].id) == str(B)
    assert resp.items[0].weight == 0.8
    connections.get_related.assert_awaited_once()
