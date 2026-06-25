"""analytics_events partition maintenance cron (worker split — djtn, ADR 0010).

``analytics_partition_maintenance`` rolls monthly partitions forward and drops
those older than retention. ``async_session`` is looked up in THIS module.
"""

from __future__ import annotations

import logging

from app.database import async_session

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────
# analytics_events partition maintenance (Phase M1, ADR 0010)
# ──────────────────────────────────────────────────

# Сколько месяцев храним аналитические события. Старше — DROP PARTITION.
ANALYTICS_RETENTION_MONTHS = 6


def _month_partition(year: int, month: int) -> tuple[str, str, str]:
    """(имя_партиции, начало, конец) для месяца. Границы RANGE [from, to)."""
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    return (
        f"analytics_events_{year:04d}_{month:02d}",
        f"{year:04d}-{month:02d}-01",
        f"{ny:04d}-{nm:02d}-01",
    )


async def analytics_partition_maintenance(ctx: dict) -> None:
    """Cron (раз в сутки + на старте): катит месячные партиции
    analytics_events вперёд и дропает старше retention.

    DROP PARTITION = чистый retention без bloat/VACUUM-боли. Партиции на
    текущий+следующий месяц всегда есть → данные не попадают в DEFAULT,
    retention работает по-месячно.
    """
    from datetime import datetime, timezone

    from sqlalchemy import text as sa_text

    now = datetime.now(timezone.utc)
    # 1. Создаём партиции на текущий + следующий месяц (idempotent).
    months = [(now.year, now.month)]
    months.append((now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1))

    created = 0
    async with async_session() as session:
        for year, month in months:
            name, start, end = _month_partition(year, month)
            await session.execute(sa_text(
                f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF analytics_events "
                f"FOR VALUES FROM ('{start}') TO ('{end}')"
            ))
            created += 1
        await session.commit()

        # 2. Дропаем партиции старше retention.
        cutoff_idx = now.year * 12 + (now.month - 1) - ANALYTICS_RETENTION_MONTHS
        rows = (await session.execute(sa_text(
            "SELECT child.relname FROM pg_inherits "
            "JOIN pg_class parent ON pg_inherits.inhparent = parent.oid "
            "JOIN pg_class child ON pg_inherits.inhrelid = child.oid "
            "WHERE parent.relname = 'analytics_events'"
        ))).scalars().all()

        dropped = 0
        for relname in rows:
            # ждём формат analytics_events_YYYY_MM (default-партицию пропускаем)
            parts = relname.rsplit("_", 2)
            if len(parts) != 3 or not (parts[1].isdigit() and parts[2].isdigit()):
                continue
            p_idx = int(parts[1]) * 12 + (int(parts[2]) - 1)
            if p_idx < cutoff_idx:
                await session.execute(sa_text(f"DROP TABLE IF EXISTS {relname}"))
                dropped += 1
        await session.commit()

    logger.info(
        f"analytics partition maintenance: ensured {created} month(s), "
        f"dropped {dropped} old (retention={ANALYTICS_RETENTION_MONTHS}mo)"
    )
