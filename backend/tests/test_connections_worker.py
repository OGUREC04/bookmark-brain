"""Тест _maybe_build_connections — задача 4a (хелпер связывания в воркере).

Вынесен из 600-строчного impl в отдельный хелпер ради изоляции: проверяем
guard'ы, конвертацию эмбеддинга, commit и best-effort-проглатывание ошибки.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import app.services.connections as conn
from app.worker import processing


async def test_skips_when_no_bookmark():
    assert await processing._maybe_build_connections(MagicMock(), None) == 0


async def test_skips_when_no_embedding():
    bm = MagicMock()
    bm.embedding = None
    bm.ai_status = "completed"
    assert await processing._maybe_build_connections(MagicMock(), bm) == 0


async def test_skips_when_status_not_ready():
    bm = MagicMock()
    bm.embedding = [0.1]
    bm.ai_status = "pending"
    assert await processing._maybe_build_connections(MagicMock(), bm) == 0


async def test_calls_build_links_and_commits(monkeypatch):
    monkeypatch.setattr(conn, "build_links_for_bookmark", AsyncMock(return_value=3))
    session = MagicMock()
    session.commit = AsyncMock()
    bm = MagicMock()
    bm.embedding = MagicMock()
    bm.embedding.tolist = MagicMock(return_value=[0.1, 0.2])
    bm.ai_status = "completed"

    n = await processing._maybe_build_connections(session, bm)

    assert n == 3
    conn.build_links_for_bookmark.assert_awaited_once()
    assert conn.build_links_for_bookmark.await_args.args[3] == [0.1, 0.2]  # tolist
    session.commit.assert_awaited_once()


async def test_no_commit_when_zero_links(monkeypatch):
    monkeypatch.setattr(conn, "build_links_for_bookmark", AsyncMock(return_value=0))
    session = MagicMock()
    session.commit = AsyncMock()
    bm = MagicMock()
    bm.embedding = [0.1]  # list → нет tolist
    bm.ai_status = "partial"

    n = await processing._maybe_build_connections(session, bm)

    assert n == 0
    session.commit.assert_not_awaited()


async def test_best_effort_swallows_error(monkeypatch):
    monkeypatch.setattr(
        conn, "build_links_for_bookmark", AsyncMock(side_effect=RuntimeError("db down"))
    )
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    bm = MagicMock()
    bm.embedding = [0.1]
    bm.ai_status = "completed"

    n = await processing._maybe_build_connections(session, bm)  # не бросает

    assert n == 0
    session.rollback.assert_awaited()


async def test_partial_status_is_processed(monkeypatch):
    """ai_status='partial' НЕ скипается — связи строятся (partial входит в набор)."""
    monkeypatch.setattr(conn, "build_links_for_bookmark", AsyncMock(return_value=2))
    session = MagicMock()
    session.commit = AsyncMock()
    bm = MagicMock()
    bm.embedding = [0.1]
    bm.ai_status = "partial"

    n = await processing._maybe_build_connections(session, bm)

    assert n == 2
    conn.build_links_for_bookmark.assert_awaited_once()
    session.commit.assert_awaited_once()
