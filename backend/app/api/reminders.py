"""CRUD API для напоминаний (Phase 2.5).

Под капотом — таблица `scheduled_messages` с `kind='reminder'`. Generic schema
позволит Phase 6 переиспользовать таблицу для digest/surfacing без миграции.

Endpoints:
- POST   /api/v1/reminders/         — создать
- PATCH  /api/v1/reminders/{id}     — продлить (snooze): меняет fire_at
- DELETE /api/v1/reminders/{id}     — отменить (status=cancelled)
- GET    /api/v1/reminders/upcoming — список pending для current_user

Все endpoint'ы скопированы под current_user — IDOR-защита через WHERE user_id=current_user.id.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_session
from app.models import Bookmark, ScheduledMessage, User
from app.schemas import (
    ReminderCreate,
    ReminderListResponse,
    ReminderResponse,
    ReminderUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/reminders", tags=["reminders"])

REMINDER_KIND = "reminder"

# Толерантность к «чуть-в-прошлом» fire_at. nl_date.parse допускает время
# до 30 сек в прошлом (возвращает OK, не IN_PAST), плюс между парсингом в
# боте и проверкой здесь проходит сетевой round-trip. Строгий `<= now`
# реджектил такие граничные значения как 400 (bookmark-brain-bne).
# Принимаем fire_at в окне [now - grace, ∞); если он в прошлом-но-в-grace,
# поджимаем к «сейчас» чтобы сработало немедленно.
_PAST_GRACE_SECONDS = 120

# Лимит длины текста напоминания при правке (тикет 8uu). Текст — короткая
# напоминалка, не статья; защищает payload от раздувания.
MAX_REMINDER_TEXT_LEN = 2000


@router.post(
    "/",
    response_model=ReminderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_reminder(
    body: ReminderCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Создать новое напоминание для текущего пользователя."""
    # Валидация: fire_at должен быть в будущем (с grace на граничные значения).
    now = datetime.now(timezone.utc)
    fire_at = body.fire_at
    if fire_at.tzinfo is None:
        # Naive datetime — трактуем как UTC (клиент обязан слать UTC ISO).
        fire_at = fire_at.replace(tzinfo=timezone.utc)
    if fire_at < now - timedelta(seconds=_PAST_GRACE_SECONDS):
        # Явно в прошлом (за пределами grace) — это ошибка.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fire_at must be in the future",
        )
    if fire_at <= now:
        # В пределах grace, но уже прошло — поджимаем к «сейчас+5с».
        fire_at = now + timedelta(seconds=5)

    # Если bookmark_id задан — проверить что он принадлежит юзеру (IDOR-защита)
    if body.bookmark_id is not None:
        result = await session.execute(
            select(Bookmark).where(
                Bookmark.id == body.bookmark_id,
                Bookmark.user_id == current_user.id,
            )
        )
        if result.scalar_one_or_none() is None:
            # Не палим существование чужого bookmark — 404
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Bookmark not found"
            )

    # E15 exact-dedup: тот же текст + та же МИНУТА fire_at среди pending →
    # не плодим дубль, возвращаем существующий (идемпотентно). Ловит
    # случайные двойные «напомни …». Разный текст / время — создаём как есть.
    # Единый helper переиспользуется и в worker-путях (reminder_creator).
    from app.services.reminder_creator import find_duplicate_reminder

    new_text = (body.payload or {}).get("text")
    existing = await find_duplicate_reminder(
        session, current_user.id, new_text, fire_at,
    )
    if existing is not None:
        logger.info(
            f"reminder dedup: вернул существующий {existing.id} "
            f"(text+minute совпали) вместо дубля для user {current_user.id}"
        )
        resp = _to_reminder_response(existing, include_bookmark=False)
        resp.deduplicated = True
        return resp

    reminder = ScheduledMessage(
        user_id=current_user.id,
        bookmark_id=body.bookmark_id,
        kind=REMINDER_KIND,
        fire_at=fire_at,
        status="pending",
        payload=body.payload,
    )
    session.add(reminder)
    await session.flush()
    await session.refresh(reminder)
    return reminder


@router.patch("/{reminder_id}", response_model=ReminderResponse)
async def update_reminder(
    reminder_id: UUID,
    body: ReminderUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Обновить напоминание: snooze (`fire_at`) и/или текст (`text`, тикет 8uu).

    - Только `fire_at` → snooze (как раньше), статус → pending.
    - Только `text` → правка текста в `payload["text"]`, время и статус не трогаем.
    - Оба → применяются вместе.
    - Ни одного → no-op (возврат без изменений).

    Правка текста разрешена только для `status='pending'` (для уже сработавших/
    отменённых текст не редактируется — 409). Пустой текст → 422.
    """
    reminder = await _get_user_reminder(session, reminder_id, current_user.id)

    has_fire_at = body.fire_at is not None
    has_text = body.text is not None
    if not has_fire_at and not has_text:
        # Нечего обновлять
        return reminder

    # ── Валидация ДО любых мутаций (чтобы не оставить частичное изменение) ──
    new_text: str | None = None
    if has_text:
        if reminder.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot edit text of a non-pending reminder",
            )
        new_text = body.text.strip()
        if not new_text:
            raise HTTPException(
                status_code=422,
                detail="text must not be empty",
            )
        if len(new_text) > MAX_REMINDER_TEXT_LEN:
            raise HTTPException(
                status_code=422,
                detail=f"text too long (max {MAX_REMINDER_TEXT_LEN} chars)",
            )

    new_fire_at: datetime | None = None
    if has_fire_at:
        new_fire_at = body.fire_at
        if new_fire_at.tzinfo is None:
            new_fire_at = new_fire_at.replace(tzinfo=timezone.utc)
        if new_fire_at <= datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="fire_at must be in the future",
            )

    # ── Применяем ──
    if new_text is not None:
        # JSONB-safe: новый dict вместо in-place мутации, иначе SQLAlchemy не
        # заметит изменение payload и не запишет (concepts/sqlalchemy-jsonb-mutation).
        reminder.payload = {**(reminder.payload or {}), "text": new_text}
    if new_fire_at is not None:
        reminder.fire_at = new_fire_at
        reminder.status = "pending"
        reminder.sent_at = None
        reminder.cancelled_at = None

    await session.flush()
    await session.refresh(reminder)
    return reminder


@router.delete("/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_reminder(
    reminder_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Отменить напоминание (status=cancelled). Не удаляет запись (история)."""
    reminder = await _get_user_reminder(session, reminder_id, current_user.id)
    reminder.status = "cancelled"
    reminder.cancelled_at = datetime.now(timezone.utc)
    await session.flush()


@router.post("/cancel-all")
async def cancel_all_pending(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Bulk-отмена всех pending напоминаний юзера (/clearreminders).

    Ставит status=cancelled (история сохраняется). Уже отправленные/отменённые
    не трогаются. Возвращает {"cancelled": N}.
    """
    from sqlalchemy import update

    stmt = (
        update(ScheduledMessage)
        .where(
            ScheduledMessage.user_id == current_user.id,
            ScheduledMessage.kind == REMINDER_KIND,
            ScheduledMessage.status == "pending",
        )
        .values(status="cancelled", cancelled_at=datetime.now(timezone.utc))
    )
    result = await session.execute(stmt)
    await session.flush()
    return {"cancelled": result.rowcount}


@router.post("/redispatch/{bookmark_id}")
async def redispatch_reminder_decision(
    bookmark_id: UUID,
    chat_id: int | None = Query(
        default=None,
        description="Чат для UI/уведомления reminder'а (DM chat_id бота).",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Переигрывает сохранённый `reminder_decision` закладки (ied).

    Контекст: при near-duplicate worker пропускает dispatch reminder'ов
    (юзер ещё выбирает что делать с дублем). Если он жмёт «сохрани как
    новую», reminder'ы из persisted decision иначе теряются. Бот зовёт этот
    endpoint → enqueue arq-джобы `redispatch_reminder_task`.

    Идемпотентно: сам dispatch защищён CAS-флагом `reminder_decision_applied`.
    Возвращает {"enqueued": bool} — False если decision нет или уже применён.
    """
    result = await session.execute(
        select(Bookmark).where(
            Bookmark.id == bookmark_id,
            Bookmark.user_id == current_user.id,
        )
    )
    bookmark = result.scalar_one_or_none()
    if bookmark is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bookmark not found")

    structured = bookmark.structured_data or {}
    decision = structured.get("reminder_decision") if isinstance(structured, dict) else None
    if not isinstance(decision, dict) or structured.get("reminder_decision_applied"):
        return {"enqueued": False}

    from app.api.bookmarks import get_arq_pool

    pool = await get_arq_pool()
    await pool.enqueue_job("redispatch_reminder_task", str(bookmark_id), chat_id)
    return {"enqueued": True}


@router.get("/upcoming", response_model=ReminderListResponse)
async def list_upcoming(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Список pending напоминаний юзера, отсортирован по fire_at.

    B1 (2026-05-15): eager-load bookmark для Mini App RemindersSheet,
    чтобы избежать N+1 при рендере title рядом с каждым reminder.
    """
    stmt = (
        select(ScheduledMessage)
        .options(selectinload(ScheduledMessage.bookmark))
        .where(
            ScheduledMessage.user_id == current_user.id,
            ScheduledMessage.kind == REMINDER_KIND,
            ScheduledMessage.status == "pending",
        )
        .order_by(ScheduledMessage.fire_at.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    items = list(result.scalars().all())
    responses = [_to_reminder_response(m) for m in items]
    return ReminderListResponse(items=responses, total=len(responses))


@router.get("/history", response_model=ReminderListResponse)
async def list_history(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=20, ge=1, le=200),
    days: int = Query(default=30, ge=1, le=365),
):
    """T12 v2.1: история выполненных/отменённых reminder'ов за N дней.

    status в (done, cancelled), отсортировано по созданию (новые первые).
    """
    from datetime import timedelta as _td
    since = datetime.now(timezone.utc) - _td(days=days)
    stmt = (
        select(ScheduledMessage)
        .where(
            ScheduledMessage.user_id == current_user.id,
            ScheduledMessage.kind == REMINDER_KIND,
            ScheduledMessage.status.in_(["done", "cancelled"]),
            ScheduledMessage.created_at >= since,
        )
        .order_by(ScheduledMessage.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    items = list(result.scalars().all())
    # history без bookmark relationship (history-карточкам title не нужен)
    responses = [_to_reminder_response(m, include_bookmark=False) for m in items]
    return ReminderListResponse(items=responses, total=len(responses))


def _to_reminder_response(
    m: ScheduledMessage, include_bookmark: bool = True
) -> ReminderResponse:
    """Сериализация ScheduledMessage → ReminderResponse с опциональным bookmark.

    B1: для list_upcoming передаём include_bookmark=True (selectinload загрузил),
    для list_history — False (relationship lazy="noload", не дергаем DB).
    """
    return ReminderResponse(
        id=m.id,
        bookmark_id=m.bookmark_id,
        kind=m.kind,
        fire_at=m.fire_at,
        status=m.status,
        payload=m.payload,
        created_at=m.created_at,
        sent_at=m.sent_at,
        bookmark_title=(m.bookmark.title if include_bookmark and m.bookmark else None),
        bookmark_raw_text=(m.bookmark.raw_text if include_bookmark and m.bookmark else None),
    )


# ──────────────────── Phase 2.6: apply-decision ────────────────────


@router.post(
    "/apply-decision/{bookmark_id}",
    response_model=ReminderListResponse,
    status_code=status.HTTP_201_CREATED,
)
async def apply_reminder_decision(
    bookmark_id: UUID,
    form: str = Query(
        ...,
        pattern="^(task_list_with_reminders|composite_reminder|single_reminder)$",
        description="Финальная форма из 3-button click или Phase 2.6 dispatch",
    ),
    composite_fire_at: datetime | None = Query(
        default=None,
        description="Только для composite_reminder — выбранная дата (UTC).",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Применяет ранее сохранённое router-решение (`structured_data.reminder_decision`)
    к bookmark'у, создавая один или несколько reminder'ов.

    Используется ботом при нажатии 3-button «📋/🔔/✕» (T4) и из dispatch
    воркера для auto-create (T5).

    IDOR-защита: проверяем, что bookmark принадлежит current_user.

    Идемпотентность не гарантируется на этом уровне — повторный POST создаст
    дубли. Bot Redis-anti-double блокирует повторные клики по той же кнопке.
    """
    from app.services.nl_date import ParseStatus
    from app.services.reminder_creator import (
        create_composite_reminder,
        create_per_item_reminders,
        create_single_reminder,
    )
    from app.services.reminder_router import ReminderForm, ResolvedItem, RouterDecision

    # Загружаем bookmark с проверкой владения
    result = await session.execute(
        select(Bookmark).where(
            Bookmark.id == bookmark_id,
            Bookmark.user_id == current_user.id,
        )
    )
    bookmark = result.scalar_one_or_none()
    if bookmark is None:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    structured = bookmark.structured_data or {}
    raw_decision = structured.get("reminder_decision")
    if not raw_decision or not isinstance(raw_decision, dict):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No reminder_decision in bookmark.structured_data — nothing to apply.",
        )

    # Idempotency-гард race-safe: атомарный UPDATE с CAS по
    # `structured_data.reminder_decision_applied`. Если флаг уже стоит
    # (другой конкурентный запрос / worker auto-create), RETURNING вернёт
    # пусто → 409. Без этого read-then-write race открывает double-spend.
    from sqlalchemy import text as _sa_text
    cas_result = await session.execute(_sa_text(
        """
        UPDATE bookmarks
        SET structured_data = COALESCE(structured_data, '{}'::jsonb)
                              || jsonb_build_object('reminder_decision_applied', true)
        WHERE id = CAST(:bid AS uuid)
          AND user_id = CAST(:uid AS uuid)
          AND COALESCE(structured_data->>'reminder_decision_applied', 'false') <> 'true'
        RETURNING id
        """
    ).bindparams(bid=str(bookmark_id), uid=str(current_user.id)))
    if cas_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reminder decision already applied for this bookmark.",
        )
    # Перезагружаем bookmark чтобы получить актуальное structured_data
    # после CAS (SQLAlchemy кэширует объект — `bookmark.structured_data` без
    # refresh покажет старое значение).
    await session.refresh(bookmark)
    structured = bookmark.structured_data or {}

    # Восстанавливаем RouterDecision из persisted dict.
    # Только items нужны — form мы получаем из query (выбор юзера может
    # отличаться от router-default'а: NEEDS_BUTTON_CHOICE → user picks 📋 vs 🔔).
    items: list[ResolvedItem] = []
    for raw in raw_decision.get("items", []):
        fire_at = raw.get("fire_at_utc")
        parsed_dt = None
        if fire_at:
            try:
                parsed_dt = datetime.fromisoformat(fire_at)
                if parsed_dt.tzinfo is None:
                    parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                logger.warning("apply-decision: bad fire_at_utc %r in bookmark %s", fire_at, bookmark_id)
                continue
        status_raw = raw.get("status")
        items.append(
            ResolvedItem(
                text=raw.get("text", ""),
                raw_date_phrase=raw.get("raw_date_phrase"),
                fire_at=parsed_dt,
                status=ParseStatus(status_raw) if status_raw else None,
            )
        )
    decision = RouterDecision(form=ReminderForm(form), items=items)

    now = datetime.now(timezone.utc)
    created: list[ScheduledMessage] = []

    if form == "task_list_with_reminders":
        created = await create_per_item_reminders(session, bookmark, decision, now=now)
    elif form == "composite_reminder":
        # Bot обязан передать composite_fire_at — берём первую dated_item если нет
        fire_at = composite_fire_at
        if fire_at is None and decision.dated_items:
            fire_at = decision.dated_items[0].fire_at
        if fire_at is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="composite_fire_at required when no dated items in decision",
            )
        if fire_at.tzinfo is None:
            fire_at = fire_at.replace(tzinfo=timezone.utc)
        reminder = await create_composite_reminder(
            session, bookmark, fire_at=fire_at, now=now,
        )
        if reminder is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="fire_at must be in the future",
            )
        created = [reminder]
    elif form == "single_reminder":
        if not decision.dated_items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No dated items in decision for single_reminder",
            )
        reminder = await create_single_reminder(
            session, bookmark, decision.dated_items[0],
            now=now, source="single_reminder_decision",
        )
        if reminder is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="fire_at must be in the future",
            )
        created = [reminder]

    # Флаг уже выставлен через CAS-UPDATE выше — здесь просто flush'аем
    # созданные ScheduledMessage'ы в той же транзакции.
    await session.flush()
    for r in created:
        await session.refresh(r)
    return ReminderListResponse(items=created, total=len(created))


async def _get_user_reminder(
    session: AsyncSession, reminder_id: UUID, user_id: UUID
) -> ScheduledMessage:
    """IDOR-защита: возвращаем reminder только если он принадлежит юзеру.

    Чужой reminder → 404 (не палим существование).
    """
    result = await session.execute(
        select(ScheduledMessage).where(
            ScheduledMessage.id == reminder_id,
            ScheduledMessage.user_id == user_id,
            ScheduledMessage.kind == REMINDER_KIND,
        )
    )
    reminder = result.scalar_one_or_none()
    if reminder is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Reminder not found"
        )
    return reminder
