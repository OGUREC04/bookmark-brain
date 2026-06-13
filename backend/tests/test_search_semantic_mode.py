"""Тест mode='semantic' в SearchService — задача 6 (без БД).

Проверяем, что семантический режим форсит веса (1.0 semantic / 0.0 text) в
сгенерированном SQL, а hybrid оставляет динамические. Реальная релевантность
(golden set) — интеграционно у пользователя.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from app.services.search import SearchService

USER = UUID("11111111-1111-1111-1111-111111111111")


class _R:
    def __init__(self, rows=None, scalar=0):
        self._rows = rows or []
        self._scalar = scalar

    def fetchall(self):
        return self._rows

    def scalar(self):
        return self._scalar


def _svc(session):
    emb = MagicMock()
    emb.get_embedding = AsyncMock(return_value=[0.1, 0.2])  # use_semantic=True
    return SearchService(session, emb)


async def test_semantic_mode_forces_full_semantic_weight():
    session = MagicMock()
    # main → [], count → 0, fallback → [] → return [], 0
    session.execute = AsyncMock(side_effect=[_R([]), _R(scalar=0), _R([])])
    svc = _svc(session)

    results, total = await svc.search(
        USER, "инвестиции в стартапы", mode="semantic"
    )

    assert results == [] and total == 0
    main_sql = str(session.execute.call_args_list[0].args[0])
    assert "1.0 * semantic_score + 0.0 * text_score" in main_sql


async def test_hybrid_mode_keeps_dynamic_weights():
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[_R([]), _R(scalar=0), _R([])])
    svc = _svc(session)

    # >2 слов → 0.7 / 0.3 (динамика hybrid)
    await svc.search(USER, "инвестиции в стартапы рынок", mode="hybrid")

    main_sql = str(session.execute.call_args_list[0].args[0])
    assert "0.7 * semantic_score + 0.3 * text_score" in main_sql


async def test_semantic_falls_back_to_fulltext_without_embedding():
    """Если эмбеддинг запроса не получился — semantic деградирует в full-text."""
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[_R([]), _R(scalar=0), _R([])])
    emb = MagicMock()
    emb.get_embedding = AsyncMock(side_effect=RuntimeError("voyage down"))
    svc = SearchService(session, emb)

    await svc.search(USER, "инвестиции в стартапы", mode="semantic")

    main_sql = str(session.execute.call_args_list[0].args[0])
    assert "0.0 * semantic_score + 1.0 * text_score" in main_sql
