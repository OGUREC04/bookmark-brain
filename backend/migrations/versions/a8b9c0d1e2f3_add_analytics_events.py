"""add analytics_events partitioned event store (Phase M1, ADR 0010)

Generic product-analytics event store. Партиционирована помесячно по ts:
retention = DROP PARTITION (без bloat). PK композитный (id, ts) —
Postgres требует partition key в первичном ключе партиционированной таблицы.

Партиции на текущий + следующий месяц создаём здесь; DEFAULT-партиция —
страховка чтобы INSERT никогда не падал. Дальше партиции катит cron
``analytics_partition_maintenance`` (создаёт вперёд, дропает старые).

Revision ID: a8b9c0d1e2f3
Revises: a7b8c9d0e1f2
Create Date: 2026-05-23 20:30:00.000000
"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    """('YYYY-MM-01', начало след. месяца) — границы партиции [from, to)."""
    start = f"{year:04d}-{month:02d}-01"
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    end = f"{ny:04d}-{nm:02d}-01"
    return start, end


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE analytics_events (
            id          BIGINT GENERATED ALWAYS AS IDENTITY,
            ts          timestamptz NOT NULL DEFAULT now(),
            event_name  text        NOT NULL,
            source      text        NOT NULL,
            dimensions  jsonb       NOT NULL DEFAULT '{}',
            PRIMARY KEY (id, ts)
        ) PARTITION BY RANGE (ts);
        """
    )
    # DEFAULT-партиция — страховка: INSERT не упадёт даже если месячной нет.
    op.execute(
        "CREATE TABLE analytics_events_default "
        "PARTITION OF analytics_events DEFAULT;"
    )
    # Индексы на родителе наследуются всеми партициями.
    op.execute(
        "CREATE INDEX ix_analytics_events_name_ts "
        "ON analytics_events (event_name, ts);"
    )
    op.execute(
        "CREATE INDEX ix_analytics_events_dimensions "
        "ON analytics_events USING gin (dimensions);"
    )

    # Партиции на текущий + следующий месяц.
    now = datetime.now(timezone.utc)
    months = [(now.year, now.month)]
    months.append((now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1))
    for year, month in months:
        start, end = _month_bounds(year, month)
        name = f"analytics_events_{year:04d}_{month:02d}"
        op.execute(
            f"CREATE TABLE {name} PARTITION OF analytics_events "
            f"FOR VALUES FROM ('{start}') TO ('{end}');"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS analytics_events CASCADE;")
