"""B1 (заметка-как-диалог): модель NoteEntry + колонка bookmarks.entries_text.

Проверки на уровне metadata (без БД, как test_scheduled_message_model):
- kind — Postgres ENUM note_entry_kind (user/brain/system), create_type=False,
  default 'user' (forward-compat под будущие ответы Brain без миграции схемы);
- duration — Float (фронт шлёт дробную длительность; SMALLINT обрезал бы);
- is_deleted — Boolean со server_default false (мягкое удаление);
- bookmark_id — FK на bookmarks с ON DELETE CASCADE;
- bookmarks.entries_text существует (денорм-конкатенация дописок под FTS, B3).
"""
from __future__ import annotations

from app.models import Bookmark, NoteEntry
from sqlalchemy import Boolean, Float, Text
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM


def _col(name: str):
    return NoteEntry.__table__.c[name]


class TestNoteEntryColumns:
    def test_table_name(self):
        assert NoteEntry.__tablename__ == "note_entries"

    def test_kind_is_pg_enum_with_user_default(self):
        col = _col("kind")
        assert isinstance(col.type, PG_ENUM), (
            f"NoteEntry.kind должен быть postgresql.ENUM, а не {type(col.type).__name__} "
            f"(forward-compat под brain/system без миграции схемы)."
        )
        assert col.type.name == "note_entry_kind"
        assert set(col.type.enums) == {"user", "brain", "system"}
        assert col.type.create_type is False  # тип создаёт миграция
        assert str(col.server_default.arg) == "user"
        assert col.nullable is False

    def test_body_required_text(self):
        assert isinstance(_col("body").type, Text)
        assert _col("body").nullable is False

    def test_duration_is_float_not_smallint(self):
        # фронт шлёт дробную длительность (media_duration тоже Float) — SMALLINT обрезал бы
        assert isinstance(_col("duration").type, Float)

    def test_is_deleted_soft_delete_default_false(self):
        col = _col("is_deleted")
        assert isinstance(col.type, Boolean)
        assert col.nullable is False
        assert "false" in str(col.server_default.arg).lower()

    def test_bookmark_fk_cascade(self):
        fk = next(iter(_col("bookmark_id").foreign_keys))
        assert fk.column.table.name == "bookmarks"
        assert fk.ondelete == "CASCADE"
        assert _col("bookmark_id").nullable is False

    def test_voice_and_edit_fields_nullable(self):
        for name in ("media_file_id", "transcription", "duration", "entry_ai_status", "edited_at"):
            assert _col(name).nullable is True, f"{name} должен быть nullable"


class TestBookmarkEntriesText:
    def test_entries_text_column_exists_nullable(self):
        col = Bookmark.__table__.c["entries_text"]
        assert isinstance(col.type, Text)
        assert col.nullable is True
