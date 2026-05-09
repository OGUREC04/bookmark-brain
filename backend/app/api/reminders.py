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
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    # Валидация: fire_at должен быть в будущем
    now = datetime.now(timezone.utc)
    fire_at = body.fire_at
    if fire_at.tzinfo is None:
        fire_at = fire_at.replace(tzinfo=timezone.utc)
    if fire_at <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fire_at must be in the future",
        )

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
    """Продлить напоминание (snooze): меняем fire_at, статус → pending."""
    reminder = await _get_user_reminder(session, reminder_id, current_user.id)

    if body.fire_at is None:
        # Нечего обновлять
        return reminder

    new_fire_at = body.fire_at
    if new_fire_at.tzinfo is None:
        new_fire_at = new_fire_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if new_fire_at <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fire_at must be in the future",
        )

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


@router.get("/upcoming", response_model=ReminderListResponse)
async def list_upcoming(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Список pending напоминаний юзера, отсортирован по fire_at."""
    stmt = (
        select(ScheduledMessage)
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
    return ReminderListResponse(items=items, total=len(items))


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
