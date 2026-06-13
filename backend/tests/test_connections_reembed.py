"""Тест reembed_all_bookmarks — пере-эмбеддинг старых заметок под новый рецепт (AD-7).

Без БД/Voyage: проверяем оркестрацию (батчи, единый рецепт _build_embedding_text,
запись embedding, commit, закрытие сервиса). Реальный прогон — на деплое.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import app.services.embeddings as emb_mod
from app.worker import scheduled

B1 = UUID("00000000-0000-0000-0000-000000000001")
B2 = UUID("00000000-0000-0000-0000-000000000002")


def _async_session_factory(session):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


class _Result:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


def _bm(id_, **kw):
    base = dict(
        id=id_, title=None, full_text=None, transcription=None,
        raw_text="", takeaway=None, summary=None, key_ideas=None, embedding=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


async def test_reembed_all_processes_and_commits(monkeypatch):
    bm1 = _bm(B1, title="Заметка 1", raw_text="реальный текст один", summary="сводка")
    bm2 = _bm(B2, full_text="тело статьи", raw_text="ссылка", takeaway="вывод", key_ideas=["идея"])

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[_Result([bm1, bm2]), _Result([])])
    session.commit = AsyncMock()

    service = MagicMock()
    service.get_embedding = AsyncMock(return_value=[0.1, 0.2])
    service.close = AsyncMock()
    monkeypatch.setattr(emb_mod, "create_embedding_service", MagicMock(return_value=service))

    with patch("app.database.async_session", _async_session_factory(session)):
        n = await scheduled.reembed_all_bookmarks(batch_size=100)

    assert n == 2
    assert service.get_embedding.await_count == 2
    # эмбеддинг переписан у обеих заметок
    assert bm1.embedding == [0.1, 0.2]
    assert bm2.embedding == [0.1, 0.2]
    # реальный текст реально попал в эмбеддинг-текст (новый рецепт)
    first_text = service.get_embedding.await_args_list[0].args[0]
    assert "реальный текст один" in first_text
    session.commit.assert_awaited_once()
    service.close.assert_awaited_once()


async def test_reembed_item_error_isolated(monkeypatch):
    from app.services.embeddings import EmbeddingError

    bm1 = _bm(B1, raw_text="первая")
    bm2 = _bm(B2, raw_text="вторая")
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[_Result([bm1, bm2]), _Result([])])
    session.commit = AsyncMock()

    service = MagicMock()
    service.get_embedding = AsyncMock(side_effect=[EmbeddingError("voyage down"), [0.3]])
    service.close = AsyncMock()
    monkeypatch.setattr(emb_mod, "create_embedding_service", MagicMock(return_value=service))

    with patch("app.database.async_session", _async_session_factory(session)):
        n = await scheduled.reembed_all_bookmarks()

    assert n == 1  # первая упала (проглочено), вторая ок
    assert bm2.embedding == [0.3]
    service.close.assert_awaited_once()  # сервис закрыт даже при ошибке элемента


async def test_reembed_registered_in_worker():
    from app.worker import WorkerSettings, reembed_all_bookmarks

    assert reembed_all_bookmarks in WorkerSettings.functions
