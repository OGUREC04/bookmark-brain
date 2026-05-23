"""Product-analytics event emission (Phase M1, ADR 0010).

``emit_event()`` — fire-and-forget запись продуктового события в
``analytics_events``. Источник правды для продуктовой аналитики высокой
кардинальности (качество router-решений, dedup-хиты, …), запрос GROUP BY
постфактум.

НЕ для системных метрик (latency / токены / глубина очереди) — те пойдут в
Prometheus отдельно. Events и metrics — разные хранилища; унификация на
уровне дашборда (Grafana с двумя источниками), не на уровне sink.

Failure-isolated: пишем в ОТДЕЛЬНОЙ сессии (своя транзакция). Сбой записи
метрики НИКОГДА не отравляет транзакцию вызывающего флоу и не ломает его.
"""
from __future__ import annotations

import logging

from app.database import async_session
from app.models import AnalyticsEvent

logger = logging.getLogger(__name__)

# Держим JSONB-payload маленьким (< ~2KB) — выше Postgres пушит в TOAST
# (2-10x медленнее). Сюда кладём дименшены решений, НЕ сырые AI-блобы.
_MAX_NAME = 64
_MAX_SOURCE = 16


async def emit_event(*, name: str, source: str, **dimensions) -> None:
    """Записать продуктовое событие. Fire-and-forget, failure-isolated.

    Args:
        name: имя события («reminder_router_decision»). Обрезается до 64.
        source: процесс-источник («bot» / «worker» / «backend»). До 16.
        **dimensions: произвольные дименшены → JSONB (держи payload < 2KB).

    Любой сбой (БД недоступна, ошибка вставки) логируется на WARNING и
    проглатывается — метрика не должна ломать пользовательский флоу.
    Использует собственную сессию: независимая транзакция, не трогает
    транзакцию caller'а.
    """
    try:
        async with async_session() as session:
            session.add(
                AnalyticsEvent(
                    event_name=name[:_MAX_NAME],
                    source=source[:_MAX_SOURCE],
                    dimensions=dimensions or {},
                )
            )
            await session.commit()
    except Exception as e:  # noqa: BLE001 — намеренно глотаем, метрика best-effort
        logger.warning(f"emit_event({name!r}) failed (swallowed): {e}")
