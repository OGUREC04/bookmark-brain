"""B4: POST /api/v1/bookmarks/{id}/entries/upload — валидация + создание записи.

Тонкая обвязка (multipart→S3→черновик→enqueue) — как в test_uploads_endpoint:
размер/тип-хелперы переиспользуются из app.api.uploads (уже покрыты там), здесь —
НОВОЕ: IDOR, только-аудио (415), пустой (400), большой (413), happy-orchestration.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.api.entries import upload_entry
from app.models import NoteEntry
from fastapi import HTTPException


@pytest.fixture
def user():
    u = MagicMock()
    u.id = uuid4()
    return u


def _owner(found: bool):
    res = MagicMock()
    res.scalar_one_or_none.return_value = uuid4() if found else None
    return res


def _session(*results):
    s = AsyncMock()
    s.add = MagicMock()
    s.flush = AsyncMock()
    s.refresh = AsyncMock()
    s.execute = AsyncMock(side_effect=list(results))
    return s


class _FakeUpload:
    def __init__(self, content_type, filename, data=b"audio-bytes"):
        self.content_type = content_type
        self.filename = filename
        self._data = data

    async def read(self, n: int = -1):
        return self._data


@pytest.fixture
def storage():
    s = MagicMock()
    s.put_bytes = AsyncMock()
    s.delete = AsyncMock()
    return s


@pytest.fixture(autouse=True)
def _patch_storage(storage):
    with patch("app.api.entries._build_storage", return_value=storage):
        yield storage


@pytest.fixture
def arq_pool():
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock()
    with patch("app.api.entries.get_arq_pool", new=AsyncMock(return_value=pool)):
        yield pool


class TestUploadEntryValidation:
    async def test_idor_404_for_foreign_note(self, user):
        session = _session(_owner(found=False))
        with pytest.raises(HTTPException) as exc:
            await upload_entry(
                uuid4(), _FakeUpload("audio/ogg", "v.ogg"), None, user, session
            )
        assert exc.value.status_code == 404
        session.add.assert_not_called()

    async def test_non_audio_rejected_415(self, user):
        session = _session(_owner(True))
        with pytest.raises(HTTPException) as exc:
            await upload_entry(
                uuid4(), _FakeUpload("application/pdf", "doc.pdf"), None, user, session
            )
        assert exc.value.status_code == 415
        session.add.assert_not_called()

    async def test_empty_file_400(self, user):
        session = _session(_owner(True))
        with pytest.raises(HTTPException) as exc:
            await upload_entry(
                uuid4(), _FakeUpload("audio/ogg", "v.ogg", data=b""), None, user, session
            )
        assert exc.value.status_code == 400

    @pytest.mark.parametrize("bad", [-5.0, float("nan"), float("inf")])
    async def test_invalid_duration_422(self, user, bad):
        session = _session(_owner(True))
        with pytest.raises(HTTPException) as exc:
            await upload_entry(
                uuid4(), _FakeUpload("audio/ogg", "v.ogg"), bad, user, session
            )
        assert exc.value.status_code == 422
        session.add.assert_not_called()

    async def test_oversized_413(self, user):
        session = _session(_owner(True))
        big = b"x" * (1024 * 1024 + 1)  # > 1 МБ
        with patch(
            "app.api.entries.settings",
            SimpleNamespace(UPLOAD_MAX_AUDIO_MB=1, UPLOAD_MAX_DOC_MB=1),
        ):
            with pytest.raises(HTTPException) as exc:
                await upload_entry(
                    uuid4(), _FakeUpload("audio/ogg", "v.ogg", data=big), None,
                    user, session,
                )
        assert exc.value.status_code == 413


class TestUploadEntryHappy:
    async def test_creates_transcribing_entry_and_enqueues(
        self, user, storage, arq_pool
    ):
        bid = uuid4()
        session = _session(_owner(True))
        result = await upload_entry(
            bid, _FakeUpload("audio/ogg", "v.ogg"), 4.5, user, session
        )

        # Запись создана в статусе transcribing с привязкой к объекту S3.
        session.add.assert_called_once()
        entry = session.add.call_args[0][0]
        assert isinstance(entry, NoteEntry)
        assert entry.kind == "user"
        assert entry.bookmark_id == bid
        assert entry.body == ""  # заполнит STT
        assert entry.entry_ai_status == "transcribing"
        assert entry.media_file_id and entry.media_file_id.startswith("uploads/")
        assert entry.duration == 4.5
        assert result is entry

        # Байты сохранены в S3, поставлен джоб распознавания.
        storage.put_bytes.assert_awaited_once()
        arq_pool.enqueue_job.assert_awaited_once()
        args, kwargs = arq_pool.enqueue_job.call_args
        assert args[0] == "process_entry_upload"
        assert args[1] == str(entry.id)
        assert args[2] == entry.media_file_id  # storage_key
