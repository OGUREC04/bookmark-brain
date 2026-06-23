"""add recurring_reminders table (ежедневные регулярные напоминания /repeat)

Регулярные напоминания заводятся явной командой /repeat и повторяются ежедневно.
Отдельная таблица, а НЕ колонки на scheduled_messages: тот fire-once
(pending→sending→sent, строки не удаляет) — мешать в него повторы = ломать
концерны. Materializer-cron по next_fire_at кладёт очередную одноразовую строку
в scheduled_messages (payload.recurring_id), дальше штатный dispatcher доставляет.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-06-21 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recurring_reminders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("hour", sa.SmallInteger(), nullable=False),
        sa.Column("minute", sa.SmallInteger(), nullable=False),
        sa.Column("next_fire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        # CHECK — час/минута в диапазоне (defense-in-depth: парсер валидирует
        # на входе, но прямой DB-write/дрейф схемы иначе уронил бы materializer).
        sa.CheckConstraint("hour >= 0 AND hour <= 23", name="ck_recurring_hour_range"),
        sa.CheckConstraint("minute >= 0 AND minute <= 59", name="ck_recurring_minute_range"),
    )
    # Partial index — materializer сканирует только активные серии.
    op.create_index(
        "ix_recurring_next_fire",
        "recurring_reminders",
        ["next_fire_at"],
        postgresql_where=sa.text("active"),
    )
    # FK user_id не индексируется автоматически — нужен для dedup/list-запросов API.
    op.create_index(
        "ix_recurring_reminders_user_id",
        "recurring_reminders",
        ["user_id"],
    )
    # DB-backstop дедупа: одна активная серия на (user, час, минута, норм-текст).
    # Норм-текст зеркалит normalize_series_text (lower + схлопнутые пробелы + trim).
    # Ловит гонку двух одновременных одинаковых /repeat.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_recurring_active_dedup
        ON recurring_reminders (
            user_id, hour, minute,
            btrim(regexp_replace(lower(text), '\\s+', ' ', 'g'))
        )
        WHERE active
        """
    )


def downgrade() -> None:
    # Чистим осиротевшие материализованные копии — иначе dispatcher попытается
    # доставить их с recurring_id, но таблицы-источника уже нет.
    op.execute(
        "DELETE FROM scheduled_messages WHERE payload->>'recurring_id' IS NOT NULL"
    )
    op.execute("DROP INDEX IF EXISTS uq_recurring_active_dedup")
    op.drop_index("ix_recurring_reminders_user_id", table_name="recurring_reminders")
    op.drop_index("ix_recurring_next_fire", table_name="recurring_reminders")
    op.drop_table("recurring_reminders")
