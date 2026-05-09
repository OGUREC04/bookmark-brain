from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    create_access_token,
    get_current_user,
    verify_bot_request,
    verify_telegram_init_data,
)
from app.config import get_settings
from app.database import get_session
from app.models import User
from app.schemas import (
    TelegramAuthData,
    TokenResponse,
    UserCreate,
    UserResponse,
)

router = APIRouter(prefix="/api/v1", tags=["auth & users"])
settings = get_settings()


@router.post("/auth/telegram", response_model=TokenResponse)
async def auth_telegram(
    data: TelegramAuthData,
    session: AsyncSession = Depends(get_session),
):
    """Аутентификация через Telegram Mini App initData."""
    user_data = verify_telegram_init_data(data.init_data, settings.TELEGRAM_BOT_TOKEN)

    telegram_id = user_data.get("id")
    if not telegram_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No user id in init_data",
        )

    # Найти или создать пользователя
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            telegram_id=telegram_id,
            telegram_username=user_data.get("username"),
            telegram_first_name=user_data.get("first_name"),
            telegram_photo_url=user_data.get("photo_url"),
        )
        session.add(user)
        await session.flush()
    else:
        # Обновить данные профиля
        user.telegram_username = user_data.get("username", user.telegram_username)
        user.telegram_first_name = user_data.get("first_name", user.telegram_first_name)
        user.telegram_photo_url = user_data.get("photo_url", user.telegram_photo_url)
        user.last_active = datetime.now(timezone.utc)

    token = create_access_token(user.id, user.telegram_id)
    return TokenResponse(access_token=token)


@router.post("/auth/bot", response_model=TokenResponse)
async def auth_bot_user(
    data: UserCreate,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_bot_request),
):
    """Создать/обновить пользователя от имени бота. Требует X-Bot-Secret header."""
    result = await session.execute(
        select(User).where(User.telegram_id == data.telegram_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            telegram_id=data.telegram_id,
            telegram_username=data.telegram_username,
            telegram_first_name=data.telegram_first_name,
        )
        session.add(user)
        await session.flush()
    else:
        user.telegram_username = data.telegram_username or user.telegram_username
        user.telegram_first_name = data.telegram_first_name or user.telegram_first_name
        user.last_active = datetime.now(timezone.utc)

    token = create_access_token(user.id, user.telegram_id)
    return TokenResponse(access_token=token)


@router.get("/users/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
):
    return current_user


@router.patch("/users/me/settings", response_model=UserResponse)
async def update_settings(
    new_settings: dict,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Обновить пользовательские настройки (merge с существующими)."""
    merged = {**(current_user.settings or {}), **new_settings}
    await session.execute(
        update(User).where(User.id == current_user.id).values(settings=merged)
    )
    current_user.settings = merged
    return current_user


class TimezoneUpdate(BaseModel):
    """Body для PATCH /users/me/timezone."""

    timezone: str = Field(min_length=1, max_length=64)


@router.patch("/users/me/timezone", response_model=UserResponse)
async def update_timezone(
    body: TimezoneUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Сменить часовой пояс пользователя.

    Принимает IANA-имена: `Europe/Moscow`, `Europe/Kaliningrad`, `Asia/Yekaterinburg`.
    Невалидное имя → 400.
    """
    try:
        ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown timezone: {body.timezone!r}. Use IANA names like 'Europe/Moscow'.",
        ) from exc

    await session.execute(
        update(User).where(User.id == current_user.id).values(timezone=body.timezone)
    )
    current_user.timezone = body.timezone
    return current_user
