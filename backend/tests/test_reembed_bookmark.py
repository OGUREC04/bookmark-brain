"""B3: classify-free re-index дописок — _build_embedding_text + reembed_bookmark_task.

Главная инвариант: дописки попадают в embedding/связи БЕЗ вызова classify (FR-5/NFR-1).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.bookmark_processor import _build_embedding_text


def _clf(**over):
    base = dict(takeaway=None, summary=None, key_ideas=None, tags=None)
    base.update(over)
    return SimpleNamespace(**base)


def _bm(**over):
    base = dict(title=None, full_text=None, transcription=None, raw_text="заметка")
    base.update(over)
    return SimpleNamespace(**base)


class TestEmbeddingTextWithEntries:
    def test_entries_included_in_base(self):
        out = _build_embedding_text(
            _bm(raw_text="полить цветы"), _clf(), ["купить удобрение", "цветы засыхают"]
        )
        assert "полить цветы" in out
        assert "купить удобрение" in out
        assert "цветы засыхают" in out

    def test_no_entries_backward_compatible(self):
        # Существующие вызовы (2 аргумента) работают как раньше.
        assert _build_embedding_text(_bm(raw_text="x"), _clf()) == "x"

    def test_blank_entries_ignored(self):
        out = _build_embedding_text(_bm(raw_text="тело"), _clf(), ["", "   ", "реальное"])
        assert out == "тело\nреальное"


class TestReembedBookmarkTask:
    async def test_reindex_denorm_embed_links_no_classify(self):
        from app.worker import scheduled

        bid = uuid4()
        bm = SimpleNamespace(
            id=bid, user_id=uuid4(), title=None, full_text=None, transcription=None,
            raw_text="заметка", takeaway=None, summary=None, key_ideas=None,
            embedding=None, entries_text=None,
        )
        session = AsyncMock()
        session.get = AsyncMock(return_value=bm)
        exec_res = MagicMock()
        exec_res.scalars.return_value.all.return_value = ["дописка раз", "дописка два"]
        session.execute = AsyncMock(return_value=exec_res)
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        acm = MagicMock()
        acm.__aenter__ = AsyncMock(return_value=session)
        acm.__aexit__ = AsyncMock(return_value=False)

        emb_service = AsyncMock()
        emb_service.get_embedding = AsyncMock(return_value=[0.1] * 1024)
        emb_service.close = AsyncMock()

        with patch("app.database.async_session", return_value=acm), \
             patch("app.services.embeddings.create_embedding_service", return_value=emb_service), \
             patch(
                 "app.services.connections.build_links_for_bookmark",
                 new=AsyncMock(return_value=1),
             ) as mock_links:
            ok = await scheduled.reembed_bookmark_task(None, str(bid))

        assert ok is True
        # Денорм под FTS-триггер.
        assert bm.entries_text == "дописка раз\nдописка два"
        # Embedding записан; текст включает и тело, и дописки.
        assert bm.embedding == [0.1] * 1024
        emb_service.get_embedding.assert_awaited_once()
        embed_text = emb_service.get_embedding.call_args[0][0]
        assert "заметка" in embed_text
        assert "дописка раз" in embed_text
        # Связи пересчитаны. (classify не вызывался — его в функции нет вообще.)
        mock_links.assert_awaited_once()
        emb_service.close.assert_awaited_once()

    async def test_missing_bookmark_returns_false(self):
        from app.worker import scheduled

        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        acm = MagicMock()
        acm.__aenter__ = AsyncMock(return_value=session)
        acm.__aexit__ = AsyncMock(return_value=False)
        emb_service = AsyncMock()
        emb_service.close = AsyncMock()

        with patch("app.database.async_session", return_value=acm), \
             patch("app.services.embeddings.create_embedding_service", return_value=emb_service):
            ok = await scheduled.reembed_bookmark_task(None, str(uuid4()))

        assert ok is False
