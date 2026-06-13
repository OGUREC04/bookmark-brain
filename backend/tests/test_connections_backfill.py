"""Тест backfill_bookmark_links — задача 4b (без БД).

Оркестрация: keyset-батчи, вызов build_links на каждую заметку, конвертация
эмбеддинга, commit на батч, best-effort на ошибке элемента. Реальный прогон —
пользователем против Postgres.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import app.services.connections as conn
from app.worker import scheduled

U = UUID("11111111-1111-1111-1111-111111111111")
B1 = UUID("00000000-0000-0000-0000-000000000001")
B2 = UUID("00000000-0000-0000-0000-000000000002")


def _async_session_factory(session):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


async def test_backfill_processes_all_and_commits(monkeypatch):
    emb2 = MagicMock()
    emb2.tolist = MagicMock(return_value=[0.2])
    r1 = SimpleNamespace(id=B1, user_id=U, embedding=[0.1])  # list → без tolist
    r2 = SimpleNamespace(id=B2, user_id=U, embedding=emb2)   # vector → tolist

    session = MagicMock()
    # 1-й батч — две записи, 2-й — пусто (конец).
    session.execute = AsyncMock(side_effect=[_Result([r1, r2]), _Result([])])
    session.commit = AsyncMock()
    monkeypatch.setattr(conn, "build_links_for_bookmark", AsyncMock(return_value=1))

    with patch("app.database.async_session", _async_session_factory(session)):
        n = await scheduled.backfill_bookmark_links(batch_size=200)

    assert n == 2
    assert conn.build_links_for_bookmark.await_count == 2
    embs = [c.args[3] for c in conn.build_links_for_bookmark.await_args_list]
    assert [0.1] in embs and [0.2] in embs  # обе конвертации
    session.commit.assert_awaited_once()  # один батч


async def test_backfill_empty_corpus_no_commit(monkeypatch):
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[_Result([])])
    session.commit = AsyncMock()
    monkeypatch.setattr(conn, "build_links_for_bookmark", AsyncMock())

    with patch("app.database.async_session", _async_session_factory(session)):
        n = await scheduled.backfill_bookmark_links()

    assert n == 0
    session.commit.assert_not_awaited()
    conn.build_links_for_bookmark.assert_not_awaited()


async def test_backfill_item_error_is_isolated(monkeypatch):
    r1 = SimpleNamespace(id=B1, user_id=U, embedding=[0.1])
    r2 = SimpleNamespace(id=B2, user_id=U, embedding=[0.2])
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[_Result([r1, r2]), _Result([])])
    session.commit = AsyncMock()
    # Первый падает, второй ок — бэкфилл не должен остановиться.
    monkeypatch.setattr(
        conn, "build_links_for_bookmark",
        AsyncMock(side_effect=[RuntimeError("boom"), 1]),
    )

    with patch("app.database.async_session", _async_session_factory(session)):
        n = await scheduled.backfill_bookmark_links()

    assert n == 2  # обе обработаны (счётчик progress), ошибка проглочена
    assert conn.build_links_for_bookmark.await_count == 2


async def test_backfill_registered_in_worker():
    """Джоба зарегистрирована в WorkerSettings.functions (enqueue вручную)."""
    from app.worker import WorkerSettings, backfill_bookmark_links

    assert backfill_bookmark_links in WorkerSettings.functions
