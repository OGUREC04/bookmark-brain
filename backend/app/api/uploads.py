"""Mini App media upload endpoint (3sr).

``POST /api/v1/bookmarks/upload`` — receives a voice recording or a document
from the Mini App (multipart), stores it in Object Storage, creates a draft
Bookmark, and returns immediately. The actual STT / text-extraction runs in the
``process_upload_task`` worker job; the Mini App polls ``GET /bookmarks/{id}``
and watches ``ai_status`` go ``transcribing|extracting -> pending -> completed``.

Lives in its own module (not bookmarks.py, which is already large). Type
detection and size limits are pure helpers (unit-tested in
tests/test_uploads_endpoint.py); the thin orchestration is verified live.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.bookmarks import get_arq_pool
from app.auth import get_current_user
from app.config import get_settings
from app.database import get_session
from app.models import Bookmark, User
from app.schemas import BookmarkResponse
from shared.media.extractor import detect_format
from shared.media.storage import UploadStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/bookmarks", tags=["bookmarks"])
settings = get_settings()

# Browser MediaRecorder + Telegram audio formats we route to STT.
_AUDIO_EXTS = {".ogg", ".oga", ".mp3", ".m4a", ".wav", ".webm", ".mp4", ".aac", ".flac"}

# STT (esp. async Yandex) can take minutes — the global 120s job timeout is too
# tight, so this job gets a longer per-job timeout.
_UPLOAD_JOB_TIMEOUT_SEC = 300
# Defer the job briefly so the get_session dependency commits the draft row
# before the worker reads it (mirrors create_bookmark's enqueue-then-commit).
_UPLOAD_DEFER_SEC = 3
# Caps so a hostile upload can't blow up raw_text (LLM cost / O(n²) difflib) or
# overflow the title column — the normal create path is capped by BookmarkCreate.
_MAX_CAPTION_CHARS = 50_000  # mirrors BookmarkCreate.raw_text max_length
_MAX_TITLE_CHARS = 500       # Bookmark.title is String(500)


def _resolve_kind(
    content_type: str | None, filename: str | None, explicit: str | None
) -> str | None:
    """Classify the upload as 'audio' | 'document', or None if unsupported."""
    if explicit in ("audio", "document"):
        return explicit
    if detect_format(content_type, filename) is not None:
        return "document"
    mime = (content_type or "").lower()
    suffix = Path(filename or "").suffix.lower()
    if mime.startswith(("audio/", "video/")) or suffix in _AUDIO_EXTS:
        return "audio"
    return None


def _max_bytes(kind: str, cfg) -> int:
    mb = cfg.UPLOAD_MAX_AUDIO_MB if kind == "audio" else cfg.UPLOAD_MAX_DOC_MB
    return mb * 1024 * 1024


def _storage_key(filename: str | None) -> str:
    suffix = Path(filename or "").suffix
    return f"uploads/{uuid.uuid4().hex}{suffix}"


def _build_storage() -> UploadStorage:
    return UploadStorage(
        endpoint=settings.YANDEX_S3_ENDPOINT,
        bucket=settings.YANDEX_S3_BUCKET,
        access_key=settings.YANDEX_S3_ACCESS_KEY,
        secret_key=settings.YANDEX_S3_SECRET_KEY,
    )


@router.post(
    "/upload",
    response_model=BookmarkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_media(
    file: UploadFile = File(...),
    kind: str | None = Form(default=None),
    caption: str | None = Form(default=None),
    duration: float | None = Form(default=None),
    title: str | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Bookmark:
    resolved = _resolve_kind(file.content_type, file.filename, kind)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Неподдерживаемый тип файла. Поддерживаются аудио и PDF/DOCX/TXT/MD.",
        )

    limit = _max_bytes(resolved, settings)
    # Read at most limit+1 bytes: an oversized upload is rejected without ever
    # slurping the whole file into memory (Starlette spools the rest to disk).
    data = await file.read(limit + 1)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Пустой файл."
        )
    if len(data) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Файл слишком большой (максимум {limit // (1024 * 1024)} МБ).",
        )

    # Store the bytes first; if persisting the draft fails afterwards, delete the
    # object so it doesn't orphan in the bucket.
    key = _storage_key(file.filename)
    storage = _build_storage()
    await storage.put_bytes(key, data, content_type=file.content_type)
    try:
        bookmark = Bookmark(
            user_id=current_user.id,
            raw_text=(caption or "")[:_MAX_CAPTION_CHARS],
            title=(title or file.filename or "")[:_MAX_TITLE_CHARS] or None,
            source="miniapp",
            content_type="voice" if resolved == "audio" else "document",
            ai_status="transcribing" if resolved == "audio" else "extracting",
        )
        session.add(bookmark)
        await session.flush()
        await session.refresh(bookmark, ["tags"])

        pool = await get_arq_pool()
        await pool.enqueue_job(
            "process_upload_task",
            str(bookmark.id),
            key,
            resolved,
            file.filename or key,
            file.content_type,
            duration,
            _job_timeout=_UPLOAD_JOB_TIMEOUT_SEC,
            _defer_by=_UPLOAD_DEFER_SEC,
        )
    except Exception:
        try:
            await storage.delete(key)
        except Exception as ce:  # noqa: BLE001 — best-effort orphan cleanup
            logger.warning("Upload: failed to clean orphan object %s: %s", key, ce)
        raise

    logger.info(
        "Mini App upload accepted: bookmark=%s kind=%s key=%s",
        bookmark.id, resolved, key,
    )
    return bookmark
