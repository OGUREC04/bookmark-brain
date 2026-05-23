"""add scheduled_messages table for Phase 2.5 reminders

Generic schema (kind ENUM): сейчас используется только kind='reminder',
позже Phase 6 добавит digest/surfacing/nudge без миграции схемы.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-09 00:00:01.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SCHEDULED_KIND_VALUES = ("reminder", "digest", "surfacing", "nudge")
SCHEDULED_STATUS_VALUES = (
    "pending",
    "sending",
    "sent",
    "done",
    "cancelled",
    "failed",
)


def upgrade() -> None:
    scheduled_kind = postgresql.ENUM(
        *SCHEDULED_KIND_VALUES, name="scheduled_kind", create_type=False
    )
    scheduled_status = postgresql.ENUM(
        *SCHEDULED_STATUS_VALUES, name="scheduled_status", create_type=False
    )

    # Создаём enum-типы явно (alembic + psycopg бывает нестабилен с inline create_type)
    bind = op.get_bind()
    scheduled_kind.create(bind, checkfirst=True)
    scheduled_status.create(bind, checkfirst=True)

    op.create_table(
        "scheduled_messages",
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
        sa.Column(
            "bookmark_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bookmarks.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kind", scheduled_kind, nullable=False),
        sa.Column("fire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            scheduled_status,
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "retry_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Partial index — только pending записи нужны для cron-сканирования
    op.create_index(
        "ix_scheduled_messages_pending_fire",
        "scheduled_messages",
        ["fire_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # Lookup по юзеру (для /reminders команды в будущем + cleanup)
    op.create_index(
        "ix_scheduled_messages_user_status",
        "scheduled_messages",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scheduled_messages_user_status", table_name="scheduled_messages"
    )
    op.drop_index(
        "ix_scheduled_messages_pending_fire", table_name="scheduled_messages"
    )
    op.drop_table("scheduled_messages")

    bind = op.get_bind()
    postgresql.ENUM(name="scheduled_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="scheduled_kind").drop(bind, checkfirst=True)
