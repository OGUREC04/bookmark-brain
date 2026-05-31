"""Тикет 0rn: правка тела текста заметки (raw_text) через PATCH /bookmarks/{id}.

Ключевое поведение — порог «материальной» правки: значимое изменение текста
триггерит фоновую переобработку (ai_status=pending + enqueue), мелкая правка
(пара слов) — просто сохраняется без холостой LLM-перегенерации.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.api.bookmarks import update_bookmark
from app.schemas import BookmarkUpdate
from fastapi import HTTPException


@pytest.fixture
def user():
    u = MagicMock()
    u.id = uuid4()
    u.timezone = "Europe/Moscow"
    return u


def _session_returning(bookmark) -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=bookmark)
    s = AsyncMock()
    s.execute = AsyncMock(return_value=result)
    return s


def _bookmark(raw_text: str):
    bm = MagicMock()
    bm.id = uuid4()
    bm.raw_text = raw_text
    bm.structured_data = None  # PATCH без structured_data → cascade пропущен
    return bm


def _mock_pool(monkeypatch) -> AsyncMock:
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock()
    monkeypatch.setattr(
        "app.api.bookmarks.get_arq_pool", AsyncMock(return_value=pool)
    )
    return pool


async def test_major_edit_triggers_reprocess(user, monkeypatch):
    """Текст переписан целиком → полная переобработка."""
    bm = _bookmark("заметка про машинное обучение и нейросети")
    session = _session_returning(bm)
    pool = _mock_pool(monkeypatch)

    body = BookmarkUpdate(raw_text="рецепт борща с говядиной и свёклой на выходные")
    out = await update_bookmark(bm.id, body, user, session)

    assert out is bm
    assert bm.raw_text == "рецепт борща с говядиной и свёклой на выходные"
    assert bm.ai_status == "pending"
    assert bm.ai_error is None
    assert bm.retry_count == 0
    pool.enqueue_job.assert_awaited_once_with("process_bookmark_task", str(bm.id))


async def test_minor_edit_skips_reprocess(user, monkeypatch):
    """В длинной заметке поправили пару слов → НЕ переобрабатываем."""
    base = (
        "Сегодня разбирался с архитектурой связей между заметками: вектор рождает "
        "связи по косинусу, рёбра храним в Postgres, граф-фичи делаем обычным SQL. "
        "Neo4j для MVP не нужен, всё закрывает pgvector и существующий пайплайн."
    )
    bm = _bookmark(base)
    session = _session_returning(bm)
    pool = _mock_pool(monkeypatch)

    # дописали пару слов в конце — смысл тот же
    body = BookmarkUpdate(raw_text=base + " Проверить на бэкфилле.")
    out = await update_bookmark(bm.id, body, user, session)

    assert out is bm
    assert bm.raw_text.endswith("Проверить на бэкфилле.")
    # ai_status НЕ трогаем, переобработку не зовём
    pool.enqueue_job.assert_not_awaited()


async def test_short_note_meaning_flip_triggers_reprocess(user, monkeypatch):
    """В короткой заметке даже «не» переворачивает смысл → переобработка."""
    bm = _bookmark("молоко")
    session = _session_returning(bm)
    pool = _mock_pool(monkeypatch)

    body = BookmarkUpdate(raw_text="не покупать молоко")
    await update_bookmark(bm.id, body, user, session)

    assert bm.ai_status == "pending"
    pool.enqueue_job.assert_awaited_once()


async def test_empty_raw_text_rejected_422(user, monkeypatch):
    bm = _bookmark("исходный текст")
    session = _session_returning(bm)
    _mock_pool(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await update_bookmark(bm.id, BookmarkUpdate(raw_text="   "), user, session)
    assert exc.value.status_code == 422


async def test_raw_text_is_trimmed(user, monkeypatch):
    bm = _bookmark("старый")
    session = _session_returning(bm)
    _mock_pool(monkeypatch)

    await update_bookmark(bm.id, BookmarkUpdate(raw_text="  новый длинный текст заметки  "), user, session)
    assert bm.raw_text == "новый длинный текст заметки"


async def test_patch_without_raw_text_does_not_reprocess(user, monkeypatch):
    """PATCH меняет только title → raw_text не трогается, переобработки нет."""
    bm = _bookmark("текст")
    bm.title = "старый"
    session = _session_returning(bm)
    pool = _mock_pool(monkeypatch)

    await update_bookmark(bm.id, BookmarkUpdate(title="новый заголовок"), user, session)

    assert bm.title == "новый заголовок"
    pool.enqueue_job.assert_not_awaited()
