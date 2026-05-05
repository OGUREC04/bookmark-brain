import logging
from datetime import datetime, timezone
from uuid import UUID

logger = logging.getLogger(__name__)

from arq.connections import ArqRedis, create_pool
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_session
from app.models import Bookmark, BookmarkTag, Tag, User
from pydantic import BaseModel

from app.schemas import (
    BookmarkCreate,
    BookmarkListResponse,
    BookmarkResponse,
    BookmarkUpdate,
)
from app.services.task_list_editor import NLEditError, apply_nl_edit
from app.worker import WorkerSettings


class NLEditRequest(BaseModel):
    text: str

router = APIRouter(prefix="/api/v1/bookmarks", tags=["bookmarks"])
settings = get_settings()

_arq_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(WorkerSettings.redis_settings)
    return _arq_pool


@router.post("/", response_model=BookmarkResponse, status_code=status.HTTP_201_CREATED)
async def create_bookmark(
    data: BookmarkCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    bookmark = Bookmark(
        user_id=current_user.id,
        raw_text=data.raw_text,
        url=data.url,
        title=data.title,
        source=data.source,
        source_message_id=data.source_message_id,
        source_date=data.source_date,
        content_type=data.content_type,
        media_file_id=data.media_file_id,
        transcription=data.transcription,
        media_duration=data.media_duration,
        document_page_count=data.document_page_count,
    )
    session.add(bookmark)
    await session.flush()

    # Phase 3D: auto-tag #voice for voice messages
    if data.voice_tag:
        await _ensure_voice_tag(session, bookmark)

    # Ставим задачу на AI-обработку
    pool = await get_arq_pool()
    await pool.enqueue_job(
        "process_bookmark_task",
        str(bookmark.id),
        data.notify_chat_id,
        data.notify_message_id,
        data.silent,
    )

    # Подгружаем теги
    await session.refresh(bookmark, ["tags"])
    return bookmark


async def _ensure_voice_tag(session: AsyncSession, bookmark: Bookmark) -> None:
    """Create or find #voice tag and link it to the bookmark."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # Upsert tag
    stmt = (
        pg_insert(Tag)
        .values(user_id=bookmark.user_id, name="voice")
        .on_conflict_do_nothing(index_elements=["user_id", "name"])
        .returning(Tag.id)
    )
    result = await session.execute(stmt)
    row = result.first()
    if row:
        tag_id = row[0]
    else:
        # Already exists — fetch it
        tag_result = await session.execute(
            select(Tag.id).where(Tag.user_id == bookmark.user_id, Tag.name == "voice")
        )
        tag_id = tag_result.scalar_one()

    # Link
    link_stmt = (
        pg_insert(BookmarkTag)
        .values(bookmark_id=bookmark.id, tag_id=tag_id)
        .on_conflict_do_nothing()
    )
    await session.execute(link_stmt)
    await session.flush()


@router.get("/", response_model=BookmarkListResponse)
async def list_bookmarks(
    page: int = 1,
    per_page: int = 20,
    category: str | None = None,
    is_favorite: bool | None = None,
    is_archived: bool | None = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    stmt = (
        select(Bookmark)
        .options(selectinload(Bookmark.tags))
        .where(Bookmark.user_id == current_user.id)
    )
    count_stmt = select(func.count(Bookmark.id)).where(
        Bookmark.user_id == current_user.id
    )

    if category:
        stmt = stmt.where(Bookmark.category == category)
        count_stmt = count_stmt.where(Bookmark.category == category)
    if is_favorite is not None:
        stmt = stmt.where(Bookmark.is_favorite == is_favorite)
        count_stmt = count_stmt.where(Bookmark.is_favorite == is_favorite)
    if is_archived is not None:
        stmt = stmt.where(Bookmark.is_archived == is_archived)
        count_stmt = count_stmt.where(Bookmark.is_archived == is_archived)

    stmt = stmt.order_by(Bookmark.created_at.desc())
    stmt = stmt.offset((page - 1) * per_page).limit(per_page)

    result = await session.execute(stmt)
    bookmarks = result.scalars().all()

    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0

    return BookmarkListResponse(
        items=bookmarks, total=total, page=page, per_page=per_page
    )


@router.get("/random", response_model=BookmarkResponse | None)
async def random_bookmark(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Bookmark)
        .options(selectinload(Bookmark.tags))
        .where(Bookmark.user_id == current_user.id)
        .order_by(func.random())
        .limit(1)
    )
    bookmark = result.scalar_one_or_none()
    if bookmark is None:
        raise HTTPException(status_code=404, detail="No bookmarks found")
    return bookmark


@router.get("/{bookmark_id}", response_model=BookmarkResponse)
async def get_bookmark(
    bookmark_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Bookmark)
        .options(selectinload(Bookmark.tags))
        .where(Bookmark.id == bookmark_id, Bookmark.user_id == current_user.id)
    )
    bookmark = result.scalar_one_or_none()

    if bookmark is None:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    bookmark.last_accessed = datetime.now(timezone.utc)
    return bookmark


@router.patch("/{bookmark_id}", response_model=BookmarkResponse)
async def update_bookmark(
    bookmark_id: UUID,
    data: BookmarkUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Bookmark)
        .options(selectinload(Bookmark.tags))
        .where(Bookmark.id == bookmark_id, Bookmark.user_id == current_user.id)
    )
    bookmark = result.scalar_one_or_none()

    if bookmark is None:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(bookmark, field, value)

    return bookmark


@router.delete("/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bookmark(
    bookmark_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Bookmark).where(Bookmark.id == bookmark_id, Bookmark.user_id == current_user.id)
    )
    bookmark = result.scalar_one_or_none()

    if bookmark is None:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    await session.delete(bookmark)


@router.post("/{bookmark_id}/reprocess", response_model=BookmarkResponse)
async def reprocess_bookmark(
    bookmark_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Bookmark)
        .options(selectinload(Bookmark.tags))
        .where(Bookmark.id == bookmark_id, Bookmark.user_id == current_user.id)
    )
    bookmark = result.scalar_one_or_none()

    if bookmark is None:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    bookmark.ai_status = "pending"
    bookmark.ai_error = None
    bookmark.retry_count = 0
    await session.flush()

    pool = await get_arq_pool()
    await pool.enqueue_job("process_bookmark_task", str(bookmark.id))

    return bookmark


@router.post("/{bookmark_id}/nl-edit", response_model=BookmarkResponse)
async def nl_edit_bookmark(
    bookmark_id: UUID,
    data: NLEditRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """NL-редактирование task_list через свободную фразу.

    Принимает `{"text": "..."}` — фразу на русском ("добавь молоко",
    "удали 2", "3 до пятницы"). LLM применяет изменения и возвращает
    обновлённый bookmark.
    """
    result = await session.execute(
        select(Bookmark)
        .options(selectinload(Bookmark.tags))
        .where(Bookmark.id == bookmark_id, Bookmark.user_id == current_user.id)
    )
    bookmark = result.scalar_one_or_none()

    if bookmark is None:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    structured = bookmark.structured_data
    if not structured or structured.get("type") != "task_list":
        raise HTTPException(
            status_code=400,
            detail="Bookmark is not a task_list",
        )

    try:
        new_structured = await apply_nl_edit(structured, data.text)
    except NLEditError as e:
        raise HTTPException(status_code=422, detail=f"NL-edit failed: {e}")

    bookmark.structured_data = new_structured
    return bookmark


@router.post("/{new_id}/merge-into/{old_id}", response_model=BookmarkResponse)
async def merge_task_lists(
    new_id: UUID,
    old_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Объединить новый task_list в существующий.

    Программный merge: добавляет задачи из нового списка в старый,
    пропуская дубликаты (по нормализованному тексту).
    Удаляет новый bookmark. Возвращает обновлённый старый.
    """
    new_result = await session.execute(
        select(Bookmark)
        .where(Bookmark.id == new_id, Bookmark.user_id == current_user.id)
    )
    new_bm = new_result.scalar_one_or_none()

    old_result = await session.execute(
        select(Bookmark)
        .options(selectinload(Bookmark.tags))
        .where(Bookmark.id == old_id, Bookmark.user_id == current_user.id)
    )
    old_bm = old_result.scalar_one_or_none()

    if not new_bm or not old_bm:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    new_structured = new_bm.structured_data
    old_structured = old_bm.structured_data

    if (
        not new_structured or new_structured.get("type") != "task_list"
        or not old_structured or old_structured.get("type") != "task_list"
    ):
        raise HTTPException(status_code=400, detail="Both bookmarks must be task_lists")

    new_tasks = new_structured.get("tasks", [])
    if not new_tasks:
        raise HTTPException(status_code=400, detail="New list has no tasks")

    # Программный merge с дедупликацией по нормализованному тексту
    old_tasks = old_structured.get("tasks", [])
    existing_texts = {
        t.get("text", "").strip().lower() for t in old_tasks
    }

    added = 0
    for task in new_tasks:
        normalized = task.get("text", "").strip().lower()
        if normalized and normalized not in existing_texts:
            old_tasks.append({
                "text": task.get("text", "").strip(),
                "done": False,
                "deadline": task.get("deadline"),
            })
            existing_texts.add(normalized)
            added += 1

    old_structured["tasks"] = old_tasks
    old_bm.structured_data = old_structured

    # Удаляем новый bookmark
    await session.delete(new_bm)

    logger.info(f"Merged {added} tasks from {new_id} into {old_id}")
    return old_bm


@router.post("/reprocess-all")
async def reprocess_all_bookmarks(
    only_missing_phase1: bool = True,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Батч-переобработка закладок пользователя.

    По умолчанию (only_missing_phase1=True) переобрабатывает только те,
    у которых не заполнены Phase 1 поля (takeaway / key_ideas / full_text).
    Если only_missing_phase1=False — переобрабатывает ВСЕ закладки юзера.

    Возвращает {"enqueued": N, "total": M}.
    """
    stmt = select(Bookmark.id).where(Bookmark.user_id == current_user.id)

    if only_missing_phase1:
        # Нет takeaway ИЛИ нет key_ideas — считаем что Phase 1 не применён
        stmt = stmt.where(
            (Bookmark.takeaway.is_(None)) | (Bookmark.key_ideas.is_(None))
        )

    result = await session.execute(stmt)
    ids = [row[0] for row in result.all()]

    if not ids:
        return {"enqueued": 0, "total": 0}

    # Сбрасываем статус всем сразу одним UPDATE
    await session.execute(
        update(Bookmark)
        .where(Bookmark.id.in_(ids))
        .values(ai_status="pending", ai_error=None, retry_count=0)
    )
    await session.commit()

    # Enqueue батчем
    pool = await get_arq_pool()
    for bid in ids:
        await pool.enqueue_job("process_bookmark_task", str(bid))

    return {"enqueued": len(ids), "total": len(ids)}
