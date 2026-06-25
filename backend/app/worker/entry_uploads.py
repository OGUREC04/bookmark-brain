"""Worker job: распознать голосовую дописку к заметке (Notes-as-conversations B4).

Эндпоинт ``POST /bookmarks/{id}/entries/upload`` кладёт аудио в Object Storage,
создаёт запись ``note_entries`` (``entry_ai_status='transcribing'``) и ставит этот
джоб. Здесь: скачать → STT → заполнить ``body``/``transcription`` записи
(``entry_ai_status='done'``); по готовности — debounce-реиндекс заметки (B3).

НЕ запускает classify/summary заметки (Brain молчит, FR-5/NFR-1) — речь только про
текст одной записи. На уровне ЗАПИСИ, не всей заметки: статус распознавания свой
(тот же класс, что note-level upload, но другая сущность).

Best-effort: ошибка STT/транскода помечает запись ``failed`` (запись остаётся —
пользователь увидит её в ленте и сможет перезаписать). Транспорт/транскод/STT —
переиспользуем из ``worker/uploads.py`` (DRY), не дублируем.
"""
from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from shared.media.stt import STTError
from shared.media.transcode import TranscodeError

from .processing import _PROCESS_MAX_TRIES
from .uploads import _TMP_DIR, _build_storage, _safe_delete, _safe_unlink, _transcribe

logger = logging.getLogger(__name__)

_ST_TRANSCRIBING = "transcribing"
_ST_DONE = "done"
_ST_FAILED = "failed"

# Окно debounce реиндекса — совпадает с REINDEX_DEFER_SEC в app.api.entries
# (тот же _job_id-дедуп: голос-готов и параллельные текст-дописки сольются в 1 джоб).
_REINDEX_DEFER_SEC = 45


async def process_entry_upload(
    ctx: dict,
    entry_id: str,
    storage_key: str,
    filename: str,
    content_type: str | None = None,
    duration: float | None = None,
) -> None:
    storage = _build_storage()
    _TMP_DIR.mkdir(exist_ok=True)
    suffix = Path(filename).suffix or ".ogg"
    src = _TMP_DIR / f"entry-{entry_id}{suffix}"
    work_paths = [src]

    try:
        # 1. Идемпотентность: обрабатываем только запись в статусе transcribing
        #    (retry после успеха/удаления → пропустить + подчистить объект).
        bookmark_id = await _read_entry_draft(entry_id)
        if bookmark_id is None:
            await _safe_delete(storage, storage_key)
            return

        # 2. Скачать + распознать (транскод браузерного аудио → OGG внутри _transcribe).
        await storage.download_to_path(storage_key, src)
        text = await _transcribe(src, filename, duration, work_paths)

        # 3. Записать результат, затем по готовности — реиндекс заметки (B3).
        await _finalize_entry(entry_id, text)
        await _enqueue_reindex(ctx, bookmark_id)
        await _safe_delete(storage, storage_key)
    except (STTError, TranscodeError) as e:
        # Постоянная медиа-ошибка (повтор не поможет): запись → failed, остаётся в ленте.
        logger.warning("Entry upload %s failed (media): %s", entry_id, e)
        await _mark_entry_failed(entry_id)
        await _safe_delete(storage, storage_key)
    except Exception as e:  # noqa: BLE001 — неожиданное (S3/DB): дать arq повторить
        job_try = (ctx or {}).get("job_try", 1)
        if job_try < _PROCESS_MAX_TRIES:
            logger.warning(
                "Entry upload %s errored (try %s/%s) — retry: %s",
                entry_id, job_try, _PROCESS_MAX_TRIES, e,
            )
            raise
        logger.error("Entry upload %s failed after %s tries: %s", entry_id, job_try, e)
        await _mark_entry_failed(entry_id)
        await _safe_delete(storage, storage_key)
    finally:
        for p in work_paths:
            _safe_unlink(p)


async def _enqueue_reindex(ctx: dict, bookmark_id: str) -> None:
    """Best-effort debounce-реиндекс заметки (B3). Сбой не критичен — самолечится
    при следующей дописке/правке (как _schedule_reindex в API)."""
    try:
        await ctx["redis"].enqueue_job(
            "reembed_bookmark_task",
            bookmark_id,
            _job_id=f"reembed:{bookmark_id}",
            _defer_by=_REINDEX_DEFER_SEC,
        )
    except Exception as e:  # noqa: BLE001 — реиндекс best-effort
        logger.warning("entry upload: reindex enqueue failed for %s: %s", bookmark_id, e)


# ── DB helpers (короткие сессии; не держим через сетевой I/O — как worker/uploads) ──

async def _read_entry_draft(entry_id: str) -> str | None:
    """str(bookmark_id) если запись ждёт распознавания, иначе None (gone/уже done)."""
    from app.database import async_session
    from app.models import NoteEntry

    async with async_session() as session:
        entry = await session.get(NoteEntry, UUID(entry_id))
        # Пропускаем если запись пропала / уже распознана / удалена пользователем
        # до старта джоба (soft-delete) — не тратим STT и не дёргаем зря re-index.
        if (
            entry is None
            or entry.is_deleted
            or entry.entry_ai_status != _ST_TRANSCRIBING
        ):
            return None
        return str(entry.bookmark_id)


async def _finalize_entry(entry_id: str, text: str) -> None:
    """Записать распознанный текст в дописку и пометить done."""
    from app.database import async_session
    from app.models import NoteEntry

    clean = (text or "").strip()
    async with async_session() as session:
        entry = await session.get(NoteEntry, UUID(entry_id))
        if entry is None:
            return
        entry.body = clean
        entry.transcription = clean or None
        entry.entry_ai_status = _ST_DONE
        await session.commit()


async def _mark_entry_failed(entry_id: str) -> None:
    """Пометить дописку failed (тело пустое — запись остаётся, можно перезаписать)."""
    from app.database import async_session
    from app.models import NoteEntry

    async with async_session() as session:
        entry = await session.get(NoteEntry, UUID(entry_id))
        if entry is None:
            return
        entry.entry_ai_status = _ST_FAILED
        await session.commit()
