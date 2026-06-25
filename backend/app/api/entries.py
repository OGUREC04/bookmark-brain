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

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_session
from app.models import Bookmark, NoteEntry, User
from app.schemas import EntryCreate, EntryResponse, EntryUpdate, ThreadResponse

router = APIRouter(prefix="/api/v1", tags=["note-entries"])

# Лимит длины тела (граница против DoS) — в EntryCreate/EntryUpdate (Field max_length),
# единый источник; на API-границе Pydantic отдаёт 422 до эндпоинта.


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
