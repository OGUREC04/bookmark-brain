"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-04-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID

revision: str = "001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Extensions ---
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')

    # --- Users ---
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("telegram_username", sa.String(255)),
        sa.Column("telegram_first_name", sa.String(255)),
        sa.Column("telegram_photo_url", sa.Text()),
        sa.Column("settings", JSONB(), server_default="{}"),
        sa.Column("import_status", sa.String(20), server_default="none"),
        sa.Column("last_import_at", sa.DateTime(timezone=True)),
        sa.Column("bookmarks_count", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("last_active", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_users_telegram_id", "users", ["telegram_id"])

    # --- Bookmarks ---
    op.create_table(
        "bookmarks",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        # Source
        sa.Column("source", sa.String(20), nullable=False, server_default="telegram"),
        sa.Column("source_message_id", sa.BigInteger()),
        sa.Column("source_date", sa.DateTime(timezone=True)),
        # Content
        sa.Column("url", sa.Text()),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("title", sa.String(500)),
        sa.Column("content_type", sa.String(20), server_default="other"),
        sa.Column("media_file_id", sa.String(255)),
        # AI-generated
        sa.Column("summary", sa.Text()),
        sa.Column("category", sa.String(30)),
        sa.Column("language", sa.String(10)),
        # Search
        sa.Column("embedding", Vector(1024)),
        sa.Column("search_vector", TSVECTOR()),
        # Processing state
        sa.Column("ai_status", sa.String(20), server_default="pending"),
        sa.Column("ai_error", sa.Text()),
        sa.Column("ai_processed_at", sa.DateTime(timezone=True)),
        sa.Column("retry_count", sa.Integer(), server_default="0"),
        # User state
        sa.Column("is_favorite", sa.Boolean(), server_default="false"),
        sa.Column("is_archived", sa.Boolean(), server_default="false"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("last_accessed", sa.DateTime(timezone=True)),
    )

    op.create_index("idx_bookmarks_user_id", "bookmarks", ["user_id"])
    op.create_index("idx_bookmarks_user_created", "bookmarks", ["user_id", "created_at"])
    op.create_index(
        "idx_bookmarks_ai_pending", "bookmarks", ["ai_status"],
        postgresql_where=sa.text("ai_status != 'completed'"),
    )
    op.create_index(
        "idx_bookmarks_source_dedup", "bookmarks",
        ["user_id", "source", "source_message_id"],
        unique=True,
        postgresql_where=sa.text("source_message_id IS NOT NULL"),
    )
    op.create_index(
        "idx_bookmarks_search_vector", "bookmarks", ["search_vector"],
        postgresql_using="gin",
    )
    op.create_index(
        "idx_bookmarks_embedding", "bookmarks", ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("idx_bookmarks_category", "bookmarks", ["user_id", "category"])

    # --- Tags ---
    op.create_table(
        "tags",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("color", sa.String(7)),
        sa.Column("bookmarks_count", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "name", name="uq_tag_user_name"),
    )
    op.create_index("idx_tags_user", "tags", ["user_id"])

    # --- Bookmark Tags (M2M) ---
    op.create_table(
        "bookmark_tags",
        sa.Column("bookmark_id", UUID(as_uuid=True), sa.ForeignKey("bookmarks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", UUID(as_uuid=True), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("idx_bookmark_tags_tag", "bookmark_tags", ["tag_id"])

    # --- search_vector auto-update trigger ---
    op.execute("""
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
    """)

    op.execute("""
        CREATE TRIGGER bookmarks_search_vector_trigger
            BEFORE INSERT OR UPDATE OF title, raw_text, summary
            ON bookmarks
            FOR EACH ROW
            EXECUTE FUNCTION bookmarks_search_vector_update();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS bookmarks_search_vector_trigger ON bookmarks")
    op.execute("DROP FUNCTION IF EXISTS bookmarks_search_vector_update()")
    op.drop_table("bookmark_tags")
    op.drop_table("tags")
    op.drop_table("bookmarks")
    op.drop_table("users")
    op.execute('DROP EXTENSION IF EXISTS "pg_trgm"')
    op.execute('DROP EXTENSION IF EXISTS "vector"')
