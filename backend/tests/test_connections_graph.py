"""Тесты графа — задача 7 (без БД).

ego_graph (BFS по глубине, дедуп, фильтр рёбер), get_full_graph (фильтр рёбер
по узлам в лимите), stale-логика эндпоинта /graph, IDOR в /graph/local.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from app.api import connections as capi
from app.services import connections
from fastapi import HTTPException

A = UUID("00000000-0000-0000-0000-00000000000a")
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


def _edge(f, t, w):
    return SimpleNamespace(from_id=f, to_id=t, weight=w)


# ── ego_graph ─────────────────────────────────────────────────────────────

async def test_ego_graph_depth1(monkeypatch):
    a = str(A)
    edges_hop1 = [_edge(a, "B", 0.9), _edge("C", a, 0.8)]
    monkeypatch.setattr(
        connections, "_neighbor_edges", AsyncMock(return_value=edges_hop1)
    )

    async def _cards(session, user_id, ids):
        return [{"id": i, "title": None, "item_type": None} for i in ids]
    monkeypatch.setattr(connections, "_node_cards", _cards)

    g = await connections.ego_graph(MagicMock(), USER, A, depth=1)

    node_ids = {n["id"] for n in g["nodes"]}
    assert node_ids == {a, "B", "C"}  # центр + соседи
    assert len(g["edges"]) == 2
    assert g["center"] == a


async def test_ego_graph_depth2_expands_frontier(monkeypatch):
    a = str(A)
    hops = [[_edge(a, "B", 0.9)], [_edge("B", "D", 0.7)]]
    seen_frontiers = []

    async def _neighbors(session, user_id, ids):
        seen_frontiers.append(set(ids))
        return hops.pop(0)
    monkeypatch.setattr(connections, "_neighbor_edges", _neighbors)

    async def _cards(session, user_id, ids):
        return [{"id": i} for i in ids]
    monkeypatch.setattr(connections, "_node_cards", _cards)

    g = await connections.ego_graph(MagicMock(), USER, A, depth=2)

    assert {n["id"] for n in g["nodes"]} == {a, "B", "D"}
    assert len(g["edges"]) == 2
    # 2-й хоп идёт по новому фронтиру {B}, не по центру.
    assert seen_frontiers[0] == {a}
    assert seen_frontiers[1] == {"B"}


async def test_ego_graph_no_neighbors(monkeypatch):
    monkeypatch.setattr(connections, "_neighbor_edges", AsyncMock(return_value=[]))

    async def _cards(session, user_id, ids):
        return [{"id": i} for i in ids]
    monkeypatch.setattr(connections, "_node_cards", _cards)

    g = await connections.ego_graph(MagicMock(), USER, A, depth=2)
    assert {n["id"] for n in g["nodes"]} == {str(A)}  # только центр
    assert g["edges"] == []


# ── get_full_graph ────────────────────────────────────────────────────────

async def test_full_graph_filters_edges_outside_cap():
    node_rows = [
        SimpleNamespace(id="N1", title="a", item_type=None),
        SimpleNamespace(id="N2", title="b", item_type=None),
    ]
    # Ребро N1-N2 валидно; N1-N9 ссылается на узел вне выборки → отбрасываем.
    edge_rows = [_edge("N1", "N2", 0.9), _edge("N1", "N9", 0.8)]
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[_Result(rows=node_rows), _Result(rows=edge_rows)])

    g = await connections.get_full_graph(session, USER)

    assert {n["id"] for n in g["nodes"]} == {"N1", "N2"}
    assert g["edges"] == [{"from": "N1", "to": "N2", "weight": 0.9}]


# ── эндпоинты ─────────────────────────────────────────────────────────────

async def test_graph_local_404_for_foreign_center():
    session = MagicMock()
    session.execute = AsyncMock(return_value=_Result(one=None))
    user = SimpleNamespace(id=USER)
    with pytest.raises(HTTPException) as ei:
        await capi.graph_local(A, depth=2, current_user=user, session=session)
    assert ei.value.status_code == 404


def _patch_graph(monkeypatch, *, nodes=10, edges=0, layout=None):
    """Хелпер: мокаем 4 зависимости эндпоинта /graph."""
    monkeypatch.setattr(connections, "get_full_graph", AsyncMock(return_value={"nodes": [], "edges": []}))
    monkeypatch.setattr(connections, "current_graph_node_count", AsyncMock(return_value=nodes))
    monkeypatch.setattr(connections, "current_graph_edge_count", AsyncMock(return_value=edges))
    monkeypatch.setattr(connections, "get_graph_layout", AsyncMock(return_value=layout))


async def test_graph_full_stale_when_no_layout(monkeypatch):
    _patch_graph(monkeypatch, nodes=10, edges=4, layout=None)
    user = SimpleNamespace(id=USER)

    resp = await capi.graph_full(current_user=user, session=MagicMock())
    assert resp.stale is True  # раскладки ещё нет → надо построить
    assert resp.layout is None
    assert resp.node_count == 10


async def test_graph_full_not_stale_when_few_new_connections(monkeypatch):
    # связей было 5, стало 6 → дельта 1 < порога (8) → НЕ устарел
    _patch_graph(
        monkeypatch, nodes=5, edges=6,
        layout={"nodes": [{"id": "x", "x": 1, "y": 2}], "node_count": 5, "edge_count": 5, "built_at": None},
    )
    user = SimpleNamespace(id=USER)

    resp = await capi.graph_full(current_user=user, session=MagicMock())
    assert resp.stale is False
    assert resp.layout == [{"id": "x", "x": 1, "y": 2}]


async def test_graph_full_stale_when_many_new_connections(monkeypatch):
    # связей было 5, стало 14 → дельта 9 ≥ порога (8) → устарел
    _patch_graph(
        monkeypatch, nodes=8, edges=14,
        layout={"nodes": [], "node_count": 5, "edge_count": 5, "built_at": None},
    )
    user = SimpleNamespace(id=USER)

    resp = await capi.graph_full(current_user=user, session=MagicMock())
    assert resp.stale is True


async def test_graph_full_stale_when_many_connections_removed(monkeypatch):
    # массовое архивирование: связей было 20, стало 5 → |дельта| 15 ≥ порога →
    # устарел (раскладка с висящими узлами; abs() ловит и убыль, не только рост).
    _patch_graph(
        monkeypatch, nodes=5, edges=5,
        layout={"nodes": [], "node_count": 20, "edge_count": 20, "built_at": None},
    )
    user = SimpleNamespace(id=USER)

    resp = await capi.graph_full(current_user=user, session=MagicMock())
    assert resp.stale is True


async def test_graph_full_not_stale_on_many_new_notes_but_few_connections(monkeypatch):
    # ключевой кейс: заметок добавилось МНОГО (5 → 30), но связей почти нет
    # (5 → 6) → баннер НЕ загорается (раньше загорался по node_count != current).
    _patch_graph(
        monkeypatch, nodes=30, edges=6,
        layout={"nodes": [], "node_count": 5, "edge_count": 5, "built_at": None},
    )
    user = SimpleNamespace(id=USER)

    resp = await capi.graph_full(current_user=user, session=MagicMock())
    assert resp.stale is False


async def test_ego_graph_center_always_present_under_cap(monkeypatch):
    """node_cap=1: центр обязан остаться в nodes (иначе битый рендер графа)."""
    a = str(A)
    monkeypatch.setattr(
        connections, "_neighbor_edges",
        AsyncMock(return_value=[_edge(a, "B", 0.9), _edge(a, "C", 0.8)]),
    )

    async def _cards(session, user_id, ids):
        return [{"id": i} for i in ids]
    monkeypatch.setattr(connections, "_node_cards", _cards)

    g = await connections.ego_graph(MagicMock(), USER, A, depth=1, node_cap=1)
    assert {n["id"] for n in g["nodes"]} == {a}  # только центр, и он на месте
    assert g["center"] == a
