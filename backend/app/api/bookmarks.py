import difflib
import logging
from datetime import datetime, timezone
from uuid import UUID

logger = logging.getLogger(__name__)

from arq.connections import ArqRedis, create_pool
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_session
from app.models import Bookmark, BookmarkTag, Tag, User
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


class StructureAsListRequest(BaseModel):
    # text=None → структурируем из raw_text закладки; иначе из явных пунктов.
    text: str | None = None
    # allow_single: юзер прислал пункты вручную → принимаем даже 1 пункт.
    allow_single: bool = False


class StructureAsListResponse(BaseModel):
    structured: bool
    reason: str = "ok"  # ok | empty | single_phrase
    tasks_count: int = 0


# Тикет 0rn: порог «материальной» правки текста. Если похожесть старого и
# нового текста ниже порога — считаем, что смысл мог поменяться, и запускаем
# полную переобработку (embedding + summary/title/теги). Выше порога (пара
# слов) — просто сохраняем, без холостой LLM-перегенерации.
# Похожесть difflib адаптивна к длине: в коротких заметках малая правка даёт
# большое падение ratio (сработает), в длинных — нет.
_REPROCESS_TEXT_SIMILARITY_THRESHOLD = 0.85


def _text_changed_materially(old: str, new: str) -> bool:
    """True, если правка достаточно крупная, чтобы оправдать переобработку."""
    if not old:
        return True
    # Быстрый путь: заметная разница длины → точно материально, без difflib.
    longer = max(len(old), len(new))
    if longer and abs(len(old) - len(new)) / longer > 0.3:
        return True
    # difflib O(n*m) и СИНХРОННЫЙ — на длинных строках блокирует event loop.
    # Ограничиваем вход (схема и так капит raw_text 50k); для эвристики
    # «сменился ли смысл» сравнения префикса достаточно.
    a, b = old[:4000], new[:4000]
    return (
        difflib.SequenceMatcher(None, a, b).ratio()
        < _REPROCESS_TEXT_SIMILARITY_THRESHOLD
    )


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
    """Создание закладки.

    ИДЕМПОТЕНТНОСТЬ: при попытке создать дубликат по
    (user_id, source, source_message_id) — возвращаем существующую закладку
    вместо 500. См. docs/bugs/2026-05-11-task-list-duplicates-and-merge-ui.md.
    """
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
    try:
        await session.flush()
    except IntegrityError as e:
        # Дубликат по idx_bookmarks_source_dedup: возвращаем существующий.
        # Унифицированный признак — наличие имени индекса в orig (asyncpg)
        # или 23505 (unique_violation) код Postgres.
        err_str = str(getattr(e, "orig", e)).lower()
        is_source_dedup = (
            "idx_bookmarks_source_dedup" in err_str
            or "source_message_id" in err_str
        )
        if not is_source_dedup or data.source_message_id is None:
            raise  # другой constraint — не наш кейс

        await session.rollback()
        # Возвращаем существующий bookmark
        existing = await session.execute(
            select(Bookmark)
            .options(selectinload(Bookmark.tags))
            .where(
                Bookmark.user_id == current_user.id,
                Bookmark.source == data.source,
                Bookmark.source_message_id == data.source_message_id,
            )
        )
        existing_bm = existing.scalar_one_or_none()
        if existing_bm is None:
            # Гонка: дубликат был, но к моменту SELECT удалён. Bot ретраит.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Concurrent duplicate detected, please retry",
            )
        logger.warning(
            f"Duplicate POST bookmark: returned existing {existing_bm.id} "
            f"for (user={current_user.id}, source={data.source}, "
            f"source_message_id={data.source_message_id})"
        )
        return existing_bm

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
    item_type: str | None = None,  # B2 (2026-05-15): фильтр для Mini App чипов
    structured_type: str | None = None,  # фильтр по structured_data.type (напр. task_list) — /lists
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
    if item_type is not None:
        stmt = stmt.where(Bookmark.item_type == item_type)
        count_stmt = count_stmt.where(Bookmark.item_type == item_type)
    if structured_type is not None:
        # JSONB: structured_data->>'type' == structured_type (idx-free,
        # объём на юзера небольшой). Используется /lists (task_list).
        type_match = Bookmark.structured_data["type"].astext == structured_type
        stmt = stmt.where(type_match)
        count_stmt = count_stmt.where(type_match)

    stmt = stmt.order_by(Bookmark.created_at.desc())
    stmt = stmt.offset((page - 1) * per_page).limit(per_page)

    result = await session.execute(stmt)
    bookmarks = result.scalars().all()

    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0

    return BookmarkListResponse(
        items=bookmarks, total=total, page=page, per_page=per_page
    )


@router.post("/archive-all-task-lists")
async def archive_all_task_lists(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Bulk-архивирование всех неархивных task_list'ов юзера (/clearlists).

    Обратимо: ставит is_archived=true, не удаляет записи. Списки исчезают
    из /lists и поиска, но остаются в БД. Возвращает {"archived": N}.
    """
    stmt = (
        update(Bookmark)
        .where(
            Bookmark.user_id == current_user.id,
            Bookmark.is_archived == False,  # noqa: E712 — SQL boolean comparison
            Bookmark.structured_data["type"].astext == "task_list",
        )
        .values(is_archived=True)
    )
    result = await session.execute(stmt)
    await session.flush()
    return {"archived": result.rowcount}


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

    # Тикет 0rn: правка тела текста. Валидируем пусто + триммим ДО присваивания.
    old_raw_text = None
    if "raw_text" in update_data:
        new_raw = (update_data["raw_text"] or "").strip()
        if not new_raw:
            raise HTTPException(status_code=422, detail="raw_text must not be empty")
        if new_raw == bookmark.raw_text:
            # No-op: текст не изменился → не пишем и не дёргаем переобработку.
            del update_data["raw_text"]
        else:
            update_data["raw_text"] = new_raw
            old_raw_text = bookmark.raw_text  # снимок ДО setattr для дифф-порога

    # Снимок structured_data ДО присваивания — нужен для cascade-диффа.
    old_structured = (
        bookmark.structured_data if "structured_data" in update_data else None
    )

    for field, value in update_data.items():
        setattr(bookmark, field, value)

    # Cascade на reminder'ы task_list при изменении structured_data (Mini App
    # редактирует дедлайны/пункты). apply_cascade — единый источник правды для
    # create/reschedule/cancel; PATCH теперь тоже его триггерит, не только
    # nl-edit. Best-effort: падение каскада не валит основной апдейт.
    if "structured_data" in update_data:
        try:
            from app.services.reminder_cascade import (
                apply_cascade,
                cascade_signature,
            )
            old_snapshot = (
                dict(old_structured) if isinstance(old_structured, dict) else None
            )
            new_structured = bookmark.structured_data
            # Дешёвый guard: если набор (текст, дедлайн) не изменился — каскад
            # пропускаем (напр. переключили только галочку done).
            if cascade_signature(old_snapshot) != cascade_signature(new_structured):
                await apply_cascade(
                    session,
                    bookmark_id=bookmark.id,
                    user_id=current_user.id,
                    old_structured=old_snapshot,
                    new_structured=new_structured,
                    user_tz=current_user.timezone or "Europe/Moscow",
                )
        except Exception as e:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "reminder cascade failed on PATCH for bookmark %s: %s",
                bookmark.id, e,
            )

    # Тикет 0rn: правка raw_text устаревает embedding + AI-поля. При
    # ЗНАЧИМОЙ правке (мог поменяться смысл) — полная фоновая переобработка;
    # при мелкой (пара слов) — просто сохраняем. ai_status честно отражает
    # процесс: pending → фронт показывает «Brain переосмысливает…».
    if "raw_text" in update_data and _text_changed_materially(
        old_raw_text or "", bookmark.raw_text
    ):
        bookmark.ai_status = "pending"
        bookmark.ai_error = None
        bookmark.retry_count = 0
        await session.flush()
        # flush ставит server-onupdate `updated_at=now()` и ЭКСПАЙРИТ атрибут;
        # без refresh обращение к нему при сериализации BookmarkResponse уходит
        # в ленивую IO вне greenlet → MissingGreenlet → 500. Рефрешим точечно,
        # чтобы НЕ заэкспайрить selectinload(tags) (иначе второй MissingGreenlet).
        await session.refresh(bookmark, attribute_names=["updated_at"])
        pool = await get_arq_pool()
        await pool.enqueue_job("process_bookmark_task", str(bookmark.id))

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

    # Phase 2.6 T9: cascade на reminder'ы task_list'а.
    # Best-effort — если падает, NL-edit всё равно применяется.
    try:
        from app.services.reminder_cascade import apply_cascade
        # Снимок ДО присваивания new_structured (иначе old==new и diff пуст)
        old_snapshot = dict(structured) if isinstance(structured, dict) else None
        cascade_result = await apply_cascade(
            session,
            bookmark_id=bookmark.id,
            user_id=current_user.id,
            old_structured=old_snapshot,
            new_structured=new_structured,
            user_tz=current_user.timezone or "Europe/Moscow",
        )
        if cascade_result.has_changes:
            # Прикрепляем сводку к new_structured для UI (бот покажет в reply)
            new_structured = dict(new_structured)
            new_structured["cascade_summary"] = cascade_result.summary()
    except Exception as e:
        # Не валим основной flow — NL-edit важнее каскада
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "reminder cascade failed for bookmark %s: %s", bookmark.id, e,
        )

    bookmark.structured_data = new_structured
    return bookmark


@router.post(
    "/{bookmark_id}/structure-as-list", response_model=StructureAsListResponse
)
async def structure_as_list(
    bookmark_id: UUID,
    data: StructureAsListRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Превратить заметку в task_list (кнопка «Сделать списком» после
    near-dup «сохрани как новую»).

    Источник пунктов — `data.text` (явно присланные пункты) либо raw_text
    закладки, если text не задан. structured=False, reason='single_phrase' —
    текст одна фраза без выделяемых пунктов; закладка НЕ мутируется, бот
    спросит пункты явно. См. bookmark-brain-c6ti.
    """
    result = await session.execute(
        select(Bookmark).where(
            Bookmark.id == bookmark_id, Bookmark.user_id == current_user.id
        )
    )
    bookmark = result.scalar_one_or_none()
    if bookmark is None:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    from app.services.task_list_detector import force_structure_as_list

    source = data.text if data.text is not None else (bookmark.raw_text or "")
    structured, reason = force_structure_as_list(
        source, allow_single=data.allow_single
    )
    if structured is None:
        return StructureAsListResponse(structured=False, reason=reason)

    bookmark.structured_data = structured
    return StructureAsListResponse(
        structured=True, reason="ok", tasks_count=len(structured["tasks"])
    )


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
