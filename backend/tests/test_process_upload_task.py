"""TDD for app.worker.uploads.process_upload_task (3sr, шаг 4b).

Воркер-джоба обработки медиа-загрузки из Mini App: скачивает файл из Object
Storage, распознаёт (аудио) или извлекает текст (документ), дозаполняет
заметку-черновик и передаёт её в ОБЫЧНЫЙ конвейер (process_bookmark_task),
не дублируя его. Лучшее-усилие: фейл STT/extract -> ai_status='failed'.

Без БД/S3/STT/ffmpeg: всё замокано. Реальный прогон — на деплое.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from app.worker import uploads

BID = "00000000-0000-0000-0000-0000000000aa"


def _session_cm(session):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


def _bookmark(ai_status="transcribing", raw_text=""):
    return SimpleNamespace(
        id=UUID(BID),
        raw_text=raw_text,
        transcription=None,
        document_page_count=None,
        ai_status=ai_status,
        ai_error=None,
    )


def _ctx():
    return {"redis": MagicMock(enqueue_job=AsyncMock())}


def _wire(monkeypatch, *, storage=None, stt=None):
    """Patch the module-level factories so the job uses our mocks."""
    storage = storage or MagicMock(
        download_to_path=AsyncMock(), delete=AsyncMock()
    )
    stt = stt or MagicMock(transcribe=AsyncMock(return_value="распознанный текст"))
    monkeypatch.setattr(uploads, "_build_storage", lambda: storage)
    monkeypatch.setattr(uploads, "_build_stt", lambda: stt)
    return storage, stt


# ── audio happy path ───────────────────────────────────────────────────────

async def test_audio_happy_path(monkeypatch):
    storage, stt = _wire(monkeypatch)
    monkeypatch.setattr(uploads, "needs_transcode", lambda name: False)
    bm = _bookmark()
    session = MagicMock(get=AsyncMock(return_value=bm), commit=AsyncMock())
    ctx = _ctx()

    with patch("app.database.async_session", _session_cm(session)):
        await uploads.process_upload_task(
            ctx, BID, "uploads/x.ogg", "audio", "x.ogg", duration=4.0
        )

    storage.download_to_path.assert_awaited_once()
    assert storage.download_to_path.await_args.args[0] == "uploads/x.ogg"
    stt.transcribe.assert_awaited_once()
    assert bm.raw_text == "распознанный текст"
    assert bm.transcription == "распознанный текст"
    assert bm.ai_status == "pending"
    session.commit.assert_awaited()
    ctx["redis"].enqueue_job.assert_awaited_once()
    assert ctx["redis"].enqueue_job.await_args.args[0] == "process_bookmark_task"
    assert ctx["redis"].enqueue_job.await_args.args[1] == BID
    storage.delete.assert_awaited_once_with("uploads/x.ogg")


async def test_audio_transcodes_browser_format(monkeypatch, tmp_path):
    storage, stt = _wire(monkeypatch)
    monkeypatch.setattr(uploads, "needs_transcode", lambda name: True)
    transcode = AsyncMock()
    monkeypatch.setattr(uploads, "transcode_to_ogg_opus", transcode)
    bm = _bookmark()
    session = MagicMock(get=AsyncMock(return_value=bm), commit=AsyncMock())

    with patch("app.database.async_session", _session_cm(session)):
        await uploads.process_upload_task(
            ctx=_ctx(), bookmark_id=BID, storage_key="uploads/r.webm",
            kind="audio", filename="r.webm", duration=5.0,
        )

    transcode.assert_awaited_once()  # webm -> ogg before STT
    stt.transcribe.assert_awaited_once()
    # STT got the transcoded .ogg, not the raw .webm
    sent = stt.transcribe.await_args.args[0]
    assert str(sent).endswith(".ogg")
    assert bm.ai_status == "pending"


# ── document happy path ──────────────────────────────────────────────────────

async def test_document_happy_path(monkeypatch):
    storage, _ = _wire(monkeypatch)
    extract = AsyncMock(
        return_value=SimpleNamespace(text="текст из pdf", page_count=3, truncated=False)
    )
    monkeypatch.setattr(uploads, "extract_text", extract)
    monkeypatch.setattr(uploads, "detect_format", lambda mime, name: "pdf")
    bm = _bookmark(ai_status="extracting")
    session = MagicMock(get=AsyncMock(return_value=bm), commit=AsyncMock())
    ctx = _ctx()

    with patch("app.database.async_session", _session_cm(session)):
        await uploads.process_upload_task(
            ctx, BID, "uploads/doc.pdf", "document", "doc.pdf",
        )

    extract.assert_awaited_once()
    assert bm.raw_text == "текст из pdf"
    assert bm.document_page_count == 3
    assert bm.transcription is None
    assert bm.ai_status == "pending"
    ctx["redis"].enqueue_job.assert_awaited_once()


# ── caption ──────────────────────────────────────────────────────────────────

async def test_caption_prepended_to_recognized_text(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.setattr(uploads, "needs_transcode", lambda name: False)
    bm = _bookmark(raw_text="моя подпись")  # endpoint stored caption here
    session = MagicMock(get=AsyncMock(return_value=bm), commit=AsyncMock())

    with patch("app.database.async_session", _session_cm(session)):
        await uploads.process_upload_task(
            _ctx(), BID, "uploads/x.ogg", "audio", "x.ogg", duration=3.0
        )

    assert bm.raw_text == "моя подпись\n\nраспознанный текст"


# ── failure path ─────────────────────────────────────────────────────────────

async def test_stt_failure_marks_bookmark_failed(monkeypatch):
    from shared.media.stt import STTError

    storage, stt = _wire(monkeypatch)
    stt.transcribe = AsyncMock(side_effect=STTError("yandex down"))
    monkeypatch.setattr(uploads, "needs_transcode", lambda name: False)
    bm = _bookmark()
    session = MagicMock(get=AsyncMock(return_value=bm), commit=AsyncMock())
    ctx = _ctx()

    with patch("app.database.async_session", _session_cm(session)):
        await uploads.process_upload_task(
            ctx, BID, "uploads/x.ogg", "audio", "x.ogg", duration=4.0
        )

    assert bm.ai_status == "failed"
    assert bm.ai_error and "yandex down" in bm.ai_error
    ctx["redis"].enqueue_job.assert_not_awaited()  # broken -> no pipeline
    storage.delete.assert_awaited_once()  # cleanup still runs


# ── idempotency ──────────────────────────────────────────────────────────────

async def test_idempotent_skip_if_already_processed(monkeypatch):
    storage, stt = _wire(monkeypatch)
    bm = _bookmark(ai_status="completed")  # a prior run already finished
    session = MagicMock(get=AsyncMock(return_value=bm), commit=AsyncMock())
    ctx = _ctx()

    with patch("app.database.async_session", _session_cm(session)):
        await uploads.process_upload_task(
            ctx, BID, "uploads/x.ogg", "audio", "x.ogg", duration=4.0
        )

    storage.download_to_path.assert_not_awaited()
    stt.transcribe.assert_not_awaited()
    ctx["redis"].enqueue_job.assert_not_awaited()


async def test_missing_bookmark_is_noop(monkeypatch):
    storage, stt = _wire(monkeypatch)
    session = MagicMock(get=AsyncMock(return_value=None), commit=AsyncMock())
    ctx = _ctx()

    with patch("app.database.async_session", _session_cm(session)):
        await uploads.process_upload_task(
            ctx, BID, "uploads/x.ogg", "audio", "x.ogg", duration=4.0
        )

    stt.transcribe.assert_not_awaited()
    ctx["redis"].enqueue_job.assert_not_awaited()


# ── registration ─────────────────────────────────────────────────────────────

def test_process_upload_task_registered_in_worker():
    from app.worker import WorkerSettings, process_upload_task

    assert process_upload_task in WorkerSettings.functions
