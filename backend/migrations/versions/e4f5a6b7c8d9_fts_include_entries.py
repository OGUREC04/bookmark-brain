"""search_vector включает bookmarks.entries_text (FTS дописок, Notes as Conversations)

Дописки лога живут в note_entries; reembed-джоб (B3) денормализует их в колонку
bookmarks.entries_text. Чтобы дописки находились full-text поиском, расширяем
триггерную функцию search_vector (добавляем entries_text) и список колонок триггера
(срабатывать также на UPDATE OF entries_text). Без этого дописки в FTS не попадают —
триггер видит только колонки строки bookmarks, а не таблицу note_entries.

Зависит от колонки bookmarks.entries_text (миграция d3e4f5a6b7c8).

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-06-26 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FN_WITH_ENTRIES = """
    CREATE OR REPLACE FUNCTION bookmarks_search_vector_update() RETURNS trigger AS $$
    BEGIN
        NEW.search_vector := to_tsvector(
            'russian',
            coalesce(NEW.title, '') || ' ' ||
            coalesce(NEW.raw_text, '') || ' ' ||
            coalesce(NEW.summary, '') || ' ' ||
            coalesce(NEW.entries_text, '')
        );
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
"""

_FN_ORIGINAL = """
    CREATE OR REPLACE FUNCTION bookmarks_search_vector_update() RETURNS trigger AS $$
    BEGIN
        NEW.search_vector := to_tsvector(
            'russian',
            coalesce(NEW.title, '') || ' ' ||
            coalesce(NEW.raw_text, '') || ' ' ||
            coalesce(NEW.summary, '')
        );
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
"""

_TRIGGER_WITH_ENTRIES = """
    CREATE TRIGGER bookmarks_search_vector_trigger
        BEFORE INSERT OR UPDATE OF title, raw_text, summary, entries_text
        ON bookmarks
        FOR EACH ROW
        EXECUTE FUNCTION bookmarks_search_vector_update();
"""

_TRIGGER_ORIGINAL = """
    CREATE TRIGGER bookmarks_search_vector_trigger
        BEFORE INSERT OR UPDATE OF title, raw_text, summary
        ON bookmarks
        FOR EACH ROW
        EXECUTE FUNCTION bookmarks_search_vector_update();
"""


def upgrade() -> None:
    op.execute(_FN_WITH_ENTRIES)
    op.execute("DROP TRIGGER IF EXISTS bookmarks_search_vector_trigger ON bookmarks")
    op.execute(_TRIGGER_WITH_ENTRIES)


def downgrade() -> None:
    op.execute(_FN_ORIGINAL)
    op.execute("DROP TRIGGER IF EXISTS bookmarks_search_vector_trigger ON bookmarks")
    op.execute(_TRIGGER_ORIGINAL)
