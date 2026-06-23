"""CRUD API для регулярных (ежедневных) напоминаний — команда /repeat.

Таблица `recurring_reminders`. Парсинг расписания «<текст> каждый день в HH:MM»
и вычисление next_fire_at в таймзоне юзера — на бэкенде (recurrence_parser +
recurring_service). Доставку делает worker-materializer + штатный
scheduled_dispatcher (см. app/worker/recurring.py).

IDOR-защита везде через WHERE user_id = current_user.id.

Endpoints:
- POST   /api/v1/recurring/        — завести серию (парсит raw)
- GET    /api/v1/recurring/        — активные серии юзера
- DELETE /api/v1/recurring/{id}    — остановить серию (+ отмена не сработавших копий)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_session
from app.models import RecurringReminder, ScheduledMessage, User
from app.schemas import RecurringCreate, RecurringListResponse, RecurringResponse
from app.services.recurrence_parser import parse_recurrence
from app.services.recurring_service import next_fire_utc, normalize_series_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/recurring", tags=["recurring"])

# Текст серии — короткая напоминалка, не статья.
MAX_RECURRING_TEXT_LEN = 500
# Максимум активных серий на юзера — защита materializer-батча от засорения.
MAX_ACTIVE_RECURRING = 50

# Понятные сообщения на коды ошибок парсера (бот их просто релеит юзеру).
_PARSE_ERROR_DETAIL = {
    "NO_SCHEDULE": "Не вижу расписание. Пример: /repeat полить цветы каждый день в 10:00",
    "NO_TIME": "Укажи время. Пример: /repeat полить цветы каждый день в 10:00",
    "NO_TEXT": "Что напоминать? Пример: /repeat полить цветы каждый день в 10:00",
    "BAD_TIME": "Время вне диапазона (0–23 ч, 0–59 мин). Пример: /repeat полить цветы каждый день в 9:30",
}


@router.post("/", response_model=RecurringResponse, status_code=status.HTTP_201_CREATED)
async def create_recurring(
    body: RecurringCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Завести ежедневную серию из сырого текста команды /repeat."""
    parsed = parse_recurrence(body.raw or "")
    if not parsed.ok:
        raise HTTPException(
            status_code=422,
            detail=_PARSE_ERROR_DETAIL.get(
                parsed.error, _PARSE_ERROR_DETAIL["NO_SCHEDULE"]
            ),
        )

    text = parsed.text[:MAX_RECURRING_TEXT_LEN]
    now = datetime.now(timezone.utc)
    next_fire = next_fire_utc(parsed.hour, parsed.minute, current_user.timezone, now)
    norm = normalize_series_text(text)

    # Дедуп серии (#5): тот же нормализованный текст + час:минута среди active.
    existing = await session.execute(
        select(RecurringReminder).where(
            RecurringReminder.user_id == current_user.id,
            RecurringReminder.active.is_(True),
            RecurringReminder.hour == parsed.hour,
            RecurringReminder.minute == parsed.minute,
        )
    )
    for row in existing.scalars():
        if normalize_series_text(row.text) == norm:
            resp = RecurringResponse.model_validate(row)
            resp.deduplicated = True
            logger.info(
                "recurring dedup: вернул существующую серию %s для user %s",
                row.id, current_user.id,
            )
            return resp

    # Кап на число активных серий юзера — защита materializer-батча от засорения.
    active_count = await session.scalar(
        select(func.count())
        .select_from(RecurringReminder)
        .where(
            RecurringReminder.user_id == current_user.id,
            RecurringReminder.active.is_(True),
        )
    )
    if active_count is not None and active_count >= MAX_ACTIVE_RECURRING:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Слишком много регулярных напоминаний (максимум {MAX_ACTIVE_RECURRING}). "
                "Останови ненужные кнопкой 🛑."
            ),
        )

    series = RecurringReminder(
        user_id=current_user.id,
        text=text,
        rule=parsed.rule,
        hour=parsed.hour,
        minute=parsed.minute,
        next_fire_at=next_fire,
        active=True,
    )
    # Гонка дедупа: два одновременных одинаковых /repeat. SELECT-then-INSERT не
    # сериализован, но частичный unique-индекс uq_recurring_active_dedup ловит
    # дубль на уровне БД → IntegrityError → возвращаем уже созданную серию.
    # SAVEPOINT (begin_nested), чтобы откат не убил всю транзакцию запроса.
    try:
        async with session.begin_nested():
            session.add(series)
            await session.flush()
    except IntegrityError:
        again = await session.execute(
            select(RecurringReminder).where(
                RecurringReminder.user_id == current_user.id,
                RecurringReminder.active.is_(True),
                RecurringReminder.hour == parsed.hour,
                RecurringReminder.minute == parsed.minute,
            )
        )
        for row in again.scalars():
            if normalize_series_text(row.text) == norm:
                resp = RecurringResponse.model_validate(row)
                resp.deduplicated = True
                return resp
        raise

    await session.refresh(series)
    return series


@router.get("/", response_model=RecurringListResponse)
async def list_recurring(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Активные серии юзера, отсортированы по времени срабатывания."""
    rows = await session.execute(
        select(RecurringReminder)
        .where(
            RecurringReminder.user_id == current_user.id,
            RecurringReminder.active.is_(True),
        )
        .order_by(RecurringReminder.hour, RecurringReminder.minute)
    )
    items = [RecurringResponse.model_validate(r) for r in rows.scalars().all()]
    return RecurringListResponse(items=items, total=len(items))


@router.delete("/{recurring_id}", status_code=status.HTTP_204_NO_CONTENT)
async def stop_recurring(
    recurring_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Остановить серию: active=false + отмена ещё не сработавших копий.

    Корнер-кейс #10: уже материализованные pending scheduled_messages с этим
    recurring_id гасим (status pending→cancelled), иначе «последняя» копия
    сработает уже ПОСЛЕ нажатия 🛑.
    """
    row = await session.execute(
        select(RecurringReminder).where(
            RecurringReminder.id == recurring_id,
            RecurringReminder.user_id == current_user.id,
        )
    )
    series = row.scalar_one_or_none()
    if series is None:
        raise HTTPException(status_code=404, detail="Recurring reminder not found")

    if series.active:
        series.active = False
        series.cancelled_at = datetime.now(timezone.utc)

    # Гасим ещё не сработавшие материализованные копии этой серии.
    await session.execute(
        update(ScheduledMessage)
        .where(
            ScheduledMessage.user_id == current_user.id,
            ScheduledMessage.kind == "reminder",
            ScheduledMessage.status == "pending",
            ScheduledMessage.payload["recurring_id"].astext == str(recurring_id),
        )
        .values(status="cancelled", cancelled_at=datetime.now(timezone.utc))
    )
    await session.flush()
