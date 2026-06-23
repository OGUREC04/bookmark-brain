"""Регулярные напоминания: вычисление времени следующего срабатывания + дедуп.

Чистые функции (без БД) — тестируемы без сессии. CRUD-логика живёт в API
(`app/api/recurring.py`) и worker-materializer (`app/worker/recurring.py`).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Совпадает с DEFAULT_TZ бота (bot.common) — единая дефолтная зона.
DEFAULT_TZ = "Europe/Moscow"


def _safe_tz(tz_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name) if tz_name else ZoneInfo(DEFAULT_TZ)
    except Exception:
        logger.warning(
            "_safe_tz: невалидная tz %r, фолбэк на %s", tz_name, DEFAULT_TZ
        )
        return ZoneInfo(DEFAULT_TZ)


def next_fire_utc(
    hour: int, minute: int, tz_name: str | None, after_utc: datetime
) -> datetime:
    """Ближайший UTC-инстант локального hour:minute СТРОГО позже after_utc.

    Если сегодня это время уже прошло (или ровно сейчас) → завтра. Пересчёт из
    локального времени каждый раз → смена tz/DST учитывается естественно.
    Пропущенные дни НЕ добиваются (корнер-кейс #9 PRD): всегда следующее
    будущее срабатывание, без пачки за простой.
    """
    if after_utc.tzinfo is None:
        after_utc = after_utc.replace(tzinfo=timezone.utc)
    tz = _safe_tz(tz_name)
    after_local = after_utc.astimezone(tz)
    candidate = after_local.replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if candidate <= after_local:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def normalize_series_text(text: str) -> str:
    """Нормализация текста для дедупа серий (тот же текст + время = дубль)."""
    return " ".join((text or "").lower().split())
