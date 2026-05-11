"""Pydantic-валидация для `scheduled_messages.payload` (Phase 2.5 v2.1).

`payload` в БД — свободный jsonb. Чтобы не было silent drift полей со
временем, валидируем структуру на write через `ReminderPayload.model_validate(...)`.

Поля:
- text: оригинальный текст напоминания (отображается в /reminders)
- source: откуда пришёл reminder (analytics + behavior switches)
- auto_done: помечено крон'ом auto_done_reminders как done без действий юзера
- snooze_count: сколько раз юзер продлевал (0 при создании, +1 на каждый snooze)
- done_by_user: юзер нажал ✅ (отличается от auto_done и от cancelled-через-API)
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReminderSource = Literal[
    "explicit_remind",   # /remind ...
    "strong_intent",     # «надо/нужно/...» → 🔔
    "implicit_weak",     # weak intent → 🔔
    "v1_legacy",         # старые reminder'ы созданные до v2.1 (для миграции)
]


class ReminderPayload(BaseModel):
    """Структурированный payload reminder'а.

    Используется для валидации перед записью в `scheduled_messages.payload`
    (jsonb). Read-side остаётся свободным dict — старые записи без новых
    полей продолжают работать.
    """

    model_config = ConfigDict(extra="allow")  # будущие поля не ломают старые версии

    text: str = Field(default="", max_length=500, description="Текст напоминания")
    source: ReminderSource = Field(default="v1_legacy")
    auto_done: bool = Field(default=False)
    snooze_count: int = Field(default=0, ge=0)
    done_by_user: bool = Field(default=False)


def to_db_payload(payload: ReminderPayload) -> dict:
    """Сериализация в dict для записи в jsonb.

    Только non-default поля чтобы не раздувать БД. Дефолты восстановятся
    при чтении через `ReminderPayload.model_validate(row.payload or {})`.
    """
    return payload.model_dump(exclude_defaults=True)
