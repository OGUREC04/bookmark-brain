"""Note entries API — дописки в «лог-переписку» заметки (Notes as Conversations).

Заметка (`bookmarks.raw_text`) = «запись #0»/шапка; дописки — строки `note_entries`.
В MVP Brain молчит (kind всегда 'user'). Индексацию дописок в поиск/связи делает
ОТДЕЛЬНЫЙ classify-free reembed-джоб (B3) — здесь только CRUD, без AI-побочек.

IDOR: заметка проверяется на принадлежность current_user (404 иначе).

Endpoints:
- GET    /api/v1/bookmarks/{id}/thread          — дописки (неудалённые, по времени)
- POST   /api/v1/bookmarks/{id}/entries         — добавить дописку
- PATCH  /api/v1/bookmarks/{id}/entries/{eid}   — править дописку (edited_at)
- DELETE /api/v1/bookmarks/{id}/entries/{eid}   — мягко удалить (is_deleted)
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.bookmarks import get_arq_pool

# Переиспользуем тип/размер-хелперы и сборку S3-клиента из note-level upload (DRY,
# покрыты в test_uploads_endpoint) — голос-дописка идёт тем же транспортом, иным путём.
from app.api.uploads import _build_storage, _max_bytes, _resolve_kind, _storage_key
from app.auth import get_current_user
from app.config import get_settings
from app.database import get_session
from app.models import Bookmark, NoteEntry, User
from app.schemas import EntryCreate, EntryResponse, EntryUpdate, ThreadResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["note-entries"])
settings = get_settings()

# Лимит длины тела (граница против DoS) — в EntryCreate/EntryUpdate (Field max_length),
# единый источник; на API-границе Pydantic отдаёт 422 до эндпоинта.

# Debounce re-index: дописки копятся, переэмбеддинг/связи/FTS пересчитываются
# отложенно. arq дедуплицирует по _job_id (burst дописок в окне → 1 джоб), NFR-1.
REINDEX_DEFER_SEC = 45

# Голос-дописку слегка отложим, чтобы get_session закоммитил запись до того, как
# воркер её прочитает (как в note-level upload). Реиндекс ставит уже воркер по готовности.
_ENTRY_UPLOAD_DEFER_SEC = 3

# Здравый потолок длительности (метаданные приходят от клиента): отсекаем мусор
# (NaN/inf/<0) и абсурд. Реальную длину уже ограничивает лимит размера файла.
_MAX_ENTRY_DURATION_SEC = 6 * 60 * 60


async def _schedule_reindex(bookmark_id: UUID) -> None:
    """Отложенно (debounce) пере-индексировать заметку под её лог (reembed_bookmark_task).

    Best-effort: сбой постановки джоба не должен ронять запрос (дописка уже сохранена).
    arq дедуплицирует по _job_id — burst дописок в окне даёт 1 джоб (NFR-1).
    """
    try:
        pool = await get_arq_pool()
        await pool.enqueue_job(
            "reembed_bookmark_task",
            str(bookmark_id),
            _job_id=f"reembed:{bookmark_id}",
            _defer_by=REINDEX_DEFER_SEC,
        )
    except Exception as e:  # noqa: BLE001 — реиндекс best-effort
        logger.warning("reindex enqueue failed for %s: %s", bookmark_id, e)


async def _assert_owner(session: AsyncSession, bookmark_id: UUID, user_id: UUID) -> None:
    """IDOR: заметка должна принадлежать текущему пользователю (404 иначе)."""
    owner = await session.execute(
        select(Bookmark.id).where(
            Bookmark.id == bookmark_id,
            Bookmark.user_id == user_id,
        )
    )
    if owner.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Bookmark not found")


async def _load_entry(
    session: AsyncSession, bookmark_id: UUID, entry_id: UUID
) -> NoteEntry:
    """Загрузить неудалённую дописку заметки или 404."""
    row = await session.execute(
        select(NoteEntry).where(
            NoteEntry.id == entry_id,
            NoteEntry.bookmark_id == bookmark_id,
            NoteEntry.is_deleted.is_(False),
        )
    )
    entry = row.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@router.get("/bookmarks/{bookmark_id}/thread", response_model=ThreadResponse)
async def get_thread(
    bookmark_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ThreadResponse:
    """Лента дописок — неудалённые, по времени (старое → новое). Без пагинации (MVP)."""
    await _assert_owner(session, bookmark_id, current_user.id)
    rows = await session.execute(
        select(NoteEntry)
        .where(
            NoteEntry.bookmark_id == bookmark_id,
            NoteEntry.is_deleted.is_(False),
        )
        .order_by(NoteEntry.created_at)
    )
    items = [EntryResponse.model_validate(r) for r in rows.scalars().all()]
    return ThreadResponse(entries=items, total=len(items))


@router.post(
    "/bookmarks/{bookmark_id}/entries",
    response_model=EntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_entry(
    bookmark_id: UUID,
    body: EntryCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> NoteEntry:
    """Добавить дописку (текст, kind='user'). Индексацию в поиск/связи делает B3."""
    await _assert_owner(session, bookmark_id, current_user.id)
    text = body.body.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Запись пустая")
    entry = NoteEntry(bookmark_id=bookmark_id, kind="user", body=text)
    session.add(entry)
    await session.flush()
    await session.refresh(entry)
    await _schedule_reindex(bookmark_id)
    return entry


@router.patch(
    "/bookmarks/{bookmark_id}/entries/{entry_id}", response_model=EntryResponse
)
async def update_entry(
    bookmark_id: UUID,
    entry_id: UUID,
    body: EntryUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> NoteEntry:
    """Править дописку: ставит edited_at. НЕ дёргает reprocess всей заметки (B3 отдельно)."""
    await _assert_owner(session, bookmark_id, current_user.id)
    entry = await _load_entry(session, bookmark_id, entry_id)
    text = body.body.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Запись пустая")
    entry.body = text
    entry.edited_at = datetime.now(timezone.utc)
    await session.flush()
    await session.refresh(entry)
    await _schedule_reindex(bookmark_id)
    return entry


@router.delete(
    "/bookmarks/{bookmark_id}/entries/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_entry(
    bookmark_id: UUID,
    entry_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Мягкое удаление (is_deleted=true) — не рвёт будущие ссылки ответов Brain на запись."""
    await _assert_owner(session, bookmark_id, current_user.id)
    entry = await _load_entry(session, bookmark_id, entry_id)
    entry.is_deleted = True
    await session.flush()
    await _schedule_reindex(bookmark_id)


@router.post(
    "/bookmarks/{bookmark_id}/entries/upload",
    response_model=EntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_entry(
    bookmark_id: UUID,
    file: UploadFile = File(...),
    duration: float | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> NoteEntry:
    """Голосовая дописка: принять аудио → создать запись 'transcribing', STT — в воркере.

    Только аудио (документ-дописки вне MVP). Файл → S3, запись с media_file_id и
    entry_ai_status='transcribing'; распознавание и re-index делает process_entry_upload
    (B4). До готовности body='' — фронт показывает запись по entry_ai_status (DEC-11).
    """
    await _assert_owner(session, bookmark_id, current_user.id)

    if _resolve_kind(file.content_type, file.filename, None) != "audio":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Голосовая дописка принимает только аудио.",
        )

    if duration is not None and not (
        math.isfinite(duration) and 0 <= duration <= _MAX_ENTRY_DURATION_SEC
    ):
        raise HTTPException(status_code=422, detail="Недопустимая длительность аудио.")

    limit = _max_bytes("audio", settings)
    # Читаем не больше limit+1 байт: пере-размерный аплоад отбрасываем, не утаскивая
    # весь файл в память (Starlette спулит остаток на диск).
    data = await file.read(limit + 1)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пустой файл.")
    if len(data) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Файл слишком большой (максимум {limit // (1024 * 1024)} МБ).",
        )

    # Сохраняем байты; если запись черновика упадёт — удаляем объект, чтобы не осиротел.
    key = _storage_key(file.filename)
    # В job-арг кладём только basename — клиентский filename не должен влиять на
    # путь temp-файла воркера (defense-in-depth; воркер берёт лишь суффикс).
    safe_name = Path(file.filename or key).name
    storage = _build_storage()
    await storage.put_bytes(key, data, content_type=file.content_type)
    try:
        entry = NoteEntry(
            bookmark_id=bookmark_id,
            kind="user",
            body="",  # заполнит STT; до готовности — пустой плейсхолдер (entry_ai_status)
            media_file_id=key,
            duration=duration,
            entry_ai_status="transcribing",
        )
        session.add(entry)
        await session.flush()
        await session.refresh(entry)
        pool = await get_arq_pool()
        await pool.enqueue_job(
            "process_entry_upload",
            str(entry.id),
            key,
            safe_name,
            file.content_type,
            duration,
            _defer_by=_ENTRY_UPLOAD_DEFER_SEC,
        )
    except Exception:
        try:
            await storage.delete(key)
        except Exception as ce:  # noqa: BLE001 — best-effort очистка осиротевшего объекта
            logger.warning("Entry upload: orphan cleanup failed for %s: %s", key, ce)
        raise
    return entry
