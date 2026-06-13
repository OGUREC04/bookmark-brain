"""Тесты `_build_embedding_text` — задача 2 (AD-7).

Реальный текст заметки — основа эмбеддинга, ИИ-поля — добавка. Проверяем, что
сырой контент теперь ПОПАДАЕТ в эмбеддинг (раньше был лишь fallback), что
ИИ-поля сохраняются, дедуп источников и обрезка до 8000.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.models import Bookmark
from app.services.bookmark_processor import (
    MAX_EMBEDDING_TEXT_CHARS,
    _build_embedding_text,
)


def _clf(*, takeaway=None, summary=None, key_ideas=None, tags=None):
    return SimpleNamespace(
        takeaway=takeaway, summary=summary, key_ideas=key_ideas, tags=tags
    )


def test_raw_text_now_included_as_backbone():
    """Сырой текст заметки теперь в эмбеддинге, а не только в fallback."""
    bm = Bookmark(raw_text="мысли про привлечение инвестиций в стартап", title=None)
    out = _build_embedding_text(bm, _clf(summary="о финансировании"))
    assert "привлечение инвестиций" in out
    assert "о финансировании" in out  # ИИ-добавка тоже на месте


def test_article_full_text_is_backbone_for_links():
    bm = Bookmark(
        raw_text="https://example.com/article",
        title="Как поднять раунд",
        full_text="Полный текст статьи про венчурное финансирование и раунды.",
    )
    out = _build_embedding_text(bm, _clf(key_ideas=["раунд A", "венчур"], tags=["startup"]))
    assert "Как поднять раунд" in out          # title
    assert "венчурное финансирование" in out   # full_text — основа
    assert "раунд A" in out and "startup" in out  # ИИ-добавка


def test_ai_fields_still_present():
    bm = Bookmark(raw_text="короткая заметка", title=None)
    out = _build_embedding_text(
        bm, _clf(takeaway="вывод", summary="сводка", key_ideas=["идея1"], tags=["t1", "t2"])
    )
    for piece in ("короткая заметка", "вывод", "сводка", "идея1", "t1 t2"):
        assert piece in out


def test_voice_transcription_not_duplicated():
    """Для voice raw_text часто == transcription — не дублируем."""
    text = "это голосовая заметка про дедлайн"
    bm = Bookmark(raw_text=text, transcription=text, title=None)
    out = _build_embedding_text(bm, _clf())
    assert out.count("голосовая заметка про дедлайн") == 1


def test_truncated_to_max_chars():
    bm = Bookmark(raw_text="x" * 20000, title=None)
    out = _build_embedding_text(bm, _clf(summary="y" * 5000))
    assert len(out) == MAX_EMBEDDING_TEXT_CHARS


def test_fallback_when_everything_empty():
    bm = Bookmark(raw_text="", title=None)
    out = _build_embedding_text(bm, _clf())
    assert out == ""  # пусто, но не падает
