"""add note_entries (заметка-как-диалог) + bookmarks.entries_text

note_entries: дописки в «лог-переписку» заметки (Notes as Conversations, MVP).
  Заметка (bookmarks.raw_text) = «запись #0»/шапка; дописки — отдельные строки
  (append одним INSERT). kind ENUM — в MVP только 'user'; 'brain'/'system'
  зарезервированы под будущие ответы Brain без миграции схемы (ALTER TYPE).
  Голосовая дописка несёт media_file_id/transcription/duration + entry_ai_status.
  Удаление мягкое (is_deleted). Структурная миграция (CREATE TABLE + ADD COLUMN),
  существующие строки bookmarks не трогает — прод-прозрачно.

bookmarks.entries_text: денормализованная конкатенация дописок под FTS;
  наполняет classify-free reembed-джоб (B3). Сама колонка — здесь (nullable).

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-06-26 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NOTE_ENTRY_KIND_VALUES = ("user", "brain", "system")


def upgrade() -> None:
    # Создаём enum-тип явно (как link_kind/scheduled_kind) — inline create_type
    # бывает нестабилен с alembic.
    note_entry_kind = postgresql.ENUM(
        *NOTE_ENTRY_KIND_VALUES, name="note_entry_kind", create_type=False
    )
    bind = op.get_bind()
    note_entry_kind.create(bind, checkfirst=True)

    op.create_table(
        "note_entries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "bookmark_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bookmarks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", note_entry_kind, nullable=False, server_default="user"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        # Голосовая дописка (статус распознавания — на уровне записи).
        sa.Column("media_file_id", sa.Text(), nullable=True),
        sa.Column("transcription", sa.Text(), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),  # сек, дробное (как media_duration)
        sa.Column("entry_ai_status", sa.String(length=20), nullable=True),
    )
    # Partial index — лента грузит только неудалённые, по времени.
    op.create_index(
        "ix_note_entries_thread",
        "note_entries",
        ["bookmark_id", "created_at"],
        postgresql_where=sa.text("NOT is_deleted"),
    )

    # Денорм-колонка под FTS дописок (наполняет reembed-джоб B3).
    op.add_column("bookmarks", sa.Column("entries_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("bookmarks", "entries_text")
    op.drop_index("ix_note_entries_thread", table_name="note_entries")
    op.drop_table("note_entries")

    bind = op.get_bind()
    postgresql.ENUM(name="note_entry_kind").drop(bind, checkfirst=True)
