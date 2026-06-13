"""TDD for app.api.uploads helper logic (3sr, шаг 5).

Тип-детекция (аудио / документ / неподдерживаемое -> 415) и лимиты размера
(-> 413) — самая баг-склонная часть эндпоинта — вынесены в чистые функции и
покрыты здесь. Тонкая HTTP-обвязка (multipart -> S3 -> черновик -> enqueue ->
201) проверяется на деплое/в integration (как у connections): сериализация
BookmarkResponse требует БД-дефолтов (is_favorite и пр.).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api import uploads


# ── _resolve_kind ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "content_type,filename",
    [
        ("audio/ogg", "voice.ogg"),
        ("audio/webm", "rec.webm"),
        ("audio/mp4", "ios.m4a"),
        ("video/mp4", "note.mp4"),   # video_note — берём аудио-дорожку
        ("application/octet-stream", "x.wav"),
    ],
)
def test_resolve_kind_audio(content_type, filename):
    assert uploads._resolve_kind(content_type, filename, None) == "audio"


@pytest.mark.parametrize(
    "content_type,filename",
    [
        ("application/pdf", "doc.pdf"),
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "r.docx"),
        (None, "notes.txt"),
        ("text/markdown", "readme.md"),
    ],
)
def test_resolve_kind_document(content_type, filename):
    assert uploads._resolve_kind(content_type, filename, None) == "document"


@pytest.mark.parametrize(
    "content_type,filename",
    [("image/png", "pic.png"), ("application/zip", "a.zip")],
)
def test_resolve_kind_unsupported(content_type, filename):
    assert uploads._resolve_kind(content_type, filename, None) is None


def test_resolve_kind_explicit_overrides_detection():
    # фронт явно сказал «audio» — верим ему, даже если mime странный
    assert uploads._resolve_kind("application/octet-stream", "blob", "audio") == "audio"
    assert uploads._resolve_kind("application/octet-stream", "blob", "document") == "document"


# ── _max_bytes ─────────────────────────────────────────────────────────────

def test_max_bytes_per_kind():
    settings = SimpleNamespace(UPLOAD_MAX_AUDIO_MB=25, UPLOAD_MAX_DOC_MB=20)
    assert uploads._max_bytes("audio", settings) == 25 * 1024 * 1024
    assert uploads._max_bytes("document", settings) == 20 * 1024 * 1024


# ── _storage_key ───────────────────────────────────────────────────────────

def test_storage_key_prefixed_and_keeps_suffix():
    key = uploads._storage_key("rec.webm")
    assert key.startswith("uploads/")
    assert key.endswith(".webm")


def test_storage_key_unique_per_call():
    assert uploads._storage_key("a.ogg") != uploads._storage_key("a.ogg")


def test_storage_key_handles_no_extension():
    key = uploads._storage_key("blob")
    assert key.startswith("uploads/")
