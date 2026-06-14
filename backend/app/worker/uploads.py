"""Worker job: process a Mini App media upload (3sr).

The upload endpoint stores the file in Object Storage and creates a draft
Bookmark (``ai_status`` ``transcribing`` / ``extracting``), then enqueues this
job. Here we download the file, run STT (audio) or text extraction (documents),
fill the draft, and hand it to the NORMAL AI pipeline (``process_bookmark_task``)
— we do not duplicate embedding / classification / connections.

Best-effort: a recognition/extraction failure marks the bookmark
``ai_status='failed'`` + ``ai_error``; the Mini App learns of it by polling
``GET /bookmarks/{id}`` (the upload endpoint already returned 201).
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from uuid import UUID

from app.config import get_settings
from shared.media.extractor import ExtractError, detect_format, extract_text
from shared.media.storage import UploadStorage
from shared.media.stt import STTError, create_stt_service
from shared.media.transcode import (
    TranscodeError,
    needs_transcode,
    transcode_to_ogg_opus,
)

from .processing import _PROCESS_MAX_TRIES

logger = logging.getLogger(__name__)

_settings = get_settings()

# Draft statuses the upload endpoint sets — only these are ours to process.
_ST_TRANSCRIBING = "transcribing"
_ST_EXTRACTING = "extracting"
_ACTIVE_DRAFT = (_ST_TRANSCRIBING, _ST_EXTRACTING)

_TMP_DIR = Path(tempfile.gettempdir()) / "bookmark-brain-uploads"


# Built lazily (and overridable in tests) so the job stays unit-testable
# without live S3 / STT credentials.
def _build_storage() -> UploadStorage:
    return UploadStorage(
        endpoint=_settings.YANDEX_S3_ENDPOINT,
        bucket=_settings.YANDEX_S3_BUCKET,
        access_key=_settings.YANDEX_S3_ACCESS_KEY,
        secret_key=_settings.YANDEX_S3_SECRET_KEY,
    )


def _build_stt():
    return create_stt_service(
        _settings.STT_PROVIDER,
        whisper_api_key=_settings.WHISPER_API_KEY,
        yandex_api_key=_settings.YANDEX_CLOUD_API_KEY,
        yandex_folder_id=_settings.YANDEX_CLOUD_FOLDER_ID,
        yandex_s3_endpoint=_settings.YANDEX_S3_ENDPOINT,
        yandex_s3_bucket=_settings.YANDEX_S3_BUCKET,
        yandex_s3_access_key=_settings.YANDEX_S3_ACCESS_KEY,
        yandex_s3_secret_key=_settings.YANDEX_S3_SECRET_KEY,
    )


async def process_upload_task(
    ctx: dict,
    bookmark_id: str,
    storage_key: str,
    kind: str,
    filename: str,
    content_type: str | None = None,
    duration: float | None = None,
) -> None:
    storage = _build_storage()
    _TMP_DIR.mkdir(exist_ok=True)
    suffix = Path(filename).suffix or (".ogg" if kind == "audio" else "")
    src = _TMP_DIR / f"{bookmark_id}{suffix}"
    work_paths = [src]

    try:
        # 1. read the draft: caption + idempotency. Don't hold the DB session
        #    across the (slow) STT/extract below.
        caption = await _read_draft(bookmark_id)
        if caption is None:
            # missing bookmark or already processed — drop any orphan object.
            await _safe_delete(storage, storage_key)
            return

        # 2. download + recognise / extract (no DB session held)
        await storage.download_to_path(storage_key, src)
        if kind == "audio":
            text: str = await _transcribe(src, filename, duration, work_paths)
            transcription: str | None = text
            page_count: int | None = None
        else:
            # Use the same signal the endpoint used (MIME + filename), so a
            # document with a valid MIME but no extension isn't dropped here.
            fmt = detect_format(content_type, filename)
            if fmt is None:
                raise ExtractError(f"Неподдерживаемый формат файла: {filename}")
            result = await extract_text(src, fmt)
            text, transcription, page_count = result.text, None, result.page_count

        final_text = f"{caption}\n\n{text}".strip() if caption else text

        # 3. persist the result AND enqueue the pipeline in one transaction —
        # commit only AFTER enqueue succeeds (see _finalize_and_enqueue).
        await _finalize_and_enqueue(
            ctx, bookmark_id, final_text, transcription, page_count
        )
        await _safe_delete(storage, storage_key)  # success — object no longer needed
    except (STTError, ExtractError, TranscodeError) as e:
        # Permanent media error (unrecognisable / corrupt file) — retry won't help.
        logger.warning("Upload %s failed (media): %s", bookmark_id, e)
        await _mark_failed(bookmark_id, str(e))
        await _safe_delete(storage, storage_key)
    except Exception as e:  # noqa: BLE001 — unexpected (S3 / DB / etc.)
        # Possibly transient: let arq retry, KEEPING the S3 object so the next
        # attempt can re-download it. On the LAST try, mark the draft failed so
        # it doesn't stay stuck in transcribing/extracting forever (mirrors the
        # final-try safety-net in process_bookmark_task) and drop the object.
        job_try = (ctx or {}).get("job_try", 1)
        if job_try < _PROCESS_MAX_TRIES:
            logger.warning(
                "Upload %s errored (try %s/%s) — retrying: %s",
                bookmark_id, job_try, _PROCESS_MAX_TRIES, e,
            )
            raise
        logger.error("Upload %s failed after %s tries: %s", bookmark_id, job_try, e)
        await _mark_failed(bookmark_id, f"Не удалось обработать загрузку: {e}")
        await _safe_delete(storage, storage_key)
    finally:
        # Temp files are per-attempt — always clean. The S3 object is cleaned
        # only on terminal outcomes above (kept across retries).
        for p in work_paths:
            _safe_unlink(p)


async def _transcribe(
    src: Path, filename: str, duration: float | None, work_paths: list[Path]
) -> str:
    """Transcode browser audio to OGG Opus if needed, then run STT."""
    work = src
    if needs_transcode(filename):
        work = src.with_suffix(".ogg")
        work_paths.append(work)
        await transcode_to_ogg_opus(src, work)
    return await _build_stt().transcribe(work, duration=duration)


# ── DB helpers (short-lived sessions; never held across network I/O) ─────────

async def _read_draft(bookmark_id: str) -> str | None:
    """Return the draft's caption (raw_text, possibly ""), or None to skip.

    None means: bookmark gone, or already past the draft stage (idempotent —
    an arq retry after a successful run must not reprocess).
    """
    from app.database import async_session
    from app.models import Bookmark

    async with async_session() as session:
        bm = await session.get(Bookmark, UUID(bookmark_id))
        if bm is None or bm.ai_status not in _ACTIVE_DRAFT:
            return None
        return bm.raw_text or ""


async def _finalize_and_enqueue(
    ctx: dict,
    bookmark_id: str,
    text: str,
    transcription: str | None,
    page_count: int | None,
) -> None:
    """Write recognised text, set 'pending', enqueue the pipeline, THEN commit.

    Enqueue happens BEFORE commit so a failed enqueue rolls the row back to its
    draft status (transcribing/extracting) — the arq retry of this job then
    re-processes it, instead of stranding it in 'pending' with the AI pipeline
    never started (Redis blip between commit and enqueue would otherwise lose it
    silently).
    """
    from app.database import async_session
    from app.models import Bookmark

    async with async_session() as session:
        bm = await session.get(Bookmark, UUID(bookmark_id))
        if bm is None:
            return
        bm.raw_text = text
        bm.transcription = transcription
        bm.document_page_count = page_count
        bm.ai_status = "pending"
        await ctx["redis"].enqueue_job(
            "process_bookmark_task", bookmark_id, None, None, False
        )
        await session.commit()


async def _mark_failed(bookmark_id: str, error: str) -> None:
    from app.database import async_session
    from app.models import Bookmark

    async with async_session() as session:
        bm = await session.get(Bookmark, UUID(bookmark_id))
        if bm is None:
            return
        bm.ai_status = "failed"
        bm.ai_error = error[:500]
        await session.commit()


async def _safe_delete(storage: UploadStorage, key: str) -> None:
    """Best-effort removal of the uploaded object (called only on terminal paths)."""
    try:
        await storage.delete(key)
    except Exception as e:  # noqa: BLE001 — orphan cleanup must never break the job
        logger.warning("Upload: storage cleanup failed for %s: %s", key, e)


def _safe_unlink(p: Path) -> None:
    try:
        if p.exists():
            p.unlink()
    except OSError:
        pass
