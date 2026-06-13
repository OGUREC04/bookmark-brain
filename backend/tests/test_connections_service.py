"""Юнит-тесты services/connections.py — задача 3 (без БД).

Логика find_similar_bookmarks / build_links_for_bookmark на мок-сессии:
построение параметров запроса, маппинг строк, КАНОНИЧЕСКОЕ направление ребра
(дедуп реверса), идемпотентность по rowcount, обработка None-эмбеддинга.
Реальный SQL против Postgres — интеграционно у пользователя.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.services import connections

A = UUID("00000000-0000-0000-0000-000000000005")
B = "00000000-0000-0000-0000-000000000001"  # < A
C = "00000000-0000-0000-0000-000000000009"  # > A
USER = UUID("11111111-1111-1111-1111-111111111111")


class _Result:
    def __init__(self, rows=None, rowcount=0):
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchall(self):
        return self._rows


def _row(id_, sim):
    return SimpleNamespace(id=id_, similarity=sim)


# ── find_similar_bookmarks ────────────────────────────────────────────────

async def test_find_similar_none_embedding_returns_empty():
    session = MagicMock()
    session.execute = AsyncMock()
    out = await connections.find_similar_bookmarks(session, A, USER, None)
    assert out == []
    session.execute.assert_not_awaited()


async def test_find_similar_maps_rows_and_builds_params():
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=_Result(rows=[_row(B, 0.91), _row(C, 0.80)])
    )
    out = await connections.find_similar_bookmarks(
        session, A, USER, [0.1, 0.2], k=5, threshold=0.7
    )
    assert out == [
        {"id": str(B), "similarity": 0.91},
        {"id": str(C), "similarity": 0.80},
    ]
    params = session.execute.call_args.args[1]
    assert params["user_id"] == str(USER)
    assert params["current_id"] == str(A)
    assert params["query_embedding"] == str([0.1, 0.2])  # каст vector
    assert params["threshold"] == 0.7
    assert params["k"] == 5


async def test_find_similar_defaults():
    session = MagicMock()
    session.execute = AsyncMock(return_value=_Result(rows=[]))
    await connections.find_similar_bookmarks(session, A, USER, [0.1])
    params = session.execute.call_args.args[1]
    assert params["threshold"] == connections.SIMILAR_THRESHOLD  # 0.75
    assert params["k"] == connections.DEFAULT_K_STORE  # 30


# ── _canonical_pair ───────────────────────────────────────────────────────

def test_canonical_pair_orders_regardless_of_input():
    assert connections._canonical_pair("b", "a") == ("a", "b")
    assert connections._canonical_pair("a", "b") == ("a", "b")


# ── build_links_for_bookmark ──────────────────────────────────────────────

async def test_build_links_none_embedding_zero():
    session = MagicMock()
    session.execute = AsyncMock()
    n = await connections.build_links_for_bookmark(session, A, USER, None)
    assert n == 0
    session.execute.assert_not_awaited()


async def test_build_links_empty_candidates_zero(monkeypatch):
    monkeypatch.setattr(
        connections, "find_similar_bookmarks", AsyncMock(return_value=[])
    )
    session = MagicMock()
    session.execute = AsyncMock()
    n = await connections.build_links_for_bookmark(session, A, USER, [0.1])
    assert n == 0
    session.execute.assert_not_awaited()


async def test_build_links_canonical_direction_and_count(monkeypatch):
    monkeypatch.setattr(
        connections,
        "find_similar_bookmarks",
        AsyncMock(return_value=[
            {"id": B, "similarity": 0.9},  # B < A → swap
            {"id": C, "similarity": 0.8},  # C > A → keep
        ]),
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_Result(rowcount=1))

    n = await connections.build_links_for_bookmark(session, A, USER, [0.1, 0.2])
    assert n == 2

    inserts = [c.args[1] for c in session.execute.call_args_list]
    # Ребро для B: A=...005, B=...001 → from=...001, to=...005
    assert inserts[0]["from_id"] == B and inserts[0]["to_id"] == str(A)
    assert inserts[0]["weight"] == 0.9
    assert inserts[0]["user_id"] == str(USER)
    # Ребро для C: from=...005, to=...009
    assert inserts[1]["from_id"] == str(A) and inserts[1]["to_id"] == C
    # Всегда from_id <= to_id (каноническое направление)
    for p in inserts:
        assert p["from_id"] <= p["to_id"]


async def test_build_links_conflict_not_counted(monkeypatch):
    monkeypatch.setattr(
        connections,
        "find_similar_bookmarks",
        AsyncMock(return_value=[{"id": C, "similarity": 0.8}]),
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_Result(rowcount=0))  # ON CONFLICT
    n = await connections.build_links_for_bookmark(session, A, USER, [0.1])
    assert n == 0


def test_connections_module_makes_no_llm_calls():
    """NFR-1: связи/граф — 0 вызовов LLM/эмбеддинга (чистый pgvector kNN).

    Тест-трипвайр: если кто-то добавит вызов эмбеддинга/классификатора в модуль
    связей — упадёт здесь.
    """
    import inspect

    from app.services import connections as c

    src = inspect.getsource(c)
    assert "get_embedding" not in src
    assert "create_embedding_service" not in src
    assert "classifier" not in src.lower()
