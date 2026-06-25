"""B4: голос-в-дописку — воркер process_entry_upload.

Инвариант: STT заполняет body/transcription записи; статус done/failed на УРОВНЕ
записи (НЕ запускает classify заметки); по готовности — debounce re-index (B3).
Моки как в test_reembed_bookmark / test_uploads_endpoint — без БД/S3/STT.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


def _entry(**over):
    base = dict(
        id=uuid4(), bookmark_id=uuid4(), kind="user", body="",
        entry_ai_status="transcribing", transcription=None,
        media_file_id="uploads/x.ogg", duration=3.2, is_deleted=False,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _session_for(entry):
    """async_session() → один и тот же session/entry для read-draft и finalize."""
    session = AsyncMock()
    session.get = AsyncMock(return_value=entry)
    session.commit = AsyncMock()
    acm = MagicMock()
    acm.__aenter__ = AsyncMock(return_value=session)
    acm.__aexit__ = AsyncMock(return_value=False)
    return acm


def _storage():
    s = MagicMock()
    s.download_to_path = AsyncMock()
    s.delete = AsyncMock()
    return s


class TestProcessEntryUpload:
    async def test_happy_fills_body_and_reindexes(self):
        from app.worker import entry_uploads

        entry = _entry()
        acm, storage = _session_for(entry), _storage()
        redis = AsyncMock()
        redis.enqueue_job = AsyncMock()

        with patch("app.database.async_session", return_value=acm), \
             patch("app.worker.entry_uploads._build_storage", return_value=storage), \
             patch(
                 "app.worker.entry_uploads._transcribe",
                 new=AsyncMock(return_value="привет мир"),
             ):
            await entry_uploads.process_entry_upload(
                {"redis": redis, "job_try": 1}, str(entry.id),
                "uploads/x.ogg", "x.ogg", "audio/ogg", 3.2,
            )

        assert entry.body == "привет мир"
        assert entry.transcription == "привет мир"
        assert entry.entry_ai_status == "done"
        # По готовности — debounce re-index по заметке (B3), дедуп по _job_id.
        redis.enqueue_job.assert_awaited_once()
        args, kwargs = redis.enqueue_job.call_args
        assert args[0] == "reembed_bookmark_task"
        assert args[1] == str(entry.bookmark_id)
        assert kwargs["_job_id"] == f"reembed:{entry.bookmark_id}"
        storage.delete.assert_awaited_once()  # объект удалён после успеха

    async def test_idempotent_skip_when_not_transcribing(self):
        # Повтор джоба после успеха: запись уже done → не перетранскрибируем.
        from app.worker import entry_uploads

        entry = _entry(entry_ai_status="done", body="уже готово")
        acm, storage = _session_for(entry), _storage()
        redis = AsyncMock()
        redis.enqueue_job = AsyncMock()

        with patch("app.database.async_session", return_value=acm), \
             patch("app.worker.entry_uploads._build_storage", return_value=storage), \
             patch("app.worker.entry_uploads._transcribe", new=AsyncMock()) as tr:
            await entry_uploads.process_entry_upload(
                {"redis": redis, "job_try": 1}, str(entry.id),
                "uploads/x.ogg", "x.ogg", "audio/ogg", None,
            )

        tr.assert_not_called()
        redis.enqueue_job.assert_not_awaited()
        assert entry.body == "уже готово"  # не тронут
        storage.delete.assert_awaited_once()  # orphan-объект подчищен

    async def test_skips_soft_deleted_entry(self):
        # Пользователь удалил запись (soft-delete) до старта джоба → не транскрибируем.
        from app.worker import entry_uploads

        entry = _entry(is_deleted=True)  # статус ещё transcribing, но запись удалена
        acm, storage = _session_for(entry), _storage()
        redis = AsyncMock()
        redis.enqueue_job = AsyncMock()

        with patch("app.database.async_session", return_value=acm), \
             patch("app.worker.entry_uploads._build_storage", return_value=storage), \
             patch("app.worker.entry_uploads._transcribe", new=AsyncMock()) as tr:
            await entry_uploads.process_entry_upload(
                {"redis": redis, "job_try": 1}, str(entry.id),
                "uploads/x.ogg", "x.ogg", "audio/ogg", None,
            )

        tr.assert_not_called()
        redis.enqueue_job.assert_not_awaited()
        storage.delete.assert_awaited_once()  # orphan-объект подчищен

    async def test_stt_error_marks_failed_entry_remains(self):
        from app.worker import entry_uploads

        from shared.media.stt import STTError

        entry = _entry()
        acm, storage = _session_for(entry), _storage()
        redis = AsyncMock()
        redis.enqueue_job = AsyncMock()

        with patch("app.database.async_session", return_value=acm), \
             patch("app.worker.entry_uploads._build_storage", return_value=storage), \
             patch(
                 "app.worker.entry_uploads._transcribe",
                 new=AsyncMock(side_effect=STTError("не распознано")),
             ):
            await entry_uploads.process_entry_upload(
                {"redis": redis, "job_try": 1}, str(entry.id),
                "uploads/x.ogg", "x.ogg", "audio/ogg", None,
            )

        assert entry.entry_ai_status == "failed"
        assert entry.body == ""  # запись остаётся (не удалена)
        redis.enqueue_job.assert_not_awaited()  # re-index не дёргаем
        storage.delete.assert_awaited_once()
